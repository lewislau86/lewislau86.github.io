---
title: "专题 4：生产准入与演练"
description: "用真实 PostgreSQL 与独立 Rust 进程，验证租户授权、旧会话迁移、容量准入、故障接管和隔离恢复。"
pageClass: learn-agent-rust-course
---

# 专题 4：生产准入与演练

[课程总览](./index.md) · [上一专题：模型协议与质量评估](./model-evaluation.md) · [学习路径](./learning-path.md#p04)

::: tip 本章学习目标
- 把“准许上线”拆成有环境、版本、阈值、负责人和原始证据的判断。
- 拒绝越权访问和旧版本写入，验证迁移失败后的原数据仍可读取。
- 在并发请求、执行者死亡和旧执行者恢复时，核对容量与写入权限。
- 将备份恢复到独立实例，测量本地恢复步骤，并说明数据缺口。

**前置：** [专题 1：PostgreSQL 检查点](./postgres-checkpoints.md)、[专题 2：外部操作的可靠性](./side-effect-reliability.md)、[专题 3：模型协议与质量评估](./model-evaluation.md)。本章工程独立运行；模型质量仍须按专题 3 单独提供证据。

**实践方式：** [下载独立 Cargo 学习包](/learn-agent-rust/production-readiness-lab.zip)，准备 Rust 1.99.1、Python 3.9+ 和 PostgreSQL 18 服务端工具。无需模型密钥，实验自动创建与清理两个专用临时数据库实例。
:::

助手已经能重启续跑，工具重试也不会重复产生业务结果。现在业务方要把它开放给多个租户，并在周五升级程序：升级前的会话会不会读坏？流量超过容量时如何拒绝？旧执行者暂停后恢复，会不会覆盖接管者？数据库备份真的能够恢复吗？

先预测一个结果：有 4 个执行名额，12 个请求同时到来，如果“先查询空位，再写入任务”分成两个事务，最多只会接收 4 个吗？后面的实验将用真实数据库和独立进程回答。

<LearnAgentRustMap active="production-readiness" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#production-readiness)下载；解压后进入 `chapters/production-readiness/`，或在代码库根目录运行 `python3 run.py run P04`。

<!-- experiment-library:end -->

## 1. 上线是一组带条件的判断

专题 1 回答“恢复时能读回什么”，专题 2 回答“业务结果不明时怎样处理”，专题 3 负责“协议与任务质量分别如何评估”。本章把这些结果放进一次发布流程：先证明指定环境可以接单，再证明故障发生后有办法停下、接管和恢复。

| 准入项 | 要回答的问题 | 可审查的证据 |
| --- | --- | --- |
| 身份与授权 | 谁能读哪个租户的会话？谁能批准哪次动作？ | 未认证、跨租户、角色不足、过期审批版本的拒绝记录，以及未被修改的数据库行。 |
| 版本与迁移 | 新程序能否读旧会话？迁移失败能否退出？ | 兼容矩阵、迁移前后状态、失败后的 DDL 与数据核对。 |
| 负载与资源 | 容量满时会怎样？怎样停止接单并排空？ | 尝试数、接收数、拒绝数、在途数、完成数，以及时延的完整口径。 |
| 监控与告警 | 进程活着是否等于能提供服务？ | readiness 的阻断原因、累计计数、异常触发条件与处置负责人。 |
| 故障与恢复 | 接管后旧执行者还能写吗？备份能恢复多少？ | worker 退出证据、拒写结果、独立恢复库核对、数据缺口与恢复步骤计时。 |

一份发布记录还应固定代码提交、配置摘要、依赖锁文件、数据库版本、会话格式、工作流版本、模型标识与评估集版本，并写明执行人和时间。换了模型、工具、提示词或数据库拓扑，相关证据应重新取得。本章的学习包用 `Cargo.lock` 和逐文件 SHA-256 固定源码；完整生产发布身份还需要部署系统提供。

::: info 本章实际验证范围
本次工程为 Rust + `postgres 0.19.12` 的应用层演练：固定身份 fixture、真实 PostgreSQL、独立 CLI 进程、两个真实 worker、真实 `pg_dump/pg_restore`。没有调用模型，也没有执行 HTTP 服务或完整 Agent。

实验中的 `jobs` 是容量预留位，`results` 是本地结果账本。没有真实邮件、支付或远程工具调用。演练通过可以支持这些局部契约，真实 provider 质量、长期吞吐、跨地域灾备和完整服务上线仍需各自验收。
:::

## 2. 先跑一次完整演练

解压学习包，在工程根目录运行：

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --locked
python3 lab.py
```

PostgreSQL 工具不在 `PATH` 时，先将 `P04_PG_BIN` 设为其 `bin` 目录；macOS Homebrew 常见路径为 `/opt/homebrew/opt/postgresql@18/bin`，Linux 常见路径为 `/usr/lib/postgresql/18/bin`。需要服务端工具，只有 `psql` 不够。请用普通用户运行，`initdb` 不支持 root。

脚本在 `/tmp/p04-pg-*` 建立两个新集群，每个使用独立 Unix socket、0700 目录、本地 trust、禁用 TCP；不会连接现有数据库。Rust 客户端的连接串由演练器传入。退出时回收本次子进程和集群，输出保留在 `results/`。

| 文件 | 职责 |
| --- | --- |
| `src/main.rs` | 授权、迁移事务、准入、租约检查、结果提交、健康检查。 |
| `src/schema.sql` | 格式 1 的旧会话、审批记录、容量与结果表。 |
| `lab.py` | 启动数据库、并发客户端、终止或阻塞 worker、直接 SQL 断言、备份与恢复。 |
| `results/results.json` | 本次全部功能断言与独立 Rust CLI 进程数。 |
| `results/measurements.json` | 本次时延口径与实际观测；每次运行会变化。 |

网站内运行 `python3 scripts/verify-agent-production.py --check`：检查 4 个 Rust 测试、Clippy、24 个场景、每轮 62 个 Rust CLI 进程，再独立解压最终学习包、重新编译并复验全部场景。它比较功能结果、源码摘要和发布产物；当次机器与计时打印到终端，不要求不同机器复现同一毫秒值。

## 3. 授权必须约束数据库中的对象

“模型说用户已批准”不能成为批准身份。程序先从可信认证入口得到主体，再检查租户与角色，最后核对数据库里已经存在的动作 ID 和修订号。

本例使用三个公开的测试凭据：租户 a 的 reader、租户 a 的 approver、租户 b 的 approver。它们是固定 fixture，用来验证授权分支；生产认证需要由服务端适配器验签、检查会话有效性并映射主体，不能直接采用本例字符串。

<<< @/public/learn-agent-rust/code/production-readiness/src/main.rs#authority

这里有三个执行边界：

1. 读取会话时同时用 `tenant` 和 `id` 查询，并先核对主体租户。两个租户都可以拥有名为 `session` 的会话。
2. 批准动作需要 approver 角色。reader 即使提交额外的 `role=approver` 也不会改变服务端身份。
3. 审批更新同时匹配动作与 `revision`，并要求原记录尚未批准。参数变化需要新修订；旧修订与重复批准返回 `ApprovalConflict`。

这里的动作行预先建立且不提供修改入口，修订绑定这份不可变请求。真实审批应继续使用[第 3 章](./permissions.md)的完整动作快照，绑定工具、参数、工作区、调用 ID 与过期策略；仅把批准状态关联到会话 ID 不够。

<<< @/public/learn-agent-rust/outputs/p04-approval-once.txt

演练器不只看错误消息，还直接查询数据库：角色被拒绝后，`approved` 仍为 false；合法批准及重复提交后，只有一条记录处于批准态。租户隔离同样检查租户 b 的原数据保留。

应用操作员修改发布配置，与租户批准工具动作是两个权限域。本例中的 `settings.approved` 代表演练操作员放行发布，和 `approvals.approved` 分别存储。真实部署应分开运行角色、迁移角色与运维角色；本实验的数据库管理员连接没有验证这些数据库权限。

## 4. 升级前先写出兼容矩阵

本例的旧会话保存 `next=review` 与累计消耗 `spent=3`。格式 2 增加 `status=paused` 和工作流列。迁移必须保留推进位置与预算，不能在解码失败时创建一个空会话。

| 读取程序 | 格式 1 | 格式 2 | 未知格式 99 |
| --- | --- | --- | --- |
| 旧 reader 1 | 接受 | 拒绝 | 拒绝 |
| 新 reader 2 | 接受 | 接受 | 拒绝 |

这个矩阵只证明本例读路径的兼容性。旧 writer 与新 writer 同时运行、在线迁移、旧模型工具协议、框架快照等都没有在本章实现。

![迁移先检查格式，在同一事务中改变表结构和会话；失败保留格式 1，成功后旧 reader 被拒绝。](/learn-agent-rust/figures/p04-migration-boundary.svg)

从上往下读：新程序先具备读旧格式的能力；迁移事务完成后才得到格式 2。失败分支同时撤销结构和数据变更，成功分支必须阻止旧程序继续解释新状态。

<<< @/public/learn-agent-rust/code/production-readiness/src/main.rs#migration

迁移锁住唯一的配置行，检查当前 schema 和现有会话格式，再执行 DDL、数据填充和 schema 更新。故障点在这些 SQL 执行后、提交前返回错误；事务被丢弃后回滚。演练器重新连接，分别检查 schema 仍为 1、两条会话仍是格式 1、`workflow` 列不存在。

<<< @/public/learn-agent-rust/outputs/p04-migration-rollback.txt

另一个场景把会话标成未知格式，迁移必须先返回 `UnmigratableSession`。成功迁移后，新 reader 读到 `spent=3` 和 `status=paused`，旧 reader 返回 `IncompatibleSnapshot`；再次迁移返回原成功结果，不再重复修改。

这是一项停机迁移教学实验：准入尚未放行，没有其他会话写入者。大表上的 DDL 锁等待、分批回填、在线双读双写与流量切换都需要额外方案。若生产要求不停机，应先扩展兼容读写，再回填并核对，最后切换格式、退役旧 writer，分别演练每个边界。

**回退程序前先判断数据是否仍兼容。** 本例迁移成功后，直接启动 reader 1 会拒绝。可以继续使用 reader 2 并关闭新功能；需要降级格式时应设计单独的反向迁移并验证预算、审批、幂等身份不丢失。本章没有实现反向迁移，不能把“替换二进制”当作已验收的回滚方案。

## 5. 把资源上限放在接单事务里

如果 12 个进程都先读到“还剩 4 个空位”，再分别写入，就可能超发。本例将容量读取、任务插入和计数增加放进同一事务，使用 `SELECT ... FOR UPDATE` 锁住配置行。PostgreSQL 的行锁让后来的更新者等待持锁事务结束；每个请求据此重新判断当前容量。机制说明见[官方行锁文档](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS)。

<<< @/public/learn-agent-rust/code/production-readiness/src/main.rs#admission

容量满时仍提交拒绝计数，再向调用方返回 `Overloaded`。这让一次拒绝能进入账本；如果抛错导致整笔事务回滚，拒绝指标也会消失。重复请求在容量检查之前单独拒绝，不额外占位；结束任务时同样串行修改作业状态与计数，重复结束不会把 `active` 扣成负数。

![12 次提交在容量 4 时接收 4 次、拒绝 8 次，排空后 active 为 0、finished 为 4。](/learn-agent-rust/figures/p04-admission-evidence.svg)

本轮启动 12 个独立 Rust CLI 进程并发提交，**所有提交返回后才释放名额**，因此验收目标是容量边界。接收哪几个请求取决于调度；验证器只归一化胜出的请求 ID，功能计数和最终记录仍逐项核对。

<<< @/public/learn-agent-rust/outputs/p04-load-burst.txt

这不是每秒吞吐测试。没有真实模型计算、工具耗时、HTTP、连接池、队列与长期守护进程；百分位也不能当作用户任务延迟。`measurements.json` 的口径为：从 CLI 进程启动到准入回复，包含进程启动、连接数据库和事务；12 条样本同时包含接收与拒绝，使用最近秩法计算 p50/p95。12 条样本中的 p95 实际落在最大值位置。

[查看一次本机观测与环境](/learn-agent-rust/outputs/p04-observation.json)。该文件保留生成时的 Rust、主机、PostgreSQL 版本与时延，重新运行会得到新值。机器时延不参与跨平台功能快照比较。

### 排空、容量与重试怎样配合？

演练把 `draining=true`，新请求立即返回 `NotReady`，已接收的四个请求仍可完成；最后核对 `active=0`、`finished=4`，重复结束返回错误。

在真实服务里，可以让网关停止发送新工作，同时保留完成回调与管理入口。资源满时应返回明确的可重试结果，并让客户端带上相同请求身份、退避和总截止时间。无限重试会扩大拥塞。

本例中的预留位没有崩溃后自动回收。若接收请求的执行者死亡，应由持久化任务状态与租约恢复流程确认实际结果，再释放或续接名额；不能因为超时就把有副作用的任务直接标成完成。长期压测还应加入不同任务长度、连接耗尽、队列上限、取消、单租户公平性和连续多轮运行。

## 6. 活着、能接单、任务正确，分别观察

`live=true` 表示当前 CLI 已执行健康检查路径。`ready=true` 还要求 schema=2、发布标识匹配、操作员放行、没有排空且没有恢复阻断。本例容量饱和时仍保持 ready，由准入路径显式拒绝，避免把短时容量波动等同于实例故障。

<<< @/public/learn-agent-rust/code/production-readiness/src/main.rs#health

数据库无法连接时，外层返回 `live=true, ready=false, reason=DatabaseUnavailable`；数据库已连接但尚无完整表结构时，返回 `SchemaUnavailable`。两者都拒绝接单。生产实现还应将具体依赖失败分类并记录到内部日志，使用有超时的检查，避免探针本身长时间阻塞。

| 观察信号 | 解释与处置方向 |
| --- | --- |
| `admitted`、`rejected`、`active`、`finished` | 拒绝比例上升先检查容量与请求模式；active 长期不降应核对失联执行者。 |
| schema、release、readiness 原因 | 版本不匹配停止放量，检查发布配置与迁移结果。 |
| 迁移失败、`Fenced`、审批冲突 | 分别排查数据兼容性、过期执行者与动作修订，不应统一重试。 |
| 备份成功时间、恢复演练结果、数据缺口 | 备份超过业务容忍窗口或无法恢复时，阻断需要该保障的发布。 |
| 任务完成率、协议失败率、工具错误、成本与延迟 | 按专题 3 的固定任务集与真实 provider 口径观察，不能从 readiness 推导。 |

这张表给出处置方向，没有替业务预设告警阈值。真正准入记录应先写明窗口、分母、阈值和负责人，再运行负载与故障测试。例如拒绝率的分母是准入尝试数，不能只统计已接收请求；任务正确率应由独立验收判断，不能用“正常返回率”代替。

实验导出的是数据库计数与 JSON 结果，没有部署指标采集、告警通知、仪表盘或持续存活探针。长服务还应带上 request/session/action/revision 等关联标识，在日志中保留错误位置，同时避免记录凭据、租户正文和未经脱敏的工具参数。

## 7. 接管后必须让旧执行者失去写入资格

“没有心跳”不能证明旧进程已经死亡。它可能暂停、网络断开，稍后继续执行。新执行者拿到任务以后，结果写入必须同时检查当前 owner 与递增的 epoch。

<<< @/public/learn-agent-rust/code/production-readiness/src/main.rs#fencing

租约时钟取自数据库，期限为两秒。领取通过条件更新递增 epoch；提交在持有租约行锁的事务中，核对 owner、epoch 和当时的期限，再写入本地结果账本。接管也修改同一行，因此不能穿过该事务的检查与写入。校验点是持锁后的检查，不承诺事务提交时的墙钟仍在期限内。

演练有两条独立路径：

1. **真的死亡：** worker 领取后被 Python 终止并回收，直接查库确认没有结果；期限前接管返回 `LeaseBusy`，期限到后 replacement 以 epoch 2 提交。
2. **仍然活着：** worker 领取后阻塞在 stdin；期限到后 replacement 获得 epoch 2，再让旧 worker 恢复提交。旧 worker 必须返回 `Fenced`；只有 replacement 写出一条结果。

<<< @/public/learn-agent-rust/outputs/p04-stale-worker-fenced.txt

等待期限时，演练器轮询数据库真实时钟，另设墙钟超时，避免把无限等待当成通过。每个 worker 都是独立子进程，正常结束与被终止的句柄均被回收。

本例的结果账本和租约在同一 PostgreSQL 中。远程业务若只接受“写入”而不检查 epoch，旧执行者仍可能在外部产生结果；此时要由接收方验证 fencing token，或结合[专题 2](./side-effect-reliability.md)的幂等身份和对账。这里的数据库拒写不能证明真实支付或消息发送只发生一次。

## 8. 备份要恢复到另一处，再决定是否接单

有一个 `backup.dump` 只能证明文件被写出。恢复演练至少要回答：目标环境独立吗、结构和数据能读吗、哪些提交没恢复、原运行者是否可能继续写、外部动作是否需要对账。

![源库先阻断接单、完成备份，随后的一条提交不在备份中；源库停止后，目标库保持恢复阻断，核对后再放行。](/learn-agent-rust/figures/p04-restore-boundary.svg)

本例按以下顺序执行，完整操作由学习包中的 `lab.py` 运行：

1. 将源库设为 `recovery=true`，确认 `active=0`。备份本身带着“不接单”的状态。
2. 调用 `pg_dump --format=custom` 导出逻辑快照，另存全部六张表的逻辑基线，包括会话、审批、完成作业、结果账本、配置和租约。
3. 在源库重新接收并完成一次 `after-backup` 作业，然后立即停止源数据库进程，确认健康检查不再 ready。
4. 先用损坏归档恢复到目标库，核对恢复失败，目标库仍不 ready。
5. 用正确归档执行 `pg_restore --exit-on-error --single-transaction`，从独立目标集群查询全部六张表的逻辑状态，与基线逐值比较。
6. 确认 `after-backup` 不存在、恢复阻断仍有效、新请求仍被拒绝；完成本地核对后，由演练操作员解除 recovery。

`pg_dump` 可以导出一致的单数据库逻辑快照，custom 格式可交给 `pg_restore`；它不备份整个集群的全局对象。`--single-transaction` 用于本次整体恢复的事务边界。机制与限制见 [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html) 和 [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html) 官方文档。生产持续备份还应根据需求选择[文件系统备份、基础备份与 WAL/PITR](https://www.postgresql.org/docs/18/backup.html)，不能把本例的小库逻辑导出当成完整灾备配置。

<<< @/public/learn-agent-rust/outputs/p04-restore-separate-cluster.txt

### 这次恢复到底测到了什么？

| 指标 | 本实验的定义与结果边界 |
| --- | --- |
| 已验证的恢复内容 | 格式 2 的两条会话、原预算、审批记录、四条完成作业和一条结果账本，与备份逻辑基线一致。 |
| 数据缺口 | 备份后新增的一条已提交作业缺失；明确报告为 1 条提交，没有证明 RPO=0。 |
| 本地恢复步骤耗时 | 从启动 pg_restore 到 SQL 核对完成并解除本地恢复阻断，观测值见 observation.json。 |
| 完整事故 RTO | 未测。还包括发现故障、人工判断、目标环境准备、外部对账和流量切换。 |
| 以时间衡量的 RPO | 未测。本例按提交数核对缺口；真实服务需固定可恢复时间点与故障时点。 |

源库已经停机，目标库为新建隔离实例，备份中没有在途作业或活动租约，因此本例没有“双主继续执行”的问题。真实恢复不能据此直接复制活动租约或重放未决工具：应先隔离旧环境，核对外部操作，再按恢复代次重新建立执行资格。数据库回到过去，不会让已经发出的邮件或已完成的付款随之撤销。

损坏归档场景只验证拒绝不可读文件，没有覆盖磁盘损坏、恢复中途断电、大数据量、加密备份、异地存储和密钥恢复。应把这些要求列入各自环境的演练计划。

## 9. 看完整证据，再写准入结论

下面的表由验证脚本从实际断言生成。每轮 24 个场景、62 个独立 Rust CLI 进程；最终下载包解压后再跑同样一轮。单元测试只负责基本授权规则，迁移、负载、进程生命周期与恢复由真实数据库实验核对。

<!-- p04-results:start -->

| 场景 | 实际断言结果 |
| --- | --- |
| `old-session` | version=1; spent=3 |
| `new-reader-old-session` | readable=true |
| `untrusted-identity` | error=Unauthenticated |
| `tenant-isolation` | error=TenantDenied; private_spent=9 |
| `approval-role` | error=RoleDenied; approved=false |
| `approval-tenant` | error=TenantDenied |
| `approval-revision` | error=ApprovalConflict |
| `approval-once` | accepted=1; replay_error=ApprovalConflict |
| `migration-unsupported` | error=UnmigratableSession; schema=1 |
| `migration-rollback` | schema=1; old_sessions=2; workflow_columns=0 |
| `migration-forward` | schema=2; migrated_sessions=2; spent=3; status=paused |
| `migration-replay` | replayed=true |
| `old-reader-rejected` | error=IncompatibleSnapshot; saved_version=2 |
| `future-version` | error=IncompatibleSnapshot |
| `readiness-gates` | schema=true; operator_approval=true; release=true; drain=true; recovery=true |
| `load-burst` | attempted=12; accepted=4; rejected=8; active=4; capacity=4; ready=true |
| `duplicate-admission` | error=DuplicateRequest; active=4 |
| `drain-and-finish` | active=0; finished=4; rejected_new=true; duplicate_finish_rejected=true |
| `worker-death-takeover` | killed=true; early_error=LeaseBusy; takeover_epoch=2; committed=1 |
| `stale-worker-fenced` | stale_error=Fenced; takeover_epoch=2; committed=1 |
| `backup-snapshot` | in_flight=0; sessions=2; completed_jobs=4; results=1; restore_blocked_by_default=true |
| `database-outage` | live=true; ready=false; reason=DatabaseUnavailable |
| `corrupt-backup` | restore_failed=true; ready=false |
| `restore-separate-cluster` | source_stopped=true; logical_state_equal=true; missing_post_backup_commits=1; ready_after_local_checks=true |

<!-- p04-results:end -->

<a href="/learn-agent-rust/code/production-readiness/lab.py" download>下载演练器</a>，重新运行得到当前环境的 `results.json`；发布时的完整来源摘要与结果在学习包 `evidence.json` 中。

### 把演练结果变成发布记录

| 发布阶段 | 本章已有证据 | 真正发布前仍需填入的内容 |
| --- | --- | --- |
| 冻结候选版本 | Cargo 锁文件、逐文件摘要、固定 schema 与 release。 | 部署镜像/提交与配置摘要、模型/provider/工具协议标识、数据规模与拓扑。 |
| 准入前核对 | fixture 授权拒绝、迁移失败回滚、旧 reader 拒绝。 | 真实认证与权限、在线或停机窗口、旧 writer 退出证据、可用回退策略。 |
| 小流量观察 | 容量边界与排空计数。 | 按预先定义窗口与阈值核对真实完成率、成功请求延迟、成本、工具结果与拒绝率。 |
| 故障与恢复 | worker 死亡接管、旧 worker 拒写、独立逻辑恢复。 | 网络与数据库故障、外部对账、完整 RTO/RPO、备份保管与恢复权限。 |
| 放量或停止 | 未满足条件时 `NotReady`，排空后在途归零。 | 操作负责人、停止条件、告警渠道、放量记录与人工接管办法。 |

如果真实模型评估还没有完成，应记录为“provider 质量准入未验证”；如果只跑过本章的小规模负载，应记录为“容量边界通过，生产吞吐未验证”。不确定项要保留在发布记录里，不能通过把总状态改成绿色来消除。

## 动手实验

1. **改容量再预测。** 在 `src/schema.sql` 中把 capacity 从 4 改为 2，先算出预期接收与拒绝数，再同步调整自己副本的断言并运行。不要把改过的工程与网站原结果混用。
2. **试错迁移。** 将格式 1 的会话标记为未知格式，观察迁移拒绝；修复版本后，核对原预算仍为 3。不要通过清空数据库绕过错误。
3. **延长旧执行者暂停。** 保持 epoch 检查，观察只有 replacement 能提交；在练习副本去掉该检查，再解释唯一约束挡住了哪些结果、远程副作用又会怎样。
4. **写一份你自己的准入记录。** 固定真实任务集、模型版本、环境、阈值、负责人和截止时间，分开填写功能、质量、资源与恢复结果。没有运行的项明确写“未验证”。

仓库内修改 Rust 或演练脚本后，先运行 `python3 scripts/verify-agent-production.py` 更新证据，再运行 `python3 scripts/generate-learn-agent-rust-figures.py --lesson P04` 刷新配图，最后执行 `--check` 和文档构建。图里的数值来自演练结果，不在 SVG 里手工填写。

::: warning 常见误区
- **“所有测试通过，就可以对外开放。”** 测试只能支持其环境与契约；真实身份、模型质量、业务规模和完整恢复需要各自证据。
- **“readiness 为真，所以任务答案正确。”** readiness 判断能否接单，质量由固定任务集与独立验收判断。
- **“迁移失败能回滚，所以成功后可随便降级。”** 提交前回滚和成功后的反向迁移不同，本例旧 reader 会拒绝格式 2。
- **“租约过期，旧进程一定消失了。”** 暂停的进程可能恢复；接收结果的一方必须核对当前执行资格。
- **“备份恢复成功就是没有数据丢失。”** 本例明确缺少备份之后的一条提交；外部业务结果也没有随库回滚。
- **“本次 p95 就是 Agent 的 p95。”** 本次只测 12 次 CLI 准入，包含成功与拒绝；没有模型或完整任务执行。
:::

<!-- transfer-thinking:start -->

## 迁移思考：恢复演练要闭合业务链

数据库恢复成功，能否宣布事故 RTO 已达标？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

继续核对认证、流量切换、积压任务、外部回执与业务验收；只恢复数据库只覆盖事故链的一段。

准入结论必须写明版本、负载、故障和恢复终点，才有可复用的工程意义。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

准入应写成可以复核的条件：指定身份能访问指定对象，指定程序能解释指定状态，资源满时显式拒绝，接管后旧执行者不能继续提交，恢复后能说明留下了什么、缺失了什么。

本章用真实 PostgreSQL 与独立进程完成这些局部演练。把它接到完整 Agent 和真实模型后，还需要在实际部署环境核对质量、负载、外部副作用、告警与恢复目标，再决定是否放量。

## 检查理解

### 1. 为什么拒绝计数需要在返回 Overloaded 之前提交？

<details><summary>参考答案</summary>

计数与准入判断放在同一事务中。如果错误返回使事务回滚，拒绝记录也会消失，监控就只看见成功请求。本例先提交拒绝计数，再返回错误，同时保持 active 不变。

</details>

### 2. 新 reader 能读格式 1 和 2，为什么仍不能直接回退旧程序？

<details><summary>参考答案</summary>

兼容性有方向。新 reader 接受旧格式，不代表旧 reader 能解释新字段与语义。迁移成功后旧 reader 拒绝格式 2；回退需要保留兼容程序，或另行验证反向迁移，不能靠清空状态恢复。

</details>

### 3. 为什么既要终止 worker，也要保留一个暂停后恢复的 worker？

<details><summary>参考答案</summary>

前者验证死亡后能否接管，后者验证接管后旧执行者能否被拒写。只测试进程死亡，就没有覆盖“仍然活着但被误认为失联”的情况。epoch 必须在写入结果的边界检查。

</details>

### 4. 恢复成功后为什么还保留 recovery 阻断？

<details><summary>参考答案</summary>

恢复工具返回成功不代表业务状态已核对。还需要比较会话、预算、审批和结果，确认数据缺口、旧环境隔离与外部操作。本例恢复后仍拒绝接单，完成本地核对才由演练操作员解除阻断；真实环境还需要外部对账。

</details>

### 5. 本例可以报告 RPO=0 或完整事故 RTO 吗？

<details><summary>参考答案</summary>

都不可以。备份后的一条提交确实缺失，本例按提交数报告缺口。计时只覆盖 pg_restore 到本地核对放行，没有包含故障发现、环境准备、人工决策、外部对账与流量切换，所以不是完整事故 RTO，也没有测出时间口径的 RPO。

</details>

## 参考资料

- [PostgreSQL 18：Explicit Locking](https://www.postgresql.org/docs/18/explicit-locking.html)：行锁与事务内并发控制。
- [PostgreSQL 18：pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)：单数据库逻辑导出、格式与边界。
- [PostgreSQL 18：pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)：恢复归档、错误处理与事务选项。
- [PostgreSQL 18：Backup and Restore](https://www.postgresql.org/docs/18/backup.html)：逻辑备份、文件系统备份及持续归档。
- [专题 1：PostgreSQL 检查点](./postgres-checkpoints.md)、[专题 2：外部操作的可靠性](./side-effect-reliability.md)：本章恢复判断的基础。
- [专题 3：模型协议与质量评估](./model-evaluation.md)：按该专题的当前状态补齐真实 provider 与质量证据。

下一专题是[固定工作流与目标控制](./workflow-and-goal-control.md)：将固定业务路径与有上限的继续策略连接起来，区分正常返回和目标完成。也可以重跑[完整 Agent 集成](./integrated-agent.md)，把本章准入条件对应到执行入口。
