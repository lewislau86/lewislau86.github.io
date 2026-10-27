---
title: "第 13 章：一条 TTL 测试为什么会一直等待"
description: "测试为什么会挂起，怎样定位并可靠验证过期？"
pageClass: mini-redis-course
---

# 第 13 章：一条 TTL 测试为什么会一直等待

[课程总览](/mini-redis/index.md) · [上一章](/mini-redis/exercises-and-index.md)

::: tip 本章学习目标
**要解决的问题：** 测试为什么会挂起，怎样定位并可靠验证过期？

**顺路学到的 Rust：** 虚拟时间、帧边界、单元测试、超时与任务收尾

**对应源码：** [tests/server.rs](/mini-redis/source/tests/server.md)
:::

<MiniRedisMap active="ttl-test-debugging" />

这次排查针对 `tests/server.rs::key_value_timeout`。旧测试先暂停 Tokio 时钟，通过真实 TCP 写入 `SET hello world EX 1`，立即 GET 验证值，再显式推进一秒并 GET 验证删除。它看似把时间控制好了，但 `pause()` 之后，运行时空闲时仍会自动推进时钟。

## 先记录卡住之前收到的字节

最初的记录只有“单独执行 20 秒未返回”，不足以归因。本轮临时把三个 `read_exact` 改为分段读取诊断循环：保持原来的目标长度，记录每次读取的字节及 Tokio 时钟相对起点的经过时间。进程外另设真实时间上限，避免诊断本身无限等待。诊断代码完成后已经移除。

第一次诊断运行通过，第一次 GET 在虚拟时间 960ms 得到 world。再次运行则复现挂起：

```text
读取 SET 的 5 字节响应，虚拟时间 0ns
收到 [43, 79, 75, 13, 10]，虚拟时间 0ns

读取第一次 GET 的 11 字节响应，虚拟时间 0ns
收到 [36, 45, 49, 13, 10]，虚拟时间 1.001s
随后不再收到字节，外部 3 秒上限终止测试
```

将数字按 ASCII 解读：第一段是 `+OK\r\n`，第二段是 `$-1\r\n`，即合法 Null。此时测试还没有执行源码中后面的 `advance(Duration::from_secs(1)).await`，但键已经到期。这也解释了为什么打印诊断信息时有时通过：任务与网络就绪的时序不同，每次结果都可能变化。

## 两个独立问题串成了挂起

第一层是时间假设错误。锁文件使用 Tokio 1.32.0，其 `time/clock.rs` 中 pause 的 Auto-advance 文档说明：运行时没有可推进的工作时，会把暂停的时钟自动推进到下一个待处理计时器。真实 socket 的就绪事件不受虚拟时钟控制；等待网络期间，过期计时器可以先被推进并触发。这里的“没有工作”指调度器当前没有可推进的任务，此时业务请求可能仍在途中。

第二层是读取假设错误。测试期待的 world 帧是 11 字节：

```text
$5\r\nworld\r\n   11 字节
$-1\r\n           5 字节
```

`read_exact(&mut [0; 11])` 只负责凑满 11 字节，不知道 5 字节已经构成一个完整 Null。它继续等待另外 6 字节；服务端则保持连接，等待客户端发下一条命令。客户端要读完才会发下一条，双方因此一直等待。断言位于读取之后，所以永远等不到“预期 world，实际 Null”的失败消息。

因此本次确认的是测试将“暂停时钟”理解为完全冻结，以及按预期值长度读取响应这两个问题。找到的证据都指向测试本身，没有发现需要修改生产过期逻辑的证据。

