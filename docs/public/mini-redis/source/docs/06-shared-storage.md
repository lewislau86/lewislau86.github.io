# 06 数据如何安全地共享

[上一章](05-tokio-server.md) · [目录](README.md) · [下一章](07-expiration.md)

本章对应的独立源码文章：[src/db.rs](source/src/db.md)、[src/cmd/get.rs](source/src/cmd/get.md)、[src/cmd/set.rs](source/src/cmd/set.md)。完整的一一对应关系见 [源码文章索引](source/README.md)。

两个客户端分别有自己的 Handler，但必须看到同一份键值表。为每个 Handler 深拷贝一个数据库会把它们变成互不相干的数据岛；只共享一个没有同步保护的可变表，又会引入数据竞争。

## 谁创建这份数据，谁会读写它

```text
server::run → DbDropGuard::new → Db::new → 创建 Shared 并 spawn 清理任务
Listener::run → DbDropGuard::db → clone Db → 放进各 Handler
Handler::run → Command::apply
                 ├→ Set::apply → Db::set → 修改 entries / expirations
                 ├→ Get::apply → Db::get → 返回 Bytes → 写回连接
                 └→ Publish / Subscribe → Db 的频道方法（第 08 章）
后台 purge_expired_tasks → Shared::purge_expired_keys → 删除到期记录
```

Db::new 的调用次数很重要：当前每个 server::run 实例创建一份，而不是每次 accept 创建一份。假如把 Db::new 放进每个 Handler 的构造，客户端 A 写入、客户端 B 读取的行为就会被改变。反过来，Db::get/set 没有主动接收 socket；只有命令执行层把已经解析的参数交进来。

## 从外到内拆开 Db

[db.rs](../src/db.rs) 的核心布局是：

```text
Handler A ── Db ── Arc ─┐
Handler B ── Db ── Arc ─┼─→ Shared
清理任务 ──────── Arc ─┘     ├─ Mutex<State>
                             │    ├─ entries: HashMap<String, Entry>
                             │    ├─ pub_sub: HashMap<String, Sender<Bytes>>
                             │    ├─ expirations: BTreeSet<(Instant, String)>
                             │    └─ shutdown: bool
                             └─ background_task: Notify
```

`Arc` 是原子引用计数的共享所有权指针。`Db` derive Clone 时会 clone 它的 Arc 字段，增加引用计数，所有句柄仍指向同一份 Shared。只有最后一个拥有者释放后，Shared 才能被销毁。

Arc 解决“资源由谁共同拥有”，Mutex 解决“此刻谁可以访问可变状态”。Arc 自己不会让任何内部类型自动变成线程安全的容器。

## 锁通过 Guard 表示访问权

源码中的 GET 非常短：

```rust
pub(crate) fn get(&self, key: &str) -> Option<Bytes> {
    let state = self.shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
}
```

`lock()` 成功后返回 Guard。通过 Guard 能访问被保护的数据，Guard drop 时自动解锁。`unwrap()` 表示本代码没有从锁中毒恢复；若持锁线程 panic，后续取锁可能因 poison 而 panic。

`HashMap::get` 返回 `Option<&Entry>`。`.map(|entry| ...)` 在 Some 时执行闭包，在 None 时保持 None。竖线中的 `entry` 是闭包参数；闭包可以捕获周围变量，第 07 章中 `expire.map` 就会更新外部的 notify 标记。

这里返回 clone 出来的 Bytes，而不是 `&Entry` 或 `&Bytes`。这样函数离开、锁已释放之后，响应仍独立持有字节资源，不会引用未来可能被其他写操作删除的表项。

## 把 GET 的返回值交回 Get::apply

上面 get 的直接调用者是 [Get::apply](../src/cmd/get.rs)，不是 Client。调用期间只借用 `self.key`；函数返回的 Bytes 由响应 Frame 继续持有，随后交给 Connection::write_frame。沿这条链看，clone 的目的首先是让“数据库锁的生命周期”和“网络响应的生命周期”分开。

如果另一连接随后 SET 覆盖同名键，数据库表项可以换成新值，而已经构造好的 GET 响应仍持有旧字节；它是这次读取获得的结果，不会在发送途中突然换成新值。若改成返回表内引用，上层就不能在不保留相应保护的情况下安全跨网络 await 使用它。

## SET 一次改变哪些共享结构

调用者 [Set::apply](../src/cmd/set.rs) 先调用 Db::set，再写 OK。下面取出 [Db::set](../src/db.rs) 中更新两张表的连续代码；进入这段前已取得 state 锁并算好 expires_at、notify：

