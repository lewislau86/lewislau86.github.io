---
title: 全书实验代码库
description: 按章节下载、运行和检查 Learn Agent by Rust 的全部实验。
pageClass: learn-agent-rust-course
---

# 全书实验代码库

[课程总览](./index.md) · [环境准备](./setup.md) · [学习路径](./learning-path.md)

全书 28 个实验单元按主题目录打包，包含源码、Cargo 锁文件、夹具、运行说明、发布时输出和检查证据。解压后可独立运行。

<a href="/learn-agent-rust/learn-agent-rust-experiments.zip" download>下载全书实验代码库（zip）</a> · [在 GitHub 浏览代码库](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust)

## 下载后先跑一章

按[环境准备](./setup.md)安装 Rust 1.99.1、rustfmt、Clippy、Git 和 C 编译工具；统一入口需要 Python 3.9+ 标准库。建议使用 macOS、Linux 或 WSL。

解压后进入 `learn-agent-rust-experiments` 目录：

```sh
python3 run.py list
python3 run.py doctor
python3 run.py integrity
python3 run.py run R01
python3 run.py test R01
python3 run.py run R20 --keep ./my-results
```

`run` 编译并执行本页对应的演示；`test` 增加 Rust 测试、格式检查和 Cargo 工程的 Clippy。程序在临时目录运行，`--keep` 保存运行产物。每章也可进入 `chapters/<主题>/`，按 README 单独操作。

## 全书重跑

```sh
python3 run.py test --all
# 工具链和依赖已缓存后，可检查离线运行：
python3 run.py test --all --offline
```

首次构建需要网络下载依赖。P01、P04 另需 PostgreSQL 18 服务端工具，脚本以普通用户创建并清理专用临时集群；工具不在 PATH 时设置 `P01_PG_BIN` 和 `P04_PG_BIN`。没有数据库环境时可显式加 `--skip-postgres`，结果会列出跳过项。

## 按章找到实验

目录名与文章主题名一致；编号仅用于阅读和命令选择。

### R00 · 整体架构与环境 {#architecture-and-setup}

[阅读本章](./architecture-and-setup.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/architecture-and-setup)

目录：`chapters/architecture-and-setup/`；运行：`python3 run.py run R00`。本章正常路径演示。

原章节验证器：`scripts/verify-learn-agent-rust.py`。

### R01 · 最小 Agent 循环 {#agent-loop}

[阅读本章](./agent-loop.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/agent-loop)

目录：`chapters/agent-loop/`；运行：`python3 run.py run R01`。本章正常路径演示。

原章节验证器：`scripts/verify-learn-agent-rust-loop.py`。

### R02 · 工具注册与图调度 {#tools-and-graph}

[阅读本章](./tools-and-graph.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/tools-and-graph)

目录：`chapters/tools-and-graph/`；运行：`python3 run.py run R02`。本章正常路径演示。

原章节验证器：`scripts/verify-learn-agent-rust-r02.py`。

### R03 · 工具权限与审批 {#permissions}

[阅读本章](./permissions.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/permissions)

目录：`chapters/permissions/`；运行：`python3 run.py run R03`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-permissions.py`。

### R04 · 生命周期与 Hooks {#hooks}

[阅读本章](./hooks.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/hooks)

目录：`chapters/hooks/`；运行：`python3 run.py run R04`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-hooks.py`。

### R05 · 可见的任务清单 {#todo-planning}

[阅读本章](./todo-planning.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/todo-planning)

目录：`chapters/todo-planning/`；运行：`python3 run.py run R05`。本章正常路径演示。

原章节验证器：`scripts/verify-learn-agent-rust-r05.py`。

### R06 · 子 Agent 与上下文隔离 {#subagents}

[阅读本章](./subagents.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/subagents)

目录：`chapters/subagents/`；运行：`python3 run.py run R06`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-subagents.py`。

### R07 · 按需加载技能 {#skill-loading}

[阅读本章](./skill-loading.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/skill-loading)

目录：`chapters/skill-loading/`；运行：`python3 run.py run R07`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-skills.py`。

### K01 · RAG：检索、证据与回答 {#retrieval-augmented-generation}

[阅读本章](./retrieval-augmented-generation.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/retrieval-augmented-generation)

目录：`chapters/retrieval-augmented-generation/`；运行：`python3 run.py run K01`。11 个检索与证据场景。

原章节验证器：`scripts/verify-agent-rag.py`。

### R08 · 上下文压缩 {#context-compaction}

[阅读本章](./context-compaction.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/context-compaction)

目录：`chapters/context-compaction/`；运行：`python3 run.py run R08`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-compaction.py`。

### R09 · 跨会话记忆 {#memory}

[阅读本章](./memory.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/memory)

目录：`chapters/memory/`；运行：`python3 run.py run R09`。跨进程写入与召回演示。

原章节验证器：`scripts/verify-agent-memory.py`。

### R10 · 系统提示词组装 {#system-prompts}

[阅读本章](./system-prompts.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/system-prompts)

目录：`chapters/system-prompts/`；运行：`python3 run.py run R10`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-prompts.py`。

### R11 · 错误分类与恢复 {#error-recovery}

[阅读本章](./error-recovery.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/error-recovery)

