---
title: "第 17 章：自主任务领取"
description: "谁有权执行任务，原执行者退出后谁来接管？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 17 章：自主任务领取

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

谁有权执行任务，原执行者退出后谁来接管？

## 本章主线选择（待实验验证）

原子领取、所有权、租约与接管。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 12 章 · 持久化任务系统](./task-system.md)、[第 16 章 · 团队协作协议](./team-protocols.md)

## 计划验收

验证竞争领取、租约过期和旧执行者拒写，单独核对外部动作重放。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![自主执行者从任务系统领取工作并持续推进。](/learn-agent-rust/figures/upstream/r17-autonomous-agents-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s17/) · [原图](https://learn.shareai.run/course-assets/s17_autonomous_agents/autonomous-agents-overview.svg)。关注任务所有权与领取过程，原子性、租约和接管需由 Rust 存储实验验证。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r17)查看本章位置。
