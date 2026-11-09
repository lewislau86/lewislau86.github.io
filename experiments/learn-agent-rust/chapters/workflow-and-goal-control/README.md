# P05：固定工作流与目标控制

正文以网站 `docs/learn-agent-rust/workflow-and-goal-control.md` 为准。本包独立运行，不需要模型密钥、数据库或其他章节工程。

## 运行

使用 Rust / Cargo 1.99.1（edition 2024）和 Python 3.9+。先解压进入 `workflow-and-goal-control-lab`。首次编译需下载 Cargo.lock 固定依赖，之后实验只访问本地文件。

```sh
cargo test --locked
cargo run --locked -- continue-success /tmp/p05-continue-demo
cargo run --locked -- false-final /tmp/p05-false-demo
cargo run --locked -- valid-then-model-error /tmp/p05-error-demo
```

每次指定一个**尚不存在**的目录，父目录必须已存在。目录内保留 source.txt、report.txt（若曾成功写入）、result.json，未完成的运行还有 handoff.json。重新运行请选择新目录，不要把实际项目目录交给本实验。CLI 对存在目录立即拒绝，不覆盖已有内容。

控制器的 `completed` 是实验业务终态；进程退出 0 仅表示实验执行并保存结果成功。目标未完成但成功写出交接记录时同样退出 0。参数错误、已有目录或结果保存失败退出 2。没有自动重启或续接命令。

运行全部 22 个场景和 2 个 CLI 拒绝实验：

```sh
cargo build --locked
python3 lab.py --binary target/debug/learn-agent-p05 --output /tmp/p05-verified
```

`lab.py` 创建并自动清理专用临时工作区，在输出目录保存断言核对后的逐场景输出和 results.json。单个 `cargo run` 的实验目录则由读者自行保留查看。

## 模块与范围

- main.rs：创建独占的新目录、准备夹具、保存最终结果。
- fixture.rs：固定输入和脚本模型。ReadSource、Write、Final、Handoff、错误是类型化提案，不接入 LLM provider。
- controller.rs：固定准备 / 执行 / 验收 / 继续或交接流程；所有 episode 共用累计账本。
- goal.rs：读取真实文件，按准备时冻结的数值合同核对每项与总计。
- tests.rs：解析、伪造总计、重复字段、进度与额度边界的单元测试。

场景名见 fixture.rs 的 NAMES 和 lab.py 的 CASES。`continue-success` 故意先漏掉 total，再依赖 `missing:total` 反馈补齐；`false-final` 只声称完成而不产生文件；`no-progress` 连续重写同样的部分结果；`valid-then-model-error` 已有合格产物，但模型阶段异常，转人工确认。

默认上限：4 个 episode、12 次脚本模型调用、8 次工具尝试、累计预留写入 256 字节；连续 2 个 episode 没有提高正确字段数则交接。额度等于上限允许执行，超过上限前拒绝。工具策略拒绝也计入工具尝试；写入失败保留已预留的字节。读取和验收的系统开销单独存在，不计入工具额度。

输入和产物读取各最多 512 字节；苹果和梨分别 0–1,000,000，总计最多 2,000,000。报告只允许 apples、pears、total 三个唯一字段。验收器比对冻结输入，并检查源文件仍未变化。固定工具只允许读取 source.txt、替换 report.txt。

这是单进程应用控制实验。取消是在下一次脚本调用前注入检查信号；不会中断已经开始的 I/O。进度是针对本合同的正确字段数，不是模型推理质量。临时写入后 rename 只避免本例写入失败留下半份 report，不提供检查点、断电恢复、外部副作用幂等或并发文件沙箱。工作区假定可信且无恶意并发修改。

handoff.json 保存冻结的输入与期望值，是待处理记录，不发送消息，也不授予新预算或执行权限。真实接管必须重新审核目标、已有结果、源数据和后续预算。本实验不实现跨进程自动续跑。