目录：`chapters/error-recovery/`；运行：`python3 run.py run R11`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-recovery.py`。

### R12 · 持久化任务系统 {#task-system}

[阅读本章](./task-system.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/task-system)

目录：`chapters/task-system/`；运行：`python3 run.py run R12`。多步持久状态演示。

原章节验证器：`scripts/verify-agent-tasks.py`。

### R13 · 后台任务 {#background-tasks}

[阅读本章](./background-tasks.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/background-tasks)

目录：`chapters/background-tasks/`；运行：`python3 run.py run R13`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-background.py`。

### R14 · 定时调度 {#scheduling}

[阅读本章](./scheduling.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/scheduling)

目录：`chapters/scheduling/`；运行：`python3 run.py run R14`。多步持久状态演示。

原章节验证器：`scripts/verify-agent-scheduling.py`。

### R15 · Agent 团队 {#agent-teams}

[阅读本章](./agent-teams.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/agent-teams)

目录：`chapters/agent-teams/`；运行：`python3 run.py run R15`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-teams.py`。

### R16 · 团队协作协议 {#team-protocols}

[阅读本章](./team-protocols.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/team-protocols)

目录：`chapters/team-protocols/`；运行：`python3 run.py run R16`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-protocols.py`。

### R17 · 自主任务领取 {#autonomous-workers}

[阅读本章](./autonomous-workers.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/autonomous-workers)

目录：`chapters/autonomous-workers/`；运行：`python3 run.py run R17`。多步持久状态演示。

原章节验证器：`scripts/verify-agent-workers.py`。

### R18 · 工作区隔离 {#worktree-isolation}

[阅读本章](./worktree-isolation.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/worktree-isolation)

目录：`chapters/worktree-isolation/`；运行：`python3 run.py run R18`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-worktrees.py`。

### R19 · MCP 外部工具 {#mcp-tools}

[阅读本章](./mcp-tools.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/mcp-tools)

目录：`chapters/mcp-tools/`；运行：`python3 run.py run R19`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-mcp.py`。

### R20 · 完整 Agent 集成 {#integrated-agent}

[阅读本章](./integrated-agent.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/integrated-agent)

目录：`chapters/integrated-agent/`；运行：`python3 run.py run R20`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-integration.py`。

### P01 · PostgreSQL 检查点 {#postgres-checkpoints}

[阅读本章](./postgres-checkpoints.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/postgres-checkpoints)

目录：`chapters/postgres-checkpoints/`；运行：`python3 run.py run P01`。完整本地 Python 套件；需要 PostgreSQL 18。

原章节验证器：`scripts/verify-agent-checkpoints.py`。

### P02 · 外部操作的可靠性 {#side-effect-reliability}

[阅读本章](./side-effect-reliability.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/side-effect-reliability)

目录：`chapters/side-effect-reliability/`；运行：`python3 run.py run P02`。本章正常路径演示。

原章节验证器：`scripts/verify-agent-effects.py`。

### P03 · 模型协议与质量评估 {#model-evaluation}

[阅读本章](./model-evaluation.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/model-evaluation)

目录：`chapters/model-evaluation/`；运行：`python3 run.py run P03`。完整本地 Python 套件。

原章节验证器：`scripts/verify-agent-evaluation.py`。

### P04 · 生产准入与演练 {#production-readiness}

[阅读本章](./production-readiness.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/production-readiness)

目录：`chapters/production-readiness/`；运行：`python3 run.py run P04`。完整本地 Python 套件；需要 PostgreSQL 18。

原章节验证器：`scripts/verify-agent-production.py`。

### P05 · 固定工作流与目标控制 {#workflow-and-goal-control}

[阅读本章](./workflow-and-goal-control.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/workflow-and-goal-control)

目录：`chapters/workflow-and-goal-control/`；运行：`python3 run.py run P05`。完整本地 Python 套件。

原章节验证器：`scripts/verify-agent-goals.py`。

### P06 · Agent RSI 与受控自我改进 {#agent-rsi}

[阅读本章](./agent-rsi.md) · [查看实验目录](https://github.com/lewislau86/lewislau86.github.io/tree/master/experiments/learn-agent-rust/chapters/agent-rsi)

目录：`chapters/agent-rsi/`；运行：`python3 run.py run P06`。三种策略发布/拒绝/回滚演示。

原章节验证器：`scripts/verify-agent-rsi.py`。

## 发布前检查记录

逐章原验证器 28/28 通过。<a href="/learn-agent-rust/experiment-audit.json" download>下载全书检查记录</a>，内含检查日期、逐章退出码、工具环境和源码摘要。

这些原验证器检查各章正常与故障场景、正文引用输出和已有章节包。统一代码库的 `test --all` 另行检查格式、Rust 测试、Clippy 和本页列出的演示；P01、P03、P04、P05 会执行各章 Python 完整本地套件。

模型响应与审批使用固定夹具；HTTP、stdio、文件、SQLite、PostgreSQL 与 Git 操作是否真实执行，以各章 evidence.json 的范围为准。P03 可选外部模型请求未纳入默认命令，协议通过和模型质量分别记录。时延、进程号与平台路径属于当次观测。

## 维护唯一来源

`experiments/learn-agent-rust/` 和 zip 均由 `scripts/package-agent-experiments.py` 生成；修改实验时先改网站 `docs/public/learn-agent-rust/code/` 的源码，更新章节验证产物，再运行全书检查与打包。`--check` 会拒绝缺章、源码与章节包不一致、检查证据过期或生成目录漂移。
