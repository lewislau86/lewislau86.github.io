---
title: "第 10 章：系统提示词组装"
description: "策略、工具、技能和环境怎样组成一次模型请求？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 10 章：系统提示词组装

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

策略、工具、技能和环境怎样组成一次模型请求？

## 本章主线选择（待实验验证）

运行时提示词组装与各部分的来源和版本。

**所在模块：** 规划与控制

**前置与基础：** [第 7 章 · 按需加载技能](./skill-loading.md)、[第 9 章 · 跨会话记忆](./memory.md)

## 计划验收

对照固定输入检查提示词组成，以及知识内容与应用策略的边界。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![系统提示词由策略、工具与环境等不同部分组装。](/learn-agent-rust/figures/upstream/r10-system-prompt-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s10/) · [原图](https://learn.shareai.run/course-assets/s10_system_prompt/system-prompt-overview.svg)。观察提示词各部分的来源，Rust 版将显式记录版本和配置。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r10)查看本章位置。
