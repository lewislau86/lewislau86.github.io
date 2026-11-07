---
title: "第 6 章：子 Agent 与上下文隔离"
description: "怎样把一次子任务放进独立的消息历史？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 6 章：子 Agent 与上下文隔离

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

怎样把一次子任务放进独立的消息历史？

## 本章主线选择（待实验验证）

子会话输入输出契约与父子预算。

**所在模块：** 规划与控制

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)

## 计划验收

验证子任务历史独立、结果回传、预算约束和取消时的资源清理。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![子 Agent 使用独立消息历史并将结果返回父会话。](/learn-agent-rust/figures/upstream/r06-subagent-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s06/) · [原图](https://learn.shareai.run/course-assets/s06_subagent/subagent-overview.svg)。关注父子上下文与结果边界，Rust 版补充父子预算和退出清理。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r06)查看本章位置。
