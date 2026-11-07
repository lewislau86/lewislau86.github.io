---
title: "第 15 章：Agent 团队"
description: "多个执行者怎样分工，并保留各自的上下文？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 15 章：Agent 团队

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

多个执行者怎样分工，并保留各自的上下文？

## 本章主线选择（待实验验证）

独立会话、有界邮箱与队友生命周期。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 6 章 · 子 Agent 与上下文隔离](./subagents.md)、[第 12 章 · 持久化任务系统](./task-system.md)、[第 13 章 · 后台任务](./background-tasks.md)

## 计划验收

观察消息投递、队友等待与退出，明确单进程和跨进程能力范围。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![多个 Agent 通过邮箱和任务系统进行协作。](/learn-agent-rust/figures/upstream/r15-agent-teams-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s15/) · [原图](https://learn.shareai.run/course-assets/s15_agent_teams/agent-teams-overview.svg)。关注各自的上下文和共享通信入口；并发与跨进程能力按实际实验记录。

![多个 Agent 通过邮箱和任务系统进行协作。](/learn-agent-rust/figures/upstream/r15-team-topology.svg)

图源：[参考章节](https://learn.shareai.run/zh/s15/) · [原图](https://learn.shareai.run/course-assets/s15_agent_teams/team-topology.svg)。关注各自的上下文和共享通信入口；并发与跨进程能力按实际实验记录。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r15)查看本章位置。
