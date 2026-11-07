---
title: "第 20 章：完整 Agent 集成"
description: "工具、策略、上下文、任务与团队怎样围绕同一个循环工作？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 20 章：完整 Agent 集成

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

工具、策略、上下文、任务与团队怎样围绕同一个循环工作？

## 本章主线选择（待实验验证）

统一事件、累计预算和跨机制的端到端路径。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 4 章 · 生命周期与 Hooks](./hooks.md)、[第 5 章 · 可见的任务清单](./todo-planning.md)、[第 6 章 · 子 Agent 与上下文隔离](./subagents.md)、[第 7 章 · 按需加载技能](./skill-loading.md)、[第 8 章 · 上下文压缩](./context-compaction.md)、[第 9 章 · 跨会话记忆](./memory.md)、[第 10 章 · 系统提示词组装](./system-prompts.md)、[第 11 章 · 错误分类与恢复](./error-recovery.md)、[第 14 章 · 定时调度](./scheduling.md)、[第 16 章 · 团队协作协议](./team-protocols.md)、[第 18 章 · 工作区隔离](./worktree-isolation.md)、[第 19 章 · MCP 外部工具](./mcp-tools.md)

## 计划验收

重新验收完整任务与故障路径，分别记录模块通过与集成通过。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![上下文、策略、任务、团队和外部工具围绕同一循环协同。](/learn-agent-rust/figures/upstream/r20-system-architecture.svg)

图源：[参考章节](https://learn.shareai.run/zh/s20/) · [原图](https://learn.shareai.run/course-assets/s20_comprehensive/system-architecture.svg)。这张图展示原课程完整系统，Rust 版以本课程章节清单为准，图中数量不是 Rust 实测值。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r20)查看本章位置。
