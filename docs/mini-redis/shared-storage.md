---
title: "第 6 章：数据如何安全地共享"
description: "多个连接怎样访问同一张表？"
pageClass: mini-redis-course
---

# 第 6 章：数据如何安全地共享

[课程总览](/mini-redis/index.md) · [上一章](/mini-redis/tokio-server.md) · [下一章](/mini-redis/expiration.md)

::: tip 本章学习目标
**要解决的问题：** 多个连接怎样访问同一张表？

**顺路学到的 Rust：** Arc、Mutex、内部可变性、闭包、RAII

**对应源码：** [src/db.rs](/mini-redis/source/src/db.md)、[src/cmd/get.rs](/mini-redis/source/src/cmd/get.md)、[src/cmd/set.rs](/mini-redis/source/src/cmd/set.md)。完整的一一对应关系见 [源码文章索引](/mini-redis/source/index.md)。
:::

<MiniRedisMap active="shared-storage" />

两个客户端分别有自己的 Handler，但必须看到同一份键值表。为每个 Handler 深拷贝一个数据库会把它们变成互不相干的数据岛；只共享一个没有同步保护的可变表，又会引入数据竞争。

## 谁创建这份数据，谁会读写它

```text
server::run → DbDropGuard::new → Db::new → 创建 Shared 并 spawn 清理任务
Listener::run → DbDropGuard::db → clone Db → 放进各 Handler
Handler::run → Command::apply
                 ├→ Set::apply → Db::set → 修改 entries / expirations
                 ├→ Get::apply → Db::get → 返回 Bytes → 写回连接
                 └→ Publish / Subscribe → Db 的频道方法（第 8 章）
后台 purge_expired_tasks → Shared::purge_expired_keys → 删除到期记录
```

Db::new 的调用次数很重要：每个 server::run 实例只创建一份，所有 accept 得到的连接共用它，客户端 A 写入的值客户端 B 才能读到。Db::get/set 只接收命令执行层交来的、已经解析好的参数，不接触 socket。

## 从外到内拆开 Db