<!-- source: src/db.rs:134-163; comments included -->
```rust
// insert 返回被替换的旧 Entry，供下面撤销旧过期索引。
    let prev = state.entries.insert(
        key.clone(),
        Entry {
            data: value,
            expires_at,
        },
    );

    // 即使这次不带 TTL，也要撤销被覆盖记录的旧期限。
    if let Some(prev) = prev {
        if let Some(when) = prev.expires_at {
            // 移除旧 (时刻, 键) 元组，防止未来误删新值。
            state.expirations.remove(&(when, key.clone()));
        }
    }

    // 先删除旧索引，再插入新索引；相同元组若反过来操作，会误删刚插入的记录。
    if let Some(when) = expires_at {
        state.expirations.insert((when, key));
    }

    // 显式 drop MutexGuard 提前解锁，让被唤醒的任务可以立即竞争锁。
    drop(state);

    if notify {
        // Notify 只是提醒重新查看共享索引，不为每次 SET 创建一份清理任务。
        self.shared.background_task.notify_one();
    }
}
```

`entries.insert` 返回旧 Entry，供随后撤销旧索引；即使新值不带 TTL，也必须执行这个撤销步骤。新索引先不插入，是为了避免新旧 `(when, key)` 相同的时候把刚插入的新记录一起删掉。两张结构受同一把锁保护，其他 get/set 与清理任务不会在这个临界区中途看见只改了一半的状态。

这段源码的影响超出了返回值：set 返回 `()`，但已替换共享表项，可能撤销旧 deadline、增加新 deadline，还可能通过 Notify 改变后台任务的下一次唤醒时间。最后一个影响继续追[第 07 章](07-expiration.md)。

| 执行场景 | entries 的变化 | expirations 的变化 | 对调用者及其他任务的影响 |
| --- | --- | --- | --- |
| 新键，无 TTL | 插入新值 | 不增加索引 | Set::apply 准备 OK，后续 GET 可读 |
| 旧键有 TTL，新值永久 | 覆盖 Entry | 删除旧索引，不插入新索引 | 旧 deadline 不能再删除这个新值 |
| 旧键改为更早 TTL | 覆盖值和时间 | 删旧、加新；按最早时间判断 notify | 清理任务可能提前醒来 |
| 解锁后响应写失败 | 不回滚已写值 | 不撤销本次索引更新 | 原客户端报错，其他连接仍可能读到新值 |


## 为什么 Bytes 的 clone 合适

`String::clone()` 为新字符串复制内容。Bytes 的 clone 可以廉价地共享底层字节存储，不必为了每次 GET 复制整个值。网络发送仍需处理实际字节，帧解析也可能复制数据，不能据此称整个请求零拷贝。

`GET big` 时，锁内只找到 Entry 并克隆 Bytes 句柄；写网络发生在锁外。大值仍然会增加网络和编码成本，但不会因为发送期间等待 socket 而一直占着数据库锁。

键仍然用 String。SET 要同时维护主表和过期索引，两处各自需要拥有键，所以你会看到 `key.clone()`。这是为了独立持有键的内存，不是 Arc 式共享数据库。

## 异步服务器为何用标准库 Mutex

这些临界区只修改内存结构，没有 await。短暂、低争用的同步临界区可以使用标准库 Mutex，官方 [Tokio 共享状态教程](https://tokio.rs/tokio/tutorial/shared-state)也讨论了这种选择。若争用激烈，它仍会阻塞执行线程；异步并不会消除这项代价。

不应把源码改成“拿着锁去等网络”：

```text
不合适的顺序：加锁 → 找到值 → await 网络发送 → 解锁
本地实际顺序：加锁 → 克隆值句柄 → 解锁 → await 网络发送
```

若工作本身需要持有独占资源跨 await，可能需要 Tokio Mutex，或者用一个任务拥有资源、其他任务发消息的方案；后者正是 BufferedClient 的设计。选择依据是访问模式，而不是“用了 async 就必须换所有锁”。

教学示例中可以用显式作用域保证 Guard 在 await 前销毁：

```rust
let value = {
    let state = shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
};
// 到这里 state Guard 已销毁；之后才执行网络 await。
```

## HashMap 是键空间，不是完整 Redis 数据模型

`entries` 负责按键定位，平均查询复杂度可视为 O(1)，但计算哈希还与键长度相关。Entry 同时存 Bytes 和可选到期时间。多个连接执行一次本地 set/get 时，Mutex 让这一小段状态访问互斥。

这不等于客户端的“GET → 计算 → SET”整体原子：两个连接仍可能在两个命令之间交错，造成更新丢失。命令级互斥与多命令事务是两个问题。本项目没有提供事务或原子递增命令。

源码里 `let state = &mut *state;` 又是什么？原来的 state 是 MutexGuard，`*state` 经 DerefMut 访问其内部 State，`&mut` 再借用 State。这样编译器能够更直接地分析对 `entries` 和 `expirations` 两个不同字段的借用。它不是新建一份 State，也不是强制绕过借用规则。

如果 Db 只有 Arc、没有 Mutex，多个 Handler 就能安全地修改 HashMap 吗？

<details>
<summary>参考答案</summary>

不能。Arc 只管理共享所有权和引用计数；内部可变数据仍需要同步或其他安全的访问策略。当前类型组合使用 Mutex 保护 State，并把锁的存活限制在同步方法中。

</details>
