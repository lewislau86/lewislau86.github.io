---
title: "第 18 章：工作区隔离"
description: "把代码任务绑定到独立 Git worktree，分开文件与索引，并在回收前保护未合入的成果。"
prev: false
next:
  text: 第 19 章 · MCP 外部工具
  link: /learn-agent-rust/mcp-tools
pageClass: learn-agent-rust-course
---

# 第 18 章：工作区隔离

[课程总览](./index.md) · [上一章：自主任务领取](./autonomous-workers.md) · [下一章：MCP 外部工具](./mcp-tools.md)

::: tip 本章学习目标
- 区分任务所有权、worktree 目录、分支、索引和共享 Git 数据各自的职责。
- 将一次执行尝试绑定到固定工作区，拒绝旧凭据、重复绑定与路径覆盖。
- 依据运行中的写入者、文件变化和提交是否合入，决定保留还是回收工作区。

**前置：** [R03 工具权限与审批](./permissions.md)、[R17 自主任务领取](./autonomous-workers.md)的所有权概念，以及 [R13 后台任务](./background-tasks.md)的句柄回收。R17 目前仍为规划章节，本章用固定的 `owner + epoch` 凭据模拟领取结果，独立提供实验所需代码。

**实践方式：** <a href="/learn-agent-rust/worktree-isolation-lab.zip" download>下载独立 Rust 学习包</a>。Rust 1.85+、Git 2.28+；只用标准库调用本地 Git，无需模型密钥、数据库或网络。
:::

两个代码任务同时修改同一个 `README.md`：甲把启动方式改成 `alpha`，乙改成 `beta`。如果它们共用一个目录，最后保存的人会覆盖前一个人的文本；即使甲只想提交自己的修改，暂存区也可能已经混入乙的内容。

前一章讨论“谁有权领取任务”。本章再给每次执行一个明确的落脚点：固定基线、独立目录、独立分支与索引，执行结束后根据实际成果决定是否回收。我们仍让两项任务修改同名文件，观察隔离解决了什么，以及合并时还需要面对什么。

<LearnAgentRustMap active="worktree-isolation" />

## 1. 两份文件、两个索引，共用一个对象库

Git worktree 让同一个仓库拥有多个检出目录。每个工作区有自己的 `HEAD` 和索引，所以甲在自己的目录里暂存文件，不会直接把乙的修改放进同一暂存区。普通分支引用、提交对象等公共数据仍然共享。

| 概念 | 在本章例子里是什么 | 隔离或共享的范围 |
| --- | --- | --- |
| 业务任务 | `alpha`、`beta` | 标识要完成的工作。 |
| 执行尝试 | `attempt=1` | 一次任务执行与工作区绑定的版本。 |
| 工作区目录 | `workspaces/alpha-a1` | 文件内容与索引独立。 |
| 分支 | `codex/r18-alpha-a1` | 记录成果的提交位置；引用存在共享仓库中。 |
| Git 公共目录 | `repository/.git` | 存放共享对象、普通引用和 worktree 登记。 |
| 执行凭据 | `owner=worker-a, epoch=1` | 由宿主判断哪个执行者当前被允许操作绑定。 |

![任务 alpha 与 beta 各自绑定目录、HEAD 和索引，并共享同一个仓库的对象与普通分支引用。](/learn-agent-rust/figures/r18-workspace-binding.svg)

读图时先看左右两个文件框：同名文件可以保留不同内容。再看下方的公共 Git 数据：worktree 的目录隔离不会把仓库复制成两份完全独立的权限域。

因此，创建独立目录还需要配合工具策略：由宿主选择 `cwd`，固定任务允许访问的工作区，并保管绑定关系。worktree 本身不限制进程读取别处文件或访问网络；R03 的权限判断仍然适用。

## 2. 先运行一次：两项任务修改同名文件

本章程序只接受一个**尚不存在的新目录**，在其中初始化专用练习仓库。它不接收现有项目地址，也不会把当前文档仓库当成实验对象。

::: info 代码只有一个来源
以下代码由 <a href="/learn-agent-rust/code/worktree-isolation.rs" download>完整 Rust 源码</a>片段导入，输出来自实际运行。<a href="/learn-agent-rust/code/worktree-isolation-README.md" download>README</a>给出全部运行说明，也可在 [GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/worktree-isolation.rs)。下载包包含源码、19 个场景输出和校验记录。
:::

解压后在目录里执行：

```sh
rustc --edition=2024 -D warnings worktree-isolation.rs -o worktree-lab
./worktree-lab parallel ./r18-parallel
```

