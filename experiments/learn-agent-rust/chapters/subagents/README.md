# 子 Agent 与上下文隔离 · 独立实验

正文：https://lewislau86.github.io/learn-agent-rust/subagents

## 环境与运行

支持 edition 2024 的 Rust 工具链（Rust 1.85 及以上），只用标准库。
运行时无需模型密钥、数据库、外部仓库或第三方 crate。

```sh
rustc --edition=2024 -D warnings subagents.rs -o subagents
./subagents normal
./subagents cancel
rustc --edition=2024 -D warnings --test subagents.rs -o subagents-tests
./subagents-tests
```

Windows 原生终端运行 `./subagents.exe` 与 `./subagents-tests.exe`。

## 场景

程序接受一个场景名，默认 normal：

- normal、changed-readme：实际读取练习文件，只把启动命令摘要回传父模型。
- missing-file：文件不存在，子任务状态为 MissingFile。
- child-model-budget、child-tool-budget：限制子任务的模型或工具额度。
- global-model-budget、global-tool-budget：限制父子共享的总额度。
- parent-answer-budget：子任务完成后，总额度不足以让父模型回答。
- cancel、cancel-before-start、gate-closed：在文件读取前请求取消或断开控制通道。
- forbidden-path、recursive：拒绝私有路径或子任务再次委派。
- invalid-task、oversized-result、model-error：拒绝空任务、超长摘要或模拟模型错误。

每次运行创建独立临时目录与练习 README。`PARENT_ONLY_NOTE` 和
`CHILD_RAW_ONLY` 是公开的测试标记，用来核对消息流，不是凭据。
父上下文只收到 ChildReport；完整子历史另打印为宿主诊断。

## 验证边界

父子模型均为固定规则替身；子任务在同一进程中的一个线程执行。
这份代码验证消息历史分离、执行前额度检查、只读工具策略和协作取消。
它不提供进程沙箱、任意工具的强制终止、真实模型质量或持久化恢复。
临时文件只属于当前实验。取消点通过通道握手确定，不靠 sleep 猜测时机。
句柄所有者退出时会请求取消并 join；文件系统 I/O 一旦开始，不能靠取消标记撤销。

进程退出码 0 表示实验运行完毕。练习是否完成，请看 fixture_goal_met，
不要仅凭 parent_stop=Completed 判断。

`outputs/`、`evidence.json` 和 `environment.txt` 由维护脚本实际运行生成。
网站仓库根目录的复现命令：

```sh
python3 scripts/verify-agent-subagents.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R06
python3 scripts/verify-agent-subagents.py --check
```
