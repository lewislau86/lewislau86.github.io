---
title: "专题 1：PostgreSQL 检查点"
description: "一个模型轮次或工具步骤怎样成为可恢复的检查点？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 专题 1：PostgreSQL 检查点

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

一个模型轮次或工具步骤怎样成为可恢复的检查点？

## 本章主线选择（待实验验证）

版本化会话、逐轮和逐工具保存边界。

**所在模块：** 可靠性专题

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 11 章 · 错误分类与恢复](./error-recovery.md)、[第 12 章 · 持久化任务系统](./task-system.md)

## 计划验收

用独立进程与故障注入验证恢复，并明确工具成功而保存失败的窗口。

回到[学习路径](./learning-path.md#p01)查看本章位置。
