---
title: "第 16 章：团队协作协议"
description: "队友怎样批准、拒绝、汇报和退出？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 16 章：团队协作协议

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

队友怎样批准、拒绝、汇报和退出？

## 本章主线选择（待实验验证）

类型化消息、关联身份与协议状态迁移。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 15 章 · Agent 团队](./agent-teams.md)

## 计划验收

拒绝非法协议消息，验证关闭握手、超时和失败退出。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![团队协作通过类型化消息完成审批、汇报与退出。](/learn-agent-rust/figures/upstream/r16-team-protocols-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s16/) · [原图](https://learn.shareai.run/course-assets/s16_team_protocols/team-protocols-overview.svg)。关注协议消息与状态的对应关系，Rust 版单独检查非法消息和退出路径。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r16)查看本章位置。