<<< @/public/learn-agent-rust/outputs/r18-parallel.txt

两个真实线程分别在自己的目录里写入固定 README。实验让两个线程都先到达等待点，再分别放行并等待退出；这里验证的是并发任务能够共存并保留各自结果，没有测量速度。

先预测：甲写完后，练习主目录中的 README 是 `alpha`、`beta`，还是最初的 `cargo run`？输出中的 `primary_baseline=true` 给出答案：主目录保持基线，甲乙各自的变更仍在自己的工作区中。

可以继续检查真实文件和 Git 状态：

```sh
git -C ./r18-parallel/repository worktree list --porcelain
git -C ./r18-parallel/workspaces/alpha-a1 status --short
git -C ./r18-parallel/workspaces/beta-a1 status --short
```

两份 README 都有修改，回收策略因此返回 `changes`，保留两处工作区。`linked=2` 统计的是主工作区之外的两个登记；`retained=2` 是管理器明确决定保留的绑定数。

## 3. 一份绑定记录，回答“这里属于谁”

如果工具只接收一个任意路径，应用很难判断这个目录属于哪个任务、从什么基线开始，以及旧执行者是否还在使用它。我们先保存绑定，再允许固定文件工具执行。

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#binding

绑定里同时保留：

- `task + attempt`：一次任务执行的身份。
- `actor`：所属执行者及所有权版本。
- `base`：创建时解析出的确定提交。
- `branch + path`：结果引用与文件位置。
- `writer`：由宿主持有的写线程句柄。
- `disposition`：当前活跃、明确保留，或已回收。

这些字段在本实验管理器的内存里；Git 的目录、分支和 worktree 登记会实际落盘。退出后它们仍可人工检查，但程序没有实现从 Git 登记重建业务绑定。生产系统需要把绑定元数据与 R12 的业务任务记录关联，再设计重启核对流程。

### 创建前先拒绝覆盖

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#allocate

宿主先检查任务名、尝试号、许可和当前凭据，再从自己的根目录生成路径与分支。当前实例中同一任务只绑定一次；已有文件、目录或符号链接都会使分配停止。

`base` 先解析成提交 ID，再用于 `worktree add -b`，避免执行中因为 `main` 移动而失去“从哪里开始”的记录。命令使用新的分支，不加 `--force`，也不自动检出已有分支。

运行 `./worktree-lab existing-path ./r18-existing`：

<<< @/public/learn-agent-rust/outputs/r18-existing-path.txt

实验先在目标路径放入 `keep.txt`，分配随即被拒绝。验证脚本会从程序外读取该文件，确认没有覆盖。`branch-exists` 则预先建立同名分支，Git 拒绝创建，原引用仍保留。

Git 子进程用参数数组调用，任务名不会拼成 shell 命令：

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#git-command

程序还去掉继承的 `GIT_*` 路由与配置变量，使用练习目录中的空配置和 hooks 目录。验收时会把 `GIT_DIR`、`GIT_WORK_TREE`、`GIT_INDEX_FILE` 指向另一个哨兵仓库，再确认它没有被修改。路径包含空格也单独复验。

## 4. 检查绑定，再允许工具行动

绑定记录建立后，磁盘状态仍可能变化：目录被移走、分支被手工切换，或者执行者已经换成新版本。每次固定工具操作与回收前都要再次检查。

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#validate

这段代码核对当前凭据、绑定所属执行者、预期目录、实际仓库顶层、公共 Git 目录与分支。检查失败就返回错误，保留现场。`wrong-branch` 场景会手工切到另一个练习分支，再验证清理返回 `branch_mismatch`。

### 所有权失效后，旧线程还能写吗

`stale` 场景先启动写线程，让它停在实验门前；宿主把凭据从 `worker-a / epoch=1` 更新成 `worker-b / epoch=2`，再放行旧线程：

<<< @/public/learn-agent-rust/outputs/r18-stale.txt

worker 在真正写入前再次核对凭据，旧线程返回 `stale_owner`。旧执行者随后调用编辑和回收，也被拒绝。验证脚本会读取工作区文件，确认 README 仍是初始内容。

这里的凭据表由同一进程内的互斥锁保护，固定写工具在锁内完成本地写入，所以测试中的凭据更新与写入有明确先后。它验证了“操作前核对所有权版本”这条应用规则，**R17 的持久化租约、跨进程争抢与过期接管仍需单独实现和验收**。任意外部命令也不会自动遵守这个凭据表。

