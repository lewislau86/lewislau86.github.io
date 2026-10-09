# 07 到期的数据由谁删除

[上一章](06-shared-storage.md) · [目录](README.md) · [下一章](08-pubsub.md)

`SET session token PX 1000` 不只是插入一行数据，还给服务器增加了一项未来工作。一秒后即使没有新的请求，这个键也应该被清理。问题变成：如何安排下一次唤醒，如何在键被覆盖时取消旧安排？

## 这不是 SET 内部的一次 sleep

```text
连接任务 A：Set::apply → Db::set → 修改共享索引 → notify_one → 返回 → 写 OK
                                              │ 通知，非直接调用
                                              ▼
后台任务：Db::new 时 spawn 的 purge_expired_tasks
              → Shared::purge_expired_keys
              → 返回下一次 deadline 或 None
              → sleep_until / notified → 下一轮检查
连接任务 B：Get::apply → Db::get → 观察清理前或清理后的 entries
```

SET 不会等一秒再返回 OK，也不会为每个过期键各 spawn 一个 sleep 任务。后台任务在 Db::new 时就已创建，生命周期属于该服务实例；它通过共享索引知道该删除什么，Notify 只提示它重新查看。

这解释了一个跨章节关系：第 06 章保证写入时两张表一致，本章保证后台如何消费这份索引；两者共同决定其他连接随后 GET 的结果。

## 一份值，两种索引

[State](../src/db.rs) 同时维护：

```text
entries["session"] = Entry { data: token, expires_at: Some(t1) }
expirations         = { (t1, "session"), (t2, "another") }
```

HashMap 回答“这个键的值是什么”；BTreeSet 回答“最早什么时候有键到期”。只用 HashMap 就需要寻找全表最小时间；有序索引让清理任务直接查看集合的第一个元素。

元组按字段顺序比较：先比 Instant，再比 String。这样两个键即使同一时刻过期，也可同时放进集合。索引的插入/删除通常是 O(log n)，每次清理处理已到期前缀，而不是遍历所有未到期键。

`Duration` 表示一段时间，`Instant` 表示单调时间轴上的时刻，避免把 TTL 调度混同于可校时的墙上时钟。本地使用 Tokio Instant，才能配合虚拟时间测试。

## 覆盖 SET 时，要把旧闹钟撤掉

`Db::set` 在同一把锁内依次完成：

1. 如果带 TTL，计算 `when = Instant::now() + duration`。
2. 判断它是否比原来最早的过期时间更早，记录是否需要 notify。
3. 向 entries 插入新 Entry，接住 `insert` 返回的旧值。
4. 如果旧值有 expires_at，从 expirations 删除 `(旧时间, key)`。
5. 如果新值有 expires_at，插入 `(新时间, key)`。
6. 释放锁，再按需 `notify_one()`。

假设第一次 `SET a old PX 1000`，过了 100 毫秒又执行 `SET a new PX 10000`。若旧索引未移除，一秒时清理任务就可能按旧记录删除新值。两张结构必须一起更新，锁保护的也包括这个跨结构不变量。

如果第二次 SET 不带 TTL，它会移除旧过期索引，并将新 Entry 的 expires_at 设为 None。本版本没有独立的 EXPIRE、TTL 查询命令，只通过 SET 选项设置过期。

## 从 Db::set 的唤醒判断追到后台

[Db::set](../src/db.rs) 在插入新记录前计算到期时间及通知条件：

<!-- source: src/db.rs:166-181; comments omitted -->
```rust
let mut notify = false;

let expires_at = expire.map(|duration| {
    let when = Instant::now() + duration;

    notify = state
        .next_expiration()
        .map(|expiration| expiration > when)
        .unwrap_or(true);

    when
});
```

这里 `next_expiration()` 读取的是更新前的最早时间。`unwrap_or(true)` 表示原来根本没有 deadline，现在必须把只等 Notify 的任务唤醒；若新 deadline 更早，也必须唤醒。notify 为 false 不代表这次 SET 没有过期，而是原来的唤醒安排仍足以覆盖新时间，或最多造成一次多余的提前醒来。

接着按第 06 章展示的代码更新 entries/expirations、drop(state)，才调用 notify_one。若仍持有同一把锁时通知，接收者会先等待锁，不能直接读到临界区中途的状态，但可能增加无用的锁等待；若改成先通知、再另行加锁更新，就可能让接收者先看到旧安排。若彻底删掉通知，后台原来只等 Notify 时，第一条 TTL 键就没有正确的计时安排。


## 后台任务不必固定频率轮询

`Db::new` spawn 了 `purge_expired_tasks(shared.clone())`。循环先调用 `purge_expired_keys`：锁住状态，从最早元素开始删除所有已到期键，若遇到未来时刻就把该时刻返回。

