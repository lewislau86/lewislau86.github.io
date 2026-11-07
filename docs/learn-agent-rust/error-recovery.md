---
title: "第 11 章：错误分类与恢复"
description: "什么错误值得重试，重试何时应该结束？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 11 章：错误分类与恢复

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

什么错误值得重试，重试何时应该结束？

## 本章主线选择（待实验验证）

类型化错误、有限重试、退避与累计预算。

**所在模块：** 规划与控制

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 8 章 · 上下文压缩](./context-compaction.md)

## 计划验收

区分临时和永久错误，验证重试或恢复后仍受总预算约束。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![错误分类影响重试、反馈与停止的路径。](/learn-agent-rust/figures/upstream/r11-error-recovery-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s11/) · [原图](https://learn.shareai.run/course-assets/s11_error_recovery/error-recovery-overview.svg)。关注哪些错误进入重试，Rust 版会增加明确的次数和总预算限制。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r11)查看本章位置。