该场景中 `linked=1`、`retained=0`，并不意味着目录已删除：旧请求在权限入口就被拒绝，没有进入“明确保留”的状态迁移，原绑定与目录原样留下。

## 5. 任务结束后，先判断成果，再决定回收

“线程退出”只说明执行结束，不能说明目录可以删除。还要知道文件有没有变化，以及新提交是否已经进入目标分支。

![回收前依次核对绑定、写线程、文件变化和提交可达性，任一步不满足就保留工作区。](/learn-agent-rust/figures/r18-retirement-gates.svg)

从上到下读：身份失败会拒绝操作；写线程未回收、目录有变化、提交尚未合入会保留；只有全部检查通过，才请求 Git 移除工作区。图中的分支引用始终保留，便于后续核对。

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#retire

### 五种检查各自保护什么

| 检查 | 保护的内容 | 实验中的结果 |
| --- | --- | --- |
| 当前绑定与执行者 | 路径没有指向错误任务，旧凭据无权清理。 | 身份不符时拒绝，现场不变。 |
| 写线程句柄 | 防止清理目录时仍有宿主线程正在使用它。 | `busy`，先保留。 |
| 完整文件状态 | 已修改、已暂存、未跟踪和被忽略的数据。 | `changes`，保留。 |
| 目标主工作区与提交关系 | 避免隐藏冲突，以及把“已提交”误当成“已交付”。 | `target_dirty`、`history_changed` 或 `unmerged`。 |
| Git 的最终移除检查 | 锁定或其他 Git 拒绝条件。 | `git_refused`，保留。 |

普通 `git status` 往往不显示被忽略文件；本实验额外传入 `--ignored`，因此 `scratch/cache.bin` 也会阻止自动回收。这是本章选择的保守策略，缓存是否可删除应由明确的业务规则决定。

Git 的 `worktree remove` 本身保护脏工作区，但允许删除干净工作区。干净只表示索引和文件与当前提交一致，**并不说明这个分支的提交已经进入 `main`**。所以程序额外用祖先关系检查提交归属。

### 已提交但尚未合入：保留

运行 `./worktree-lab unmerged ./r18-unmerged`：

<<< @/public/learn-agent-rust/outputs/r18-unmerged.txt

README 的变化已经提交，目录干净，仍返回 `unmerged`。验证脚本核对 `main..codex/r18-alpha-a1` 中确实有一个提交，并从主仓库的共享对象库读取这个分支中的 README。

### 明确接收成果后：回收目录，保留分支

运行 `./worktree-lab accepted ./r18-accepted`：

<<< @/public/learn-agent-rust/outputs/r18-accepted.txt

这个场景由实验驱动明确执行一次本地 fast-forward，然后调用回收。提交已进入 `main`，工作区没有额外文件，也没有未回收线程，目录才被移除。

`primary_baseline=false` 在这里有明确含义：练习主分支接收了 `alpha` 的提交。它不是文件串写；验证脚本会比较两个分支的提交 ID，并检查主 README 的实际内容。回收方法本身不合并代码、不删除分支，也不推送远端。

## 6. 文件隔离以后，合并冲突仍然存在

甲乙在各自目录里把同一行改成不同内容，两个提交都可以独立产生。但当它们要进入同一个目标分支时，Git 仍需判断如何组合。

![两个独立 worktree 保留不同修改，接收 alpha 后合并 beta 会产生真实冲突并保留现场。](/learn-agent-rust/figures/r18-isolation-and-integration.svg)

这张图把执行阶段与集成阶段分开。上方两份结果互不覆盖；下方在练习主工作区汇合时出现冲突。隔离让成果归属更清楚，冲突由集成步骤显式暴露。

运行 `./worktree-lab conflict ./r18-conflict`：

<<< @/public/learn-agent-rust/outputs/r18-conflict.txt

场景先接收 `alpha`，再尝试合并 `beta`，保留真实冲突。外部验证确认主索引中 `README.md` 为 `UU`、包含三个冲突阶段，两处分支中的文件仍分别为 `alpha` 与 `beta`。

此时主工作区不干净，两处回收都返回 `target_dirty`。程序不会自动选择一方、自动提交或丢弃冲突。你可以在专用练习目录里检查差异，再决定怎样组合；实际业务中的评审、测试与发布属于独立步骤。

## 7. 停止写入者，再处理目录生命周期

工作区属于任务，写线程属于宿主运行时。回收必须同时尊重这两种归属。

`busy` 先让真实线程等待，然后尝试回收，得到 `busy`；接着取消等待中的写入、`join`，再次检查目录：