```text
有下一次到期时间 → 等待 sleep_until(when) 或 Notify
没有待过期键     → 仅等待 Notify
被唤醒           → 重新读取共享状态、清理、计算下一次等待
```

直接看 [purge_expired_tasks](../src/db.rs) 的源码，它是 Db::new 提交给 Tokio 的任务入口：

<!-- source: src/db.rs:346-369; comments omitted -->
```rust
async fn purge_expired_tasks(shared: Arc<Shared>) {
    while !shared.is_shutdown() {
        if let Some(when) = shared.purge_expired_keys() {
            tokio::select! {
                _ = time::sleep_until(when) => {}
                _ = shared.background_task.notified() => {}
            }
        } else {
            shared.background_task.notified().await;
        }
    }

    debug!("Purge background task shut down")
}
```

`purge_expired_keys` 的返回值不是“刚删掉了哪个键”，而是“下一次应等待到什么时候”。其中 None 也不是整个任务结束：循环转为等 Notify。真正决定退出的是下一轮的 is_shutdown。

再进入它调用的 [Shared::purge_expired_keys](../src/db.rs)：

<!-- source: src/db.rs:290-322; comments omitted -->
```rust
fn purge_expired_keys(&self) -> Option<Instant> {
    let mut state = self.state.lock().unwrap();

    if state.shutdown {
        return None;
    }

    let state = &mut *state;

    let now = Instant::now();

    while let Some(&(when, ref key)) = state.expirations.iter().next() {
        if when > now {
            return Some(when);
        }

        state.entries.remove(key);
        state.expirations.remove(&(when, key.clone()));
    }

    None
}
```

这段代码取得与请求任务相同的 Mutex，移除 entries 与对应索引。`when > now` 立即返回未来时间，因为后面的有序元素也不会更早。大量同时到期键会在一次持锁循环中被处理，所以影响既包括“哪些值不再可见”，也包括“其他连接等这把锁多久”。

| 返回/事件 | 谁接着执行 | 可观察影响 |
| --- | --- | --- |
| Some(when) | 后台 select 等计时器或 Notify | 当前未到期键保留，睡到合适时机再查 |
| None，且没有 shutdown | 后台等 Notify | 没有新 TTL/停止通知时不忙轮询 |
| 清理删除完成 | 解锁后其他 Handler 可进入 Db | GET 得到 None，而不是旧值 |
| shutdown 标记 + Notify | 等待中的后台醒来，下一轮退出 | 不再安排清理，但无网络响应由此直接产生 |


为什么不能只 sleep_until？假设任务正在等十秒后的 A，新请求插入一秒后的 B；没有通知就会晚九秒处理 B。因此插入新的最早 deadline 时要唤醒任务重新计算。

Notify 不携带键或命令，它的意思只是“状态可能变了，请重看”。多次 notify 可以合并，不应该把它当精确计数队列。这里正确性来自共享状态才是事实来源：即使通知合并，重新检查有序索引仍会找到所有到期项。

若最早的键被改成更晚时间或永久键，代码有时不会马上唤醒原来的等待；旧计时器会造成一次提前醒来，但重新检查索引后不会误删新值。这种多余唤醒和错删是两种性质不同的问题。

## 一个必须看实现的细节

当前 `Db::get` **没有检查 expires_at**，它只从 entries 中取值。因此在名义到期之后、清理任务实际得到调度之前，GET 仍可能拿到旧值。这份实现不能提供“任何 GET 都绝不返回已过期值”的强保证。

真实 Redis 还会在访问键时处理过期，并结合主动过期清理，详见 [EXPIRE 官方说明](https://redis.io/docs/latest/commands/expire/)。不要因为两者都支持 TTL，就断言过期可见性与清理算法相同。

在练习中可以提出增强方案：GET 持锁读取时比较 Instant，若已过期则返回 None，并同步移除主表和索引。实现之前先确定接口语义、清理路径与测试，不能只往 `get` 里插一句判断就宣称整个过期系统完成。

## 用时间线检查理解

```text
t=0ms      SET a old PX 1000      索引 (1000, a)
t=100ms    SET a new PX 10000     移除旧索引，插入 (10100, a)
t=1000ms   即使旧等待醒来         查看当前索引，不删除 a
t=10100ms  清理任务得到调度       删除 a 及其索引
```

[roundtrip 实验](labs/src/bin/roundtrip.rs)包括普通 TTL、带 TTL 后覆盖为永久值的两条路径。实验预留调度余量并设超时；这证明本次运行的行为，不是严格到期时刻的调度保证。

为什么通知要在 `drop(state)` 后发出？

<details>
<summary>参考答案</summary>

被唤醒的清理任务接下来也要获取同一把锁。先解锁可以减少它立即醒来又等待锁的机会。状态先完成更新，再通知读取，也让逻辑顺序更清楚；Notify 本身不负责存放需要更新的数据。

</details>