[db.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 的核心布局是：

![Handler A、Handler B 和后台清理任务各持一个 Db，经 Arc 指向同一份 Shared；Shared 内的 Mutex 保护 entries、expirations、pub_sub、shutdown，Notify 在锁外](/mini-redis/figures/shared-state.svg)

`Arc` 是原子引用计数的共享所有权指针。`Db` derive Clone 时会 clone 它的 Arc 字段，增加引用计数，所有句柄仍指向同一份 Shared。只有最后一个拥有者释放后，Shared 才能被销毁。

Arc 解决“资源由谁共同拥有”，Mutex 解决“此刻谁可以访问可变状态”，两者各管一件事，组合起来才是可共享、可修改的状态。

## 锁通过 Guard 表示访问权

源码中的 GET 非常短：

```rust
pub(crate) fn get(&self, key: &str) -> Option<Bytes> {
    let state = self.shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
}
```

`lock()` 成功后返回 Guard。通过 Guard 能访问被保护的数据，Guard drop 时自动解锁。`unwrap()` 表示本代码没有从锁中毒恢复；若持锁线程 panic，后续取锁可能因 poison 而 panic。

`HashMap::get` 返回 `Option<&Entry>`。`.map(|entry| ...)` 在 Some 时执行闭包，在 None 时保持 None。竖线中的 `entry` 是闭包参数；闭包可以捕获周围变量，第 7 章中 `expire.map` 就会更新外部的 notify 标记。

这里返回 clone 出来的 Bytes。函数返回、锁释放之后，响应仍独立持有这份字节，与表项之后是否被修改或删除无关。

## 把 GET 的返回值交回 Get::apply

上面 get 的直接调用者是服务端的 [Get::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/get.rs)。调用期间只借用 `self.key`；函数返回的 Bytes 由响应 Frame 继续持有，随后交给 Connection::write_frame。沿这条链看，clone 的目的首先是让“数据库锁的生命周期”和“网络响应的生命周期”分开。

如果另一连接随后 SET 覆盖同名键，表项换成新值，已经构造好的 GET 响应仍持有旧字节：它代表这次读取得到的结果，发送途中保持不变。返回表内引用则意味着上层必须一直持锁到网络发送结束。

## SET 一次改变哪些共享结构

调用者 [Set::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/set.rs) 先调用 Db::set，再写 OK。下面取出 [Db::set](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 中更新两张表的连续代码；进入这段前已取得 state 锁并算好 expires_at、notify：

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

这段源码的影响超出了返回值：set 返回 `()`，但已替换共享表项，可能撤销旧 deadline、增加新 deadline，还可能通过 Notify 改变后台任务的下一次唤醒时间。最后一个影响继续追[第 7 章](/mini-redis/expiration.md)。

| 执行场景 | entries 的变化 | expirations 的变化 | 对调用者及其他任务的影响 |
| --- | --- | --- | --- |
| 新键，无 TTL | 插入新值 | 不增加索引 | Set::apply 准备 OK，后续 GET 可读 |
| 旧键有 TTL，新值永久 | 覆盖 Entry | 删除旧索引，不插入新索引 | 旧 deadline 不能再删除这个新值 |
| 旧键改为更早 TTL | 覆盖值和时间 | 删旧、加新；按最早时间判断 notify | 清理任务可能提前醒来 |
| 解锁后响应写失败 | 不回滚已写值 | 不撤销本次索引更新 | 原客户端报错，其他连接仍可能读到新值 |


## 为什么 Bytes 的 clone 合适

`String::clone()` 为新字符串复制内容。Bytes 的 clone 只增加引用计数、共享底层字节存储，每次 GET 都不必复制整个值。

`GET big` 时，锁内只找到 Entry 并克隆 Bytes 句柄；写网络发生在锁外。大值仍然会增加网络和编码成本，但不会因为发送期间等待 socket 而一直占着数据库锁。

键仍然用 String。SET 要同时维护主表和过期索引，两处各自需要拥有键，所以你会看到 `key.clone()`：它复制的是键本身。

## 异步服务器为何用标准库 Mutex

这些临界区只修改内存结构，没有 await。短暂、低争用的同步临界区可以使用标准库 Mutex，官方 [Tokio 共享状态教程](https://tokio.rs/tokio/tutorial/shared-state)也讨论了这种选择。若争用激烈，它仍会阻塞执行线程；异步并不会消除这项代价。

锁只覆盖内存操作，网络等待放在锁外：

![错误做法在持锁期间 await 网络发送；mini-redis 加锁、找到值、克隆 Bytes 句柄后立即解锁，再在锁外等待网络](/mini-redis/figures/lock-scope.svg)

若工作本身需要持有独占资源跨 await，可能需要 Tokio Mutex，或者用一个任务拥有资源、其他任务发消息的方案；后者正是 BufferedClient 的设计。选择依据是访问模式：临界区里有没有 await、争用是否激烈。

教学示例中可以用显式作用域保证 Guard 在 await 前销毁：

```rust
let value = {
    let state = shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
};
// 到这里 state Guard 已销毁；之后才执行网络 await。
```

## HashMap 承担键空间

`entries` 负责按键定位，平均查询复杂度可视为 O(1)，但计算哈希还与键长度相关。Entry 同时存 Bytes 和可选到期时间。多个连接执行一次本地 set/get 时，Mutex 让这一小段状态访问互斥。

Mutex 保证的是“单个命令内部”的互斥。客户端的“GET → 计算 → SET”是三个命令，两个连接仍可能在命令之间交错，造成更新丢失；要让多命令整体原子，需要事务或原子递增这类命令，本项目没有实现。

源码里 `let state = &mut *state;` 又是什么？原来的 state 是 MutexGuard，`*state` 经 DerefMut 访问其内部 State，`&mut` 再借用 State。这样编译器能够直接看出对 `entries` 和 `expirations` 两个不同字段的借用互不重叠。它借用的仍是锁内那一份 State。

::: warning 常见误区
- **Arc 不提供可变访问的安全。** 它只管理共享所有权和引用计数，修改内部数据还要靠 Mutex 等同步手段。
- **Bytes 的 clone 不等于整个请求零拷贝。** 它省掉的是 GET 时复制值；网络发送仍处理实际字节，帧解析也可能复制数据。
- **单命令互斥不等于多命令原子。** “GET → 计算 → SET”之间可以被其他连接插入。
- **用了 async 不必把所有锁都换成 Tokio Mutex。** 临界区里没有 await、争用不高时，标准库 Mutex 更简单。
:::

## 本章结论 {#summary}

所有连接共享同一份数据，靠的是两层结构：`Db` 句柄里的 `Arc` 让多个任务共同拥有一份 `Shared`，`Shared` 里的 `Mutex` 保证同一时刻只有一个任务修改 `State`。mini-redis 把锁的范围压缩到纯内存操作：GET 在锁内克隆 Bytes 句柄后立即解锁，SET 在同一个临界区里同时更新 entries 和过期索引，网络读写都发生在锁外。

## 检查理解

1. 如果 Db 只有 Arc、没有 Mutex，多个 Handler 就能安全地修改 HashMap 吗？

   <details><summary>参考答案</summary>

   不能。Arc 只管理共享所有权和引用计数；内部可变数据仍需要同步或其他安全的访问策略。当前类型组合使用 Mutex 保护 State，并把锁的存活限制在同步方法中。

   </details>

2. 把 `Db::new` 移到每个 Handler 的构造函数里，会出现什么现象？

   <details><summary>参考答案</summary>

   每个连接拥有一份独立的数据库。客户端 A 用一条连接 SET 的值，客户端 B 用另一条连接 GET 不到。

   </details>

3. `Db::get` 为什么返回克隆的 `Bytes`，而不是 `&Bytes`？

   <details><summary>参考答案</summary>

   返回值要交给响应帧，并在锁释放后跨网络 await 发送。克隆的 Bytes 独立持有数据（只增加引用计数），返回引用则必须一直持锁到发送结束。

   </details>

4. `Db::set` 为什么先删除旧的过期索引，再插入新的？

   <details><summary>参考答案</summary>

   新旧 `(when, key)` 可能完全相同。若先插入再删除，会把刚插入的新索引一起删掉。

   </details>

下一章追踪 SET 带上 TTL 之后，到期的数据由谁、在什么时候删除：[第 7 章：到期的数据由谁删除](/mini-redis/expiration.md)。
