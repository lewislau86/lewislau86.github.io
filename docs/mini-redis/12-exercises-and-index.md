---
editLink: false
---

# 12 动手练习与知识索引

[上一章](/mini-redis/11-real-redis.md) · [目录](/mini-redis/index.md)

读懂笔记是开始，能够预测结果、解释错误、独立改出一个功能才会形成自己的知识。下面按“现象 → 解释 → 修改 → 验证”推进，不要求一次做完。

## 第一轮：不修改项目，先证明看懂了

先完成第 01 章的 hello_tokio：保持服务运行，在程序里把 GET 的键改成一个从未写入的名字，预测结果为什么会变为 None，以及实验的“必须等于 rust”断言为什么会失败。恢复代码后，继续运行 [labs](/mini-redis/labs/index.md) 中的其他程序。每次运行前先写下预期，再看实际输出。

1. `ownership`：画出 key 移动到 table、两个 Arc 指向同一 State 的关系。删掉 `drop(second_handle)`，预测强引用计数断言的变化。
2. `frames`：把 `course` 换成 `中`，把 Bulk 长度改为 3；检查完整帧字节数。若错写 1，会在哪一层暴露问题？不要把当前宽松解析器的行为当规范。
3. `async_basics`：交换两次 await 的顺序，预测打印顺序；再只创建并丢弃第二个 Future，解释为什么看不到它的阶段输出。不要把这条结论套到已经 spawn 的任务上。
4. `roundtrip`：把 TTL 后的永久覆盖移除，预测旧值是否还应该存在；观察失败的断言对应哪个业务假设。
5. `multiplex`：把 8 个任务改为 40 个，它们会经历队列等待，但仍共用一条连接。不要把输出通过当成吞吐量随任务数线性提升。

再做两个[故意失败的编译实验](/mini-redis/labs/index.md)：E0382 告诉你值在哪里移动，E0502 告诉你共享与独占借用在哪里重叠。先用借用范围和所有权解释，再修改代码。

## 第二轮：增加一个 DEL 命令

这是建议你自行完成的练习，**当前仓库没有因为本笔记自动新增 DEL**。先选择小而明确的语义：`DEL key` 删除一个键，存在返回整数 1，不存在返回 0；暂不支持多键。

实现前画调用路径：

```text
Client::del → Del::into_frame → TCP → Command::from_frame
→ Del::parse_frames → Del::apply → Db::remove → Integer 响应
```

修改点应包括：

| 位置 | 要完成的职责 |
| --- | --- |
| `src/cmd/del.rs` | 保存 key，解析一个参数，执行删除，编码命令 |
| `src/cmd/mod.rs` | 模块导出、Command 分支、名称分发和 apply 分发 |
| `src/db.rs` | 同一临界区删除 entries 与相应过期索引 |
| `src/clients/client.rs` | 发命令并接受整数结果 |
| `src/bin/cli.rs` | 如需命令行体验，再增加子命令 |
| `tests` | 已有键、缺失键、带 TTL 的键、错误参数 |

不要只删 entries：遗留的 `(旧时间, key)` 会破坏索引不变量，之后给同名 key 写入新值时可能造成错删。这个练习会把枚举穷尽匹配、所有权转移、锁内跨结构更新和端到端验证连起来。

<details>
<summary>设计参考：删除方法应该返回什么？</summary>

可以返回 bool 表示是否删除过一条记录，命令层把 bool 映射为 0/1；也可以由 Db 返回删除数量。先明确“键已名义到期但尚未清理”如何计数，再决定是否将 GET/DEL 的过期语义一起完善。结构修改与语义选择都要有测试对应，不能只验证普通存在键。

</details>

## 第三轮：把一个已知边界变成明确保证

从下面选择一个，不必同时做：

| 改进 | 要先写清的保证 | 至少验证的场景 |
| --- | --- | --- |
| GET 访问时处理过期 | 读操作不暴露已到期记录 | 未过期、恰好到期、被覆盖、无 TTL |
| Bulk 终止符校验 | 数据后的两个字节必须是 CRLF | 正常、半帧、错误尾部、正文含 CRLF |
| 输入大小与深度上限 | 超过上限可控返回错误 | 边界值、超限、嵌套、连接后续行为 |
| 订阅二进制值修复 | 收到的字节与发布的字节相同 | UTF-8、0 字节、非法 UTF-8、CRLF |
| 限时停机 | 超过 deadline 的任务按明确策略结束 | 空闲连接、活跃请求、慢读者、订阅连接 |

把“编译通过”“某条测试通过”“对所有边界提供保证”分开报告。尤其是网络、时间与取消，不要只用正常路径推导全部行为。

## Rust 知识在哪里再次出现