本轮网页读取版本文档未成功，语义核对使用本机 Cargo 缓存里的 `tokio-1.32.0/src/time/clock.rs`，对应源码注释的 pause/advance 两段。可自行交叉查阅 [Tokio 1.32.0 pause](https://docs.rs/tokio/1.32.0/tokio/time/fn.pause.html) 与 [advance](https://docs.rs/tokio/1.32.0/tokio/time/fn.advance.html)。

## 用两个层次分别验证时间与通信

| 测试 | 运行条件 | 负责证明什么 |
| --- | --- | --- |
| `db::tests::expiration_boundary` | 暂停时钟，无 TCP | 999ms 仍有值，1000ms 清理函数可以删除 |
| `db::tests::background_expiration` | 暂停时钟，无 TCP | 后台任务确实删除到期键，并保留无 TTL 的键 |
| `key_value_timeout` | 真实时间、真实 TCP | 原始 SET EX 请求经服务端处理，最终 GET 返回完整 Null |

新增单元测试位于 [src/db.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 的 `#[cfg(test)] mod tests`。这个模块只在测试构建中编译；通过 `use super::*` 引入父模块名字，子模块可以检查父模块的私有实现，所以无须为了测试把 Db 公开给库外部。

边界测试先同步写入，再推进 999ms 并直接运行清理函数，确认下一次期限和值仍在；再推进 1ms，调用清理函数并确认缺失。测试同时断言虚拟时间的实际经过量，确认经过的正好是 999ms 和一秒，而非混入了调度等待。直接调用清理是为了检查边界；后台任务是否在运行，由下一项测试证明。

<!-- source: src/db.rs:284-304; comments included -->
```rust
async fn expiration_boundary() {
    let guard = DbDropGuard::new();
    let db = guard.db();
    let started = Instant::now();
    db.set("hello".into(), "world".into(), Some(Duration::from_secs(1)));
    assert_eq!(db.get("hello"), Some(Bytes::from("world")));

    time::advance(Duration::from_millis(999)).await;
    assert_eq!(Instant::now() - started, Duration::from_millis(999));
    assert_eq!(
        db.shared.purge_expired_keys(),
        Some(started + Duration::from_secs(1))
    );
    assert_eq!(db.get("hello"), Some(Bytes::from("world")));

    time::advance(Duration::from_millis(1)).await;
    assert_eq!(Instant::now() - started, Duration::from_secs(1));
    // 直接执行清理函数以检查边界，不假设 advance 已等待后台任务执行完毕。
    assert_eq!(db.shared.purge_expired_keys(), None);
    assert_eq!(db.get("hello"), None);
}
```

后台测试因此另行启动 Db 的正常清理任务，推进到期限后，在 100ms 的虚拟时间上限内观察键消失。轮询不调用清理函数；只通过 Db::get 检查状态。短 sleep 让 runtime 推进任务，删除结果才是完成依据。此处没有真实 I/O，自动推进时间正好用于快速执行受控测试。另一个不带 TTL 的键必须保留，避免把清空整张表误判成正确过期。

## 网络测试不再猜测响应长度

修复后的 [key_value_timeout](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/server.rs) 保留原始 RESP 的 `EX 1` 输入，继续验证服务端接受秒数选项。发送后把 TcpStream 交给 Connection，使用 `read_frame()` 按协议边界读取响应：

- SET 必须返回 Simple OK，否则报告实际 Frame。
- GET 返回 Bulk 时必须等于 world，再继续等待下一次查询。
- GET 返回 Null，表示观察到删除完成。
- 其他帧或 EOF 立即失败，并显示实际结果。

<!-- source: tests/server.rs:92-99; comments included -->
```rust
match response {
    // 即使测试被长时间抢占、第一次 GET 已到期，也能正常识别完整 Null。
    Some(Frame::Null) => break,
    Some(Frame::Bulk(value)) => assert_eq!(value.as_ref(), b"world"),
    other => panic!("GET 应返回 world 或 Null，实际为 {:?}", other),
}
// 等待的是可观察的删除结果，sleep 仅限制轮询频率，不作为完成证明。
time::sleep(Duration::from_millis(10)).await;
```

网络测试允许第一次 GET 晚于一秒发生；操作系统可以长时间抢占测试线程，精确到期前断言已经由无 I/O 的单元测试承担。建连、SET 确认、全部 GET 轮询统一受 5 秒真实时间上限保护。10ms sleep 只降低查询频率，删除完成以 GET 收到 Null 为准。

测试创建自己的临时端口和 oneshot 停止信号。场景正常结束或总超时后都先通知服务停止，再用 1 秒上限等待服务任务返回。其他旧网络测试仍采用原有启动辅助函数；本次没有把它们全部重写。

真实时间上限要放在虚拟时钟之外：此次网络测试不调用 pause，诊断进程的外部限制则独立于 Tokio 时钟。

## 证明测试能发现故障，而非只证明能通过

除了正常执行，还做了临时故障注入，随后全部恢复：

1. 禁用后台清理任务：后台单元测试在虚拟时间上限内失败；网络测试在 5 秒上限失败并完成受控停机，不再无限等待。
2. 将清理条件提前 2ms：边界测试在 999ms 检查处失败，证明它能发现过早删除。

这些注入只用于验证断言和等待上限，没有保留在最终源码。最终修复增加测试、调整测试组织和诊断方式，没有改变数据库生产逻辑。全套测试与重复执行的具体数量见 [本地验证记录](/mini-redis/validation.md)。

理解这次故障后，再回看 async/await：await 等待的是某一个具体操作完成。测试需要明确“当前收到哪个协议结果”和“哪个状态变化证明操作完成”，才能把异步执行变成可验证的行为。

::: warning 常见误区
- **`pause()` 不等于时钟完全冻结。** 运行时没有可推进的工作时，会把时钟自动推进到下一个计时器；等待真实 socket 期间，过期计时器可能先触发。
- **按预期值长度 `read_exact` 不是按协议读取。** 响应长度由服务端实际返回的帧决定，5 字节的 Null 同样是完整响应。
- **增加 sleep、替换 yield 或扩大超时不是修复。** 它们都保留了“时钟冻结”和“响应定长”这两个错误前提。
- **在暂停时钟的测试外套一层 Tokio timeout 得不到真实观察期。** 它使用同一个虚拟时钟。
- **await 返回或 sleep 结束不证明后台工作已完成。** await 既不保证时间停止，也不保证另一个后台任务已经执行；完成要以可观察的状态变化为依据。
:::

## 本章结论 {#summary}

`key_value_timeout` 的挂起来自测试的两个独立错误假设：暂停的 Tokio 时钟会在等待真实 socket 时自动推进，让键在第一次 GET 前就已到期；测试又按 world 的长度读取 11 字节，于是收到 5 字节 Null 后一直等待剩余字节。先记录每次收到的字节和虚拟时间，才把模糊的“卡住了”变成可以归因的证据。

修复把时间与通信分开验证：无 I/O 的单元测试在暂停时钟下检查 999ms 与 1000ms 的边界和后台清理，网络测试在真实时间下按 RESP 帧边界读取响应，以收到 Null 作为删除完成的依据，并由总超时和受控停机保证不会无限等待。故障注入进一步证明，这些测试在过期逻辑出错时确实会失败。

## 检查理解

1. 旧测试为什么会一直挂起，而不是报出“预期 world，实际 Null”的断言失败？

   <details><summary>参考答案</summary>

   断言位于读取之后。第一次 GET 时键已经到期，服务端返回 5 字节的 `$-1\r\n`；测试却用 `read_exact` 凑满 11 字节，继续等待另外 6 字节。服务端保持连接、等待下一条命令，客户端要读完才会发下一条，双方一直等待，断言永远执行不到。

   </details>

2. 这次挂起由哪两个独立问题串成？

   <details><summary>参考答案</summary>

   一是时间假设错误：`pause()` 之后，运行时没有可推进的工作时会把时钟自动推进到下一个计时器，等待真实 socket 期间过期计时器先被触发，键在显式 advance 之前就已到期。二是读取假设错误：按预期值 world 的帧长度读取，而服务端实际返回的是更短的 Null 帧。

   </details>

3. 修复后，怎样分别验证“时间边界”和“网络通信”？

   <details><summary>参考答案</summary>

   时间边界由 `src/db.rs` 中的单元测试负责：暂停时钟、没有 TCP，`expiration_boundary` 检查 999ms 时值仍在、1000ms 时清理函数删除，`background_expiration` 检查后台任务确实删除到期键并保留无 TTL 的键。网络通信由 `key_value_timeout` 负责：真实时间、真实 TCP，用 `read_frame()` 按协议边界读取，GET 收到 Null 才算删除完成，整个过程受 5 秒真实时间上限保护。

   </details>

4. 测试已经通过了，为什么还要临时禁用后台清理、提前清理条件来做故障注入？

   <details><summary>参考答案</summary>

   测试通过只说明正常情况下没有报错，故障注入证明它能发现故障：禁用后台清理后，后台单元测试在虚拟时间上限内失败，网络测试在 5 秒上限失败并受控停机；清理提前 2ms 后，边界测试在 999ms 检查处失败。这样才能确认断言和等待上限真的起作用。

   </details>

全部章节到此结束，可以回到[课程总览](/mini-redis/index.md)按架构总图复习或挑选章节重读。
