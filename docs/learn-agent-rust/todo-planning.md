---
title: "第 5 章：可见的任务清单"
description: "长任务怎样记录目标、步骤和当前进度？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 5 章：可见的任务清单

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

长任务怎样记录目标、步骤和当前进度？

## 本章主线选择（待实验验证）

会话内待办清单与合法状态迁移。

**所在模块：** 规划与控制

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)

## 计划验收

展示计划变化，拒绝非法更新，区分个人待办与持久化任务队列。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![待办清单把计划与当前执行状态呈现给 Agent。](/learn-agent-rust/figures/upstream/r05-todo-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s05/) · [原图](https://learn.shareai.run/course-assets/s05_todo_write/todo-overview.svg)。关注计划更新与工具循环的关系，待办清单与持久化任务分别设计。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r05)查看本章位置。
