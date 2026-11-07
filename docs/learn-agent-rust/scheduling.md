---
title: "第 14 章：定时调度"
description: "定时触发怎样在重启后继续，并处理重复触发？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 14 章：定时调度

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

定时触发怎样在重启后继续，并处理重复触发？

## 本章主线选择（待实验验证）

有时区的持久化调度与触发身份。

**所在模块：** 并发与调度

**前置与基础：** [第 12 章 · 持久化任务系统](./task-system.md)、[第 13 章 · 后台任务](./background-tasks.md)

## 计划验收

检查错过触发、重复触发和调度重启时的行为。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![定时调度把持久化计划转为到期触发的任务。](/learn-agent-rust/figures/upstream/r14-cron-scheduler-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s14/) · [原图](https://learn.shareai.run/course-assets/s14_cron_scheduler/cron-scheduler-overview.svg)。关注计划和任务的边界，时区、重启和重复触发将在 Rust 示例中明确。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r14)查看本章位置。