<<< @/public/learn-agent-rust/outputs/r18-busy.txt

这里没有发生文件变化，所以第二次可以回收。如果线程已经写出变化，`join` 之后还会继续走文件检查并保留成果。

当整个管理器离开作用域时，析构只负责释放等待中的线程并等待退出，文件与 worktree 全部保留：

<<< @/public/learn-agent-rust/code/worktree-isolation.rs#shutdown

与 R13 的固定半成品清理不同，代码任务可能有尚未评审的成果，因此本章选择**先保留工作区，再由显式回收方法检查**。实验没有自动归档、跨进程恢复或后台垃圾回收。

如果路径已经消失，回收会报 `workspace_missing`，保留 Git 登记作诊断；不会顺手执行全仓库 `prune`。`locked` 场景还验证：即使目录干净，已锁定的 worktree 也保留，程序不会为了清理而追加 `--force`。

## 8. 动手验收：核对真实 Git，而不只看日志

先运行 Rust 测试，再分别运行自己想观察的场景：

```sh
rustc --edition=2024 -D warnings --test worktree-isolation.rs -o worktree-tests
./worktree-tests --test-threads=1
./worktree-lab ignored ./r18-ignored
./worktree-lab locked ./r18-locked
```

所有场景的目标目录必须尚不存在；程序无论成功或失败都保留练习目录。这样可以在运行后检查真实文件、Git 登记、分支与索引。测试驱动只在核对完成后清理它自己创建的临时实验数据。

**本章验证记录：** 本地使用 `rustc 1.99.1 (58cf8f9c3 2026-10-13)`、`git version 2.54.0 (Apple Git-157)`，通过 12 个 Rust 测试与 19 个 CLI 场景。12 个测试的口径为 macOS/Linux，符号链接测试限 Unix。并发写入使用真实线程，仓库、提交、合并冲突和目录移除都由本地 Git 实际执行；任务凭据和任务内容采用固定 fixture。

| 场景 | 剩余关联 worktree | 明确保留的绑定 | 已回收的绑定 |
| --- | --- | --- | --- |
| `clean` | 0 | 0 | 1 |
| `parallel` | 2 | 2 | 0 |
| `tracked` | 1 | 1 | 0 |
| `staged` | 1 | 1 | 0 |
| `untracked` | 1 | 1 | 0 |
| `ignored` | 1 | 1 | 0 |
| `unmerged` | 1 | 1 | 0 |
| `accepted` | 0 | 0 | 1 |
| `conflict` | 2 | 2 | 0 |
| `busy` | 0 | 0 | 1 |
| `stale` | 1 | 0 | 0 |
| `duplicate` | 1 | 0 | 0 |
| `existing-path` | 0 | 0 | 0 |
| `branch-exists` | 0 | 0 | 0 |
| `denied` | 0 | 0 | 0 |
| `invalid-task` | 0 | 0 | 0 |
| `unknown` | 0 | 0 | 0 |
| `locked` | 1 | 1 | 0 |
| `wrong-branch` | 1 | 0 | 0 |

“剩余关联 worktree”不含练习主工作区，也不含创建失败前就存在的普通目录；“明确保留”只统计进入 `Retained` 状态的绑定。`stale`、`duplicate`、`wrong-branch` 都在入口被拒绝，原有工作区依旧存在，所以必须把状态迁移与真实目录数量分开看。

在网站仓库中，可以重新执行全部验收：

```sh
python3 scripts/verify-agent-worktrees.py
python3 scripts/verify-agent-worktrees.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R18
```

验证脚本会从外部检查文件内容、索引状态、分支引用、公共对象库、合并冲突和保留目录，并复验路径空格、继承的 Git 路由与现有目录保护。`--check` 还会从最终下载包解压、编译，重新执行全部 19 个场景。证据保存源文件摘要；配图数据只从这些真实结果读取。

## 9. 放回 Agent 的执行链

在课程的目标架构中，R17 的领取结果提供业务任务、执行尝试和所有权版本；R18 的宿主工作区管理器据此分配固定目录。图节点只传递可序列化的绑定身份，运行时保管线程与路径核对逻辑；工具执行前仍经过权限判断。

本章只实现独立管理器与固定文件工具。`langchain-rust` 消息、`graph-flow` 节点、真实模型、R17 存储、任意 shell 工具与跨进程恢复没有接入这一实验，完整接线需要在 R20 中单独验收。

下面原样保留参考课程的 Python/Claude 工作区隔离图，接口与编号沿用上游：

