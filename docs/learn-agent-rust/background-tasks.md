---
title: "第 13 章：后台任务"
description: "慢工具怎样在后台运行，同时保持可查询与可取消？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 13 章：后台任务

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

慢工具怎样在后台运行，同时保持可查询与可取消？

## 本章主线选择（待实验验证）

有界后台执行、任务句柄、通知与资源回收。

**所在模块：** 并发与调度

**前置与基础：** [第 12 章 · 持久化任务系统](./task-system.md)

## 计划验收

验证启动、查询、取消、完成通知与退出清理的完整生命周期。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![后台执行将慢操作与当前模型循环分离，并通过通知传回结果。](/learn-agent-rust/figures/upstream/r13-background-tasks-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s13/) · [原图](https://learn.shareai.run/course-assets/s13_background_tasks/background-tasks-overview.svg)。关注启动、完成和查询路径，Rust 版需要单独验证取消与资源回收。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r13)查看本章位置。
