# src/db.rs：共享数据、过期索引与频道的唯一持有处

<!-- analyzes: src/db.rs -->

[打开对应源码](../../../src/db.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

Db 对外提供 get/set/subscribe/publish，内部通过 Arc<Shared> 共享状态。此文件还负责后台清理任务的创建和停止，所以它既是存储模块，也是几个异步任务之间的状态接缝。

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
| Db | Arc<Shared> | 可克隆的访问句柄 |
| Shared | Mutex<State>、Notify | 数据同步及后台唤醒 |
| State / Entry | 主表、频道表、过期集合、停止标记 / Bytes、到期时刻 | 记录当前数据库事实 |

Db::new 每个服务实例创建一次，克隆 Db 不会复制整张表。清理任务另持一个 Arc；所以不能等最后一个 Arc 消失才通知清理任务退出，否则后台自己的持有关系会让逻辑难以结束。

## get 先在锁内取得独立可用的值

<!-- source: src/db.rs:145-152; comments omitted -->
```rust
pub(crate) fn get(&self, key: &str) -> Option<Bytes> {
    let state = self.shared.state.lock().unwrap();
    state.entries.get(key).map(|entry| entry.data.clone())
}
```

直接调用者是 Get::apply，返回的 Bytes 随后放入响应 Frame。克隆字节句柄使锁可以在发送网络之前释放；同名 key 随后被覆盖时，已构造的响应仍持有读取时的值。此函数没有检查 expires_at，后台未及时删除时，GET 可能暂时见到已到期值。

## set 的顺序保证两张结构一致

<!-- source: src/db.rs:158-219; comments omitted -->
```rust
pub(crate) fn set(&self, key: String, value: Bytes, expire: Option<Duration>) {
    let mut state = self.shared.state.lock().unwrap();

    let mut notify = false;

    let expires_at = expire.map(|duration| {
        let when = Instant::now() + duration;

        notify = state
            .next_expiration()
            .map(|expiration| expiration > when)
            .unwrap_or(true);

        when
    });

    let prev = state.entries.insert(
        key.clone(),
        Entry {
            data: value,
            expires_at,
        },
    );

    if let Some(prev) = prev {
        if let Some(when) = prev.expires_at {
            state.expirations.remove(&(when, key.clone()));
        }
    }

    if let Some(when) = expires_at {
        state.expirations.insert((when, key));
    }

    drop(state);

    if notify {
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

## 读完后沿哪里继续

[src/cmd/get.rs](cmd/get.md) → [src/cmd/set.rs](cmd/set.md) → [src/cmd/subscribe.rs](cmd/subscribe.md) → [src/cmd/publish.rs](cmd/publish.md) → [src/server.rs](server.md)。

跨文件串读：[第 06 章与第 07 章的共享存储主线](../../06-shared-storage.md)。
