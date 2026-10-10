---
editLink: false
---

# src/db.rs：共享数据、过期索引与频道的唯一持有处

<!-- analyzes: src/db.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

Db 对外提供 get/set/subscribe/publish，内部通过 Arc&lt;Shared> 共享状态。此文件还负责后台清理任务的创建和停止，所以它既是存储模块，也是几个异步任务之间的状态接缝。

## 它和哪些代码交互

```text
server::run → DbDropGuard::new → Db::new → spawn purge_expired_tasks
Listener → DbDropGuard::db → clone Db → Handler
Get/Set::apply → Db::get/set → Mutex<State>
Subscribe/Publish → Db::subscribe/publish → broadcast
DbDropGuard::drop → shutdown_purge_task → Notify → 后台退出
```

## 四种类型各持有什么

| 类型 | 持有资源 | 生命周期责任 |
| --- | --- | --- |
| DbDropGuard | 一个 Db | 服务持有者析构时通知清理停止 |
| Db | Arc&lt;Shared> | 可克隆的访问句柄 |
| Shared | Mutex&lt;State>、Notify | 数据同步及后台唤醒 |
| State / Entry | 主表、频道表、过期集合、停止标记 / Bytes、到期时刻 | 记录当前数据库事实 |

Db::new 每个服务实例创建一次，克隆 Db 不会复制整张表。清理任务另持一个 Arc；所以不能等最后一个 Arc 消失才通知清理任务退出，否则后台自己的持有关系会让逻辑难以结束。

## get 先在锁内取得独立可用的值

<!-- source: src/db.rs:106-111; comments included -->
```rust
pub(crate) fn get(&self, key: &str) -> Option<Bytes> {
    // lock 返回 MutexGuard，离开作用域时自动解锁；unwrap 在锁中毒时会 panic。
    // 返回 Bytes 克隆使后续网络写不必继续持锁。
    let state = self.shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
}
```

直接调用者是 Get::apply，返回的 Bytes 随后放入响应 Frame。克隆字节句柄使锁可以在发送网络之前释放；同名 key 随后被覆盖时，已构造的响应仍持有读取时的值。此函数没有检查 expires_at，后台未及时删除时，GET 可能暂时见到已到期值。

## set 的顺序保证两张结构一致

<!-- source: src/db.rs:115-163; comments included -->
```rust
pub(crate) fn set(&self, key: String, value: Bytes, expire: Option<Duration>) {
    let mut state = self.shared.state.lock().unwrap();

    // 先判断是否需要重排后台等待；只有新期限比当前最早期限更早时才需要唤醒。
    let mut notify = false;

    let expires_at = expire.map(|duration| {
        // Option::map 只在 Some(duration) 时运行闭包，将相对时长转为绝对时刻。
        let when = Instant::now() + duration;

        // 若没有旧期限，unwrap_or(true) 表示需要唤醒原本只等 Notify 的任务。
        notify = state
            .next_expiration()
            .map(|expiration| expiration > when)
            .unwrap_or(true);

        when
    });

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

先算 deadline 与是否需要提前唤醒，再 insert 主表并取得旧 Entry，移除旧索引后插入新索引。删除旧索引必须先于插入新索引，避免新旧元组相同时误删新记录；不带新 TTL 时同样要撤销旧 TTL。

最后解锁才 notify，减少被唤醒者立刻争锁。set 返回 unit 但已产生共享状态副作用，Set::apply 随后的响应写失败不会回滚这里。

## 后台怎样消费索引

purge_expired_tasks 每轮先检查停止状态，再调用 Shared::purge_expired_keys。后者持同一把锁，从 BTreeSet 最早元素开始删除，遇到未来时刻返回 Some(when)，全部清完返回 None。后台以这个结果选择 sleep_until/Notify 或只等 Notify。

State::next_expiration 只读最早时刻，供 set 判断是否重排等待。大批键同时到期时，一轮清理会在锁内删除多条，所以它可能影响前台锁等待。notify 不是一键一个任务的队列，索引才是任务恢复后检查的事实来源。

## 频道与键值不是一个命名空间

subscribe 在 pub_sub 中复用 Sender 或建立容量 1024 的 broadcast；调用者取得 Receiver，交给订阅连接的流。publish 查找频道并 send，失败或无频道返回 0。频道表项不会因最后一个 Receiver 释放而自动删除，这与主表键过期无关。

shutdown_purge_task 持锁设 shutdown=true，解锁后 notify；DbDropGuard 的 Drop 是触发者。清理任务没有显式 JoinHandle 确认，通知停止与确认已退出要分开理解。

## 修改不能只盯一张 HashMap

增加 DEL 或访问时过期判断，都应同时维护主表与索引；分片锁要重新设计跨结构一致性；频道回收要协调新订阅与发布。验证 GET/SET 只是起点，还要验证覆盖 TTL、集中到期、跨连接可见性和停止唤醒。

## 这里的 Rust 写法：为什么 &self 仍然能写数据库

Db 只通过 &self 共享借用句柄，Mutex 在运行时提供对 State 的独占访问，因此修改不用把整个 Db 变成 &mut。Guard 是锁的持有凭据，drop 负责解锁；Arc 只管共享存活，不能替代锁。`let state = &mut *state` 是通过 DerefMut 借到结构体并遮蔽变量，让字段借用可拆分，原锁并没有释放。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](/mini-redis/rust-reading-guide.md#guards)。

## 测试模块怎样验证过期而不引入网络时序

文件末尾新增 `#[cfg(test)] mod tests`，仅在测试构建启用。expiration_boundary 在暂停时钟下检查 999ms 仍存在、1000ms 清理后缺失；background_expiration 不主动调用清理，等待后台删除并确认无 TTL 的键仍保留。这两项分别验证算法边界和任务是否工作，避免 TCP 等待触发虚拟时间自动前进的干扰。完整过程见 [TTL 测试排查](/mini-redis/13-ttl-test-debugging.md)。

## 读完后沿哪里继续

[src/cmd/get.rs](/mini-redis/source/src/cmd/get.md) → [src/cmd/set.rs](/mini-redis/source/src/cmd/set.md) → [src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md) → [src/cmd/publish.rs](/mini-redis/source/src/cmd/publish.md) → [src/server.rs](/mini-redis/source/src/server.md)。

跨文件串读：[第 06 章与第 07 章的共享存储主线](/mini-redis/06-shared-storage.md)。
