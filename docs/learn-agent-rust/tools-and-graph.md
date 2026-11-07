---
title: "第 2 章：工具注册与图调度"
description: "增加工具后，怎样让循环保持清晰并映射到图？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 2 章：工具注册与图调度

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

增加工具后，怎样让循环保持清晰并映射到图？

## 本章主线选择（待实验验证）

工具注册表，以及 ModelTurn 与 ExecuteTools 的图节点映射。

**所在模块：** 工具与执行

**前置与基础：** [第 1 章 · 最小 Agent 循环](./agent-loop.md)

## 计划验收

增加第二个只读工具，用相同用例比较显式版和图版的消息、调用与结果。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![工具注册与分发将可用能力接入共同的调用入口。](/learn-agent-rust/figures/upstream/r02-tool-dispatch.svg)

图源：[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/tool-dispatch.svg)。观察工具描述与执行入口的分工；Rust 第一版按顺序执行工具，原图中的并发设计留作后续对照。

![工具注册与分发将可用能力接入共同的调用入口。](/learn-agent-rust/figures/upstream/r02-concurrency-comparison.svg)

图源：[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/concurrency-comparison.svg)。观察工具描述与执行入口的分工；Rust 第一版按顺序执行工具，原图中的并发设计留作后续对照。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r02)查看本章位置。
