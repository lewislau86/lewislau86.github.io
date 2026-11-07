---
title: "第 3 章：工具权限与审批"
description: "模型提出动作后，谁决定允许、拒绝或等待审批？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 3 章：工具权限与审批

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

模型提出动作后，谁决定允许、拒绝或等待审批？

## 本章主线选择（待实验验证）

执行前权限判断与类型化审批状态。

**所在模块：** 工具与执行

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)

## 计划验收

验证拒绝路径没有执行工具，批准后只执行被批准的动作；跨进程恢复另行验收。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![权限判断先于工具执行，审批作为单独的决策过程。](/learn-agent-rust/figures/upstream/r03-permission-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-overview.svg)。关注动作如何经过允许、拒绝或审批分支，具体规则将在 Rust 版独立验证。

![权限判断先于工具执行，审批作为单独的决策过程。](/learn-agent-rust/figures/upstream/r03-permission-pipeline.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-pipeline.svg)。关注动作如何经过允许、拒绝或审批分支，具体规则将在 Rust 版独立验证。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r03)查看本章位置。