| 知识 | 回看章节 | 源码定位 |
| --- | --- | --- |
| Cargo、crate、模块、可见性 | 01 | Cargo.toml、lib.rs |
| let、mut、基础类型、遮蔽 | 02 | Connection::write_decimal |
| 所有权、移动、借用、切片 | 02、03 | Set::into_frame、Client::get |
| struct、enum、match、if let | 02、03 | Frame、Command、Get::apply |
| Option、Result、`?`、类型别名 | 03 | lib.rs、Connection::read_frame |
| 泛型、trait、`impl Trait`、转换 | 03、09 | Set::new、Client::connect、Into |
| 生命周期 | 04 | frame::get_line |
| Future、async/await、move | 05 | Listener::run |
| runtime、block_on、Cargo features | 01、05、09 | async_basics、Cargo.toml、BlockingClient::connect |
| Send、Sync、`'static` | 05、08 | spawn、Messages、Error |
| Arc、Mutex、Deref、Drop | 06、10 | Db、Shared、DbDropGuard |
| 闭包、迭代器、map、into_iter | 03、06、07 | Parse::new、Db::get、Db::set |
| HashMap、BTreeSet、元组排序 | 06、07 | State |
| select、取消、Notify | 05、07、10 | Handler、purge_expired_tasks |
| mpsc、broadcast、oneshot | 08、09、10 | subscribe、BufferedClient、server |
| Box、dyn、关联类型、Pin、Stream | 08、09 | Messages、SubscriberIterator |
| 宏、derive、属性、cfg | 01、02、10 | server binary 的 tokio/main、otel 条件编译 |
| 单元/集成/文档测试、虚拟时间 | 10 | tests、客户端 doc comments |

`#[cfg(feature = "otel")]` 是编译期条件：开启对应 Cargo feature 才包含那段代码，不是运行时 if。本文沿默认 feature 路径阅读，没有验证 OpenTelemetry 部署。`#[test]` 标记同步测试，`#[tokio::test]` 为异步测试安排 runtime；文档里的测试代码由 rustdoc 收集执行或编译，不能因此认为独立 Markdown 中每个节选也会自动被测。

## 源码阅读的十个口头检查

尝试不看笔记，逐题回答，并指出函数位置：

1. 一个 SET 从 CLI 到 Db 要经过哪些表示转换？
2. 为什么 `Db::get` 返回 `Option<Bytes>`，而不返回表内值的引用？
3. `self`、`&self`、`&mut self` 各自允许调用者接下来做什么？
4. 半帧、EOF、非法协议分别走哪条路径？
5. tokio task 与 OS thread 有什么区别？
6. 为什么 Arc 不能替代 Mutex，Mutex 又为什么不能替代 Arc？
7. 覆盖带 TTL 的键时为什么要删除旧索引？
8. broadcast、mpsc、oneshot、Notify 分别适合哪种通信？
9. 停机代码在哪里发出通知，在哪里等待完成，哪里没有显式 join？
10. 哪些 Redis 能力在本仓库里根本找不到？

<details>
<summary>简要答案索引</summary>

1. CLI 参数 → Set → Frame → RESP → Frame → Set → Db；见第 03 章。
2. 要在解锁和可能删除表项后仍持有值，Bytes 克隆成本适合；见第 06 章。
3. 分别转移所有权、共享借用、独占可变借用；见第 02 章。
4. 继续追加、空缓冲时返回 None、传播 Err；半帧 EOF 也是 Err；见第 04 章。
5. task 是 runtime 调度的计算，线程是系统执行资源；见第 05 章。
6. 一个管理共享生命期，一个保护可变访问；见第 06 章。
7. 旧记录可能按旧 deadline 删除新值；见第 07 章。
8. 多订阅者广播、多个生产者发给一个消费者、一次回复、提示重查状态；见第 07—09 章。
9. drop broadcast、等待 mpsc 所有发送端释放；清理任务没有显式 join；见第 10 章。
10. 多类型数据结构、持久化、复制、Sentinel、Cluster、事务和淘汰等；见第 11 章。

</details>

## 接下来怎样把 Rust 学扎实

读完并做完以上练习，应能独立跟踪项目里的所有权与异步调用链。继续按 [Rust Book](https://doc.rust-lang.org/book/) 补齐模式匹配、泛型与生命周期、错误设计、测试、智能指针和并发章节，再用 [Tokio 官方教程](https://tokio.rs/tokio/tutorial)重写一次小型服务。

之后再深入本项目没有充分训练的主题：自定义错误枚举与库 API 设计、trait 的高级用法、手写 Future/Pin、unsafe 的安全边界、性能分析、宏开发和 FFI。完成这些需要更多程序与调试经验，不能把读完一本项目笔记等同于掌握 Rust 的全部能力。

一个合适的下一步是从空目录实现“只支持 PING、GET、SET 的服务器”，然后用这里的帧实验和独立客户端验证它。你能解释每份数据的拥有者、每个 await 的等待对象、每个共享状态的不变量，就已经掌握了继续扩展的基础。
