---
title: "第 9 章：跨会话记忆"
description: "哪些事实应当在新会话中仍然可用？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 9 章：跨会话记忆

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

哪些事实应当在新会话中仍然可用？

## 本章主线选择（待实验验证）

有来源和版本的事实存储、提取与召回。

**所在模块：** 记忆管理

**前置与基础：** [第 8 章 · 上下文压缩](./context-compaction.md)

## 计划验收

在新会话中召回指定事实，并验证冲突、更新和损坏记录的处理。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![长期记忆经过筛选、提取与整理，在后续会话召回。](/learn-agent-rust/figures/upstream/r09-memory-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s09/) · [原图](https://learn.shareai.run/course-assets/s09_memory/memory-overview.svg)。关注记忆来源和更新路径，Rust 版存储与召回算法尚未实现。

![长期记忆经过筛选、提取与整理，在后续会话召回。](/learn-agent-rust/figures/upstream/r09-memory-subsystems.svg)

图源：[参考章节](https://learn.shareai.run/zh/s09/) · [原图](https://learn.shareai.run/course-assets/s09_memory/memory-subsystems.svg)。关注记忆来源和更新路径，Rust 版存储与召回算法尚未实现。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r09)查看本章位置。
