---
title: "第 8 章：上下文压缩"
description: "对话历史太长时，怎样保留继续行动需要的事实？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 8 章：上下文压缩

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

对话历史太长时，怎样保留继续行动需要的事实？

## 本章主线选择（待实验验证）

上下文预算、裁剪与历史摘要。

**所在模块：** 记忆管理

**前置与基础：** [第 1 章 · 最小 Agent 循环](./agent-loop.md)、[第 7 章 · 按需加载技能](./skill-loading.md)

## 计划验收

检查压缩前后的事实保留与工具消息配对，记录摘要遗漏的失败用例。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-compact-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/compact-overview.svg)。按图辨认压缩发生的位置，Rust 版将检查事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-compaction-layers.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/compaction-layers.svg)。按图辨认压缩发生的位置，Rust 版将检查事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-micro-compact.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/micro-compact.svg)。按图辨认压缩发生的位置，Rust 版将检查事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-layer1-budget.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/layer1-budget.svg)。按图辨认压缩发生的位置，Rust 版将检查事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-auto-compact.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/auto-compact.svg)。按图辨认压缩发生的位置，Rust 版将检查事实保留与工具消息配对。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r08)查看本章位置。
