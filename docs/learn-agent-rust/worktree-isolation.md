---
title: "第 18 章：工作区隔离"
description: "并发代码任务怎样拥有独立文件与变更归属？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 18 章：工作区隔离

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

并发代码任务怎样拥有独立文件与变更归属？

## 本章主线选择（待实验验证）

任务绑定的练习 worktree 与资源回收策略。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 3 章 · 工具权限与审批](./permissions.md)、[第 17 章 · 自主任务领取](./autonomous-workers.md)

## 计划验收

在专用练习仓库验证创建、绑定、保留和回收，不覆盖已有修改。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![任务绑定独立 worktree，以隔离文件修改与资源生命周期。](/learn-agent-rust/figures/upstream/r18-worktree-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s18/) · [原图](https://learn.shareai.run/course-assets/s18_worktree_isolation/worktree-overview.svg)。关注任务和工作区的绑定关系，Rust 实验只在专用练习仓库中实施。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r18)查看本章位置。
