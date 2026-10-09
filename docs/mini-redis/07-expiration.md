---
editLink: false
---

# 07 到期的数据由谁删除

[上一章](/mini-redis/06-shared-storage.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/08-pubsub.md)

`SET session token PX 1000` 不只是插入一行数据，还给服务器增加了一项未来工作。一秒后即使没有新的请求，这个键也应该被清理。问题变成：如何安排下一次唤醒，如何在键被覆盖时取消旧安排？

## 一份值，两种索引

[State](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 同时维护：

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

## 后台任务不必固定频率轮询

`Db::new` spawn 了 `purge_expired_tasks(shared.clone())`。循环先调用 `purge_expired_keys`：锁住状态，从最早元素开始删除所有已到期键，若遇到未来时刻就把该时刻返回。

```text
有下一次到期时间 → 等待 sleep_until(when) 或 Notify
没有待过期键     → 仅等待 Notify
被唤醒           → 重新读取共享状态、清理、计算下一次等待
```

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

[roundtrip 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/roundtrip.rs)包括普通 TTL、带 TTL 后覆盖为永久值的两条路径。实验预留调度余量并设超时；这证明本次运行的行为，不是严格到期时刻的调度保证。

为什么通知要在 `drop(state)` 后发出？

<details>
<summary>参考答案</summary>

被唤醒的清理任务接下来也要获取同一把锁。先解锁可以减少它立即醒来又等待锁的机会。状态先完成更新，再通知读取，也让逻辑顺序更清楚；Notify 本身不负责存放需要更新的数据。

</details>
