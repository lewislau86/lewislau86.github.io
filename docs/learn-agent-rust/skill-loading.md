---
title: "第 7 章：按需加载技能"
description: "怎样只在任务需要时加入专业说明？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 7 章：按需加载技能

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

怎样只在任务需要时加入专业说明？

## 本章主线选择（待实验验证）

技能目录、版本与按需内容注入。

**所在模块：** 规划与控制

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)

## 计划验收

观察加载前后的上下文，验证技能内容与执行权限分别受控。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![技能说明通过目录发现并在需要时展开。](/learn-agent-rust/figures/upstream/r07-skill-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s07/) · [原图](https://learn.shareai.run/course-assets/s07_skill_loading/skill-overview.svg)。观察技能元信息和完整内容的分离，加载知识不会自动授予执行权限。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r07)查看本章位置。
