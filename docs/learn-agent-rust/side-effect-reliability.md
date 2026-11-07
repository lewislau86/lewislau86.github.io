---
title: "专题 2：外部操作的可靠性"
description: "工具已产生业务结果、检查点却未保存时，怎样重放？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 专题 2：外部操作的可靠性

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

工具已产生业务结果、检查点却未保存时，怎样重放？

## 本章主线选择（待实验验证）

操作身份、业务幂等、Outbox 与对账。

**所在模块：** 可靠性专题

**前置与基础：** [专题 1 · PostgreSQL 检查点](./postgres-checkpoints.md)、[第 17 章 · 自主任务领取](./autonomous-workers.md)

## 计划验收

在指定故障窗口重试，核对重复调用与最终业务结果。

回到[学习路径](./learning-path.md#p02)查看本章位置。
