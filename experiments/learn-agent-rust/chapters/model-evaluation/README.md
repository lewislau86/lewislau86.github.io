# P03 模型协议与质量评估

教程：https://lewislau86.github.io/learn-agent-rust/model-evaluation

Rust 1.99.1；graph-flow / langchain-rust 固定提交；直接 HTTP 适配器用 reqwest 0.12.28。
完整依赖见 Cargo.lock；Python 3.9+ 的标准库负责真实 loopback HTTP fixture 与评测。
首次获取依赖需要网络；fixture 模式无需模型密钥和外部模型服务。

```sh
cargo test --locked
cargo build --locked
python3 lab.py fixture target/debug/learn-agent-p03 demo-fixture
```

输出目录必须不存在，父目录存在。学习包在 Windows 上二进制名需加 .exe；本轮记录环境为
macOS，CI 使用 Ubuntu。所有文件操作只在新建任务目录，唯一可用工具 read_file 只读
README.md，不执行 README 中的命令。所有 case 都在启动时用同一份 cases.json 建好。
stdout 输出证据，demo-fixture/evidence.json 保存全部结构化结果；每次 CLI 的 run.json
和实际 README 在各自任务目录。fixture 服务在线程中启动，结束关闭并等待线程退出。

## 已验范围

27 个协议/宿主边界场景；4 个带标签的固定任务 × 每项 3 次 × 两种夹具策略 = 24 次任务。
使用真实 HTTP 请求、两库消息和图、实际文件读取、独立 Python 判分、消息配对、请求与
响应交叉核对。正确夹具逐次从收到的工具数据提取 Startup；错误夹具总是回答 npm start。
夹具用确定性程序生成响应，重复只检验复现性，不是随机模型的多种子质量比较。

协议子集：Chat Completions 非流式、单 choice、单 function call、JSON 字符串参数，
显式 tools + tool_choice=auto、temperature=0、max_tokens=256、thinking disabled。
模型响应 identity 必须和请求一致（本实验准入规则，别名/版本映射需另做配置）。
不覆盖 SSE、图片、思考字段回传、并行工具、多 provider 兼容或完整 SDK。
系统策略和 user 目标在每轮前缀，模型输入不含标签；工具结果用同一 tool_call_id 回传。

请求最多 24576 字节，响应最多 65536 字节（含没有 Content-Length 的分块响应），读取文件
最多 4096 字节；fixture 请求总超时 800 ms，live 30 秒，覆盖响应体。最多 3 次模型尝试、
1 次文件读取。显式不自动重试 HTTP；认证、限流、服务错误、重定向、超时分别停止。
该限制并非任务完整的 wall-clock / 财务预算；客户端取消不证明远端停止生成或不计费。

任务判分要求精确 JSON 两字段、command 与标签相同、source=README.md、且实际读取一次。
四任务为 rust、node、含恶意指令的 python、缺失 README。4 项是小型合成公开诊断集，
没有训练集/验证集拆分，不用于泛化或模型排名；注入夹具不测真实模型抗攻击质量。
missing-usage 可以完成任务，但 usage=null；未知绝不补零。夹具返回的 token 数是假数据，
只用于汇总逻辑测试。费用始终未知，除非另行加入日期、币种、缓存/普通输入等计价类别的
价格表并核对供应商账单。本程序没有按网上单价自动推算费用。

## 可选真实服务（本次未运行）

只允许固定 HTTPS 地址 https://api.deepseek.com/chat/completions，关闭重定向、系统代理；
先在本机安全设置 DEEPSEEK_API_KEY 和显式 P03_MODEL。不要把密钥写进文章、命令参数或
结果文件。本文不绑定某个随时间变化的模型别名，运行前核对官方支持的模型和协议。

```sh
python3 lab.py live target/debug/learn-agent-p03 demo-live
```

这会发送公开 cases.json 的 README 与固定提示词：计划 12 个任务，最多 36 次 HTTP 请求；
每次最多 256 生成 token。token 上限不等于费用上限。认证、限流或返回模型身份变化时
提前停止，live-results.json 保留 attempted_tasks 和 planned_tasks，失败不从分母移除。
这条命令需要读者自行决定是否运行并承担服务调用费用；CI 和验证脚本从不执行它。
适配器的 live 配置分支可构建、端点约束有测试；真实服务可用性、响应兼容与质量尚未验收。

报告记录每次 HTTP 耗时、整个任务 elapsed_ms、请求/响应模型、消息与原始 usage；
live manifest 记录时间、平台、任务/提示词哈希，源码和 lockfile 哈希在 evidence.json。
任务计时从图开始到停止，含 HTTP 与工具，不含 CLI 启动和建文件；没有 TTFT 或并发吞吐。
p50/p95 使用 nearest-rank，n=12 时 p95 是最大值，不宜解释成可靠尾延迟。

## 仓库复验与产物

scripts/verify-agent-evaluation.py 从独立目录测试、Clippy、构建并运行全部本机场景；
然后独立解压最终 zip，离线重新编译、重新启动服务并复验。
规范化证据去除波动耗时与临时端口；measured_snapshot 保留一次实际延迟观测，--check
重新测量但不要求时延逐字相同。源码和任务集哈希有变必须刷新证据。
