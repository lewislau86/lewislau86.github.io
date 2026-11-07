---
title: "第 12 章：持久化任务系统"
description: "任务依赖与执行状态怎样在进程退出后保留？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 12 章：持久化任务系统

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

任务依赖与执行状态怎样在进程退出后保留？

## 本章主线选择（待实验验证）

业务任务身份、依赖校验、合法迁移与单执行者存储。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 5 章 · 可见的任务清单](./todo-planning.md)、[第 11 章 · 错误分类与恢复](./error-recovery.md)

## 计划验收

从新进程恢复任务，拒绝依赖环，并观察保存失败和损坏记录。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![持久化任务用依赖关系和状态迁移组织执行。](/learn-agent-rust/figures/upstream/r12-task-system-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s12/) · [原图](https://learn.shareai.run/course-assets/s12_task_system/task-system-overview.svg)。关注任务身份与依赖边，图节点和业务任务的职责分别说明。

![持久化任务用依赖关系和状态迁移组织执行。](/learn-agent-rust/figures/upstream/r12-task-dag.svg)

图源：[参考章节](https://learn.shareai.run/zh/s12/) · [原图](https://learn.shareai.run/course-assets/s12_task_system/task-dag.svg)。关注任务身份与依赖边，图节点和业务任务的职责分别说明。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r12)查看本章位置。