![参考课程把任务绑定到独立 worktree，并通过生命周期动作管理代码工作区。](/learn-agent-rust/figures/upstream/r18-worktree-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s18/) · [原图](https://learn.shareai.run/course-assets/s18_worktree_isolation/worktree-overview.svg)。关注任务与工作区的对应关系；Rust 实验另外核对了索引隔离、旧凭据拒绝、未合入成果与显式回收。来源版本和许可见[参考资料说明](./architecture.md#reference-assets)。

::: warning 常见误区
- 工作区目录与索引独立，普通分支引用和 Git 公共数据仍然共享；worktree 不提供进程、网络或权限沙箱。
- 目录干净只说明没有未提交变化；回收前还要核对提交是否进入目标分支。
- 被忽略文件也可能有价值。本实验发现它们就保留；删除失败或 Git 拒绝不会触发强制重试。
- 任务完成、线程退出、成果接收与目录回收是不同事件；本章没有自动合并或自动归档。
- 凭据与检查只约束本实验单宿主的固定工具。外部进程并发操作目录会引入检查与使用之间的竞争，需要额外执行隔离和协调。
- Git 子进程没有内置超时；验收脚本的外层超时不代表管理器已具备进程树终止能力。
:::

## 本章结论：隔离执行，明确接收，谨慎回收

本章选择一次任务尝试绑定一个固定基线与新 worktree，使用独立目录和索引保留各自修改。宿主在行动前核对所有权与实际仓库关系，持有写线程直到回收；目录有变化、提交未接收或 Git 拒绝时保留现场。

隔离让修改归属清楚，集成让冲突显式出现，回收则要求拿出成果已被接收的证据。三步分别验收，才能让并行代码任务留下可检查的结果。

## 检查理解

1. 甲在自己的 worktree 暂存 README，乙会看到同一份暂存区吗？

   <details><summary>参考答案</summary>

   每个 worktree 有自己的索引与 HEAD，所以乙不会直接看到甲的暂存变化。提交对象和普通分支引用仍共享，乙可以通过仓库引用读取甲已提交的内容。目录隔离与访问控制是不同问题。

   </details>

2. `git status` 干净，为什么回收还会返回 `unmerged`？

   <details><summary>参考答案</summary>

   新修改已经提交后，状态可以干净，但这个提交可能只在任务分支上。实验额外检查该 HEAD 是否已成为 `main` 的祖先；未进入目标历史时保留工作区，分支引用也保留。

   </details>

3. 把任务凭据的 owner 改成新执行者，旧目录可以直接复用吗？

   <details><summary>参考答案</summary>

   原绑定还记录着原 owner、epoch、attempt 和 base。旧执行者会被拒绝，新执行者也不能靠换一个调用参数接管旧绑定。需要显式设计交接或新的执行尝试，并检查原成果；本实验未实现持久化交接。

   </details>

4. 为什么两个独立 worktree 都成功提交，集成仍然可能冲突？

   <details><summary>参考答案</summary>

   独立目录避免执行阶段相互覆盖，提交描述的逻辑变化仍可能修改同一行。把两份变化组合到同一目标分支时，Git 会暴露冲突，需要评审并确定最终内容。本章 conflict 场景保留了真实索引冲突。

   </details>

5. 管理器析构时为什么只停止线程，不直接删除 worktree？

   <details><summary>参考答案</summary>

   线程退出后仍可能有未提交、未跟踪、被忽略或尚未合入的成果。析构负责结束宿主持有的执行资源；目录回收通过显式方法重新核对身份、文件状态和提交关系，满足条件后才请求 Git 移除。

   </details>

## 参考资料

- [Git worktree：独立 HEAD/索引、共享引用与移除规则](https://git-scm.com/docs/git-worktree)。
- [Git status：porcelain、未跟踪与忽略文件](https://git-scm.com/docs/git-status)。
- [Git merge-base：`--is-ancestor` 可达性检查](https://git-scm.com/docs/git-merge-base)。
- [Learn Claude Code · Worktree Isolation](https://learn.shareai.run/zh/s18/)，通用机制与原图参考。
- <a href="/learn-agent-rust/code/worktree-isolation.rs" download>完整源码</a> · <a href="/learn-agent-rust/code/worktree-isolation-README.md" download>运行说明</a> · <a href="/learn-agent-rust/worktree-isolation-lab.zip" download>独立学习包</a>。

下一章：[第 19 章：MCP 外部工具](./mcp-tools.md)。把执行范围从本地固定工具扩展到外部服务时，继续核对工具身份、连接和生命周期。
