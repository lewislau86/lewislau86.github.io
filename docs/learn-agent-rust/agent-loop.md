---
title: "第 1 章：最小 Agent 循环"
description: "模型怎样请求工具，看到执行结果后再继续？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 1 章：最小 Agent 循环

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

模型怎样请求工具，看到执行结果后再继续？

## 本章主线选择（待实验验证）

显式循环、结构化调用、消息配对与停止状态。

**所在模块：** 工具与执行

**前置与基础：** [第 0 章 · 整体架构与环境](./architecture-and-setup.md)

## 计划验收

用脚本模型完成一次文件读取，核对消息、call_id、轮次和预算耗尽路径。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![模型请求工具、工具结果回传与继续生成组成最小循环。](/learn-agent-rust/figures/upstream/r01-agent-loop.svg)

图源：[参考章节](https://learn.shareai.run/zh/s01/) · [原图](https://learn.shareai.run/course-assets/s01_agent_loop/agent-loop.svg)。先沿循环读一遍，Rust 版将使用结构化 tool_calls 关联结果，具体协议以章节实验为准。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r01)查看本章位置。
