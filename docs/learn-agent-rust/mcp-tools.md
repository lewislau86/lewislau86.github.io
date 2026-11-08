---
title: "第 19 章：MCP 外部工具"
description: "外部服务怎样进入同一工具注册与调用体系？"
search: false
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 第 19 章：MCP 外部工具

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: info 本章状态：规划中
本页先列出本章问题、实现方向与验收目标。正文、可运行 Rust 示例和实验输出尚未完成。
:::

## 本章问题

外部服务怎样进入同一工具注册与调用体系？

## 本章主线选择（待实验验证）

工具发现、命名空间、schema 映射与连接生命周期。

**所在模块：** 多 Agent 平台

**前置与基础：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)、[第 11 章 · 错误分类与恢复](./error-recovery.md)

## 计划验收

锁定协议与客户端版本，用本地真实服务验证发现、调用、超时与退出。

<!-- r19-results:start -->

| 场景 | 远端调用 | 写入行数 | 验证结果 |
| --- | --- | --- | --- |
| `normal` | 1 | 0 | `ok,ok` |
| `dual-server` | 2 | 0 | `ok,ok` |
| `denied-write` | 0 | 0 | `approval_required` |
| `approved-write` | 1 | 1 | `ok` |
| `approval-mismatch` | 0 | 0 | `approval_required` |
| `invalid-arguments` | 0 | 0 | `invalid_arguments` |
| `unknown-tool` | 0 | 0 | `unknown_tool` |
| `duplicate-call` | 1 | 0 | `ok,duplicate_call` |
| `tool-error` | 1 | 0 | `tool_error` |
| `protocol-error` | 1 | 0 | `protocol_error` |
| `timeout` | 1 | 0 | `timeout,connection_unavailable` |
| `write-timeout` | 1 | 1 | `outcome_unknown,connection_unavailable` |
| `server-crash` | 1 | 0 | `transport_error,connection_unavailable` |
| `discovery-duplicate` | 0 | 0 | `duplicate_alias` |
| `discovery-schema` | 0 | 0 | `unsupported_schema` |
| `discovery-name` | 0 | 0 | `unsupported_name` |
| `cursor-loop` | 0 | 0 | `cursor_loop` |
| `missing-capability` | 0 | 0 | `capability_or_version` |
| `startup-exit` | 0 | 0 | `handshake_failed` |
| `startup-timeout` | 0 | 0 | `startup_timeout` |
| `dirty-stdout` | 0 | 0 | `handshake_failed` |
| `list-timeout` | 0 | 0 | `discovery_failed` |
| `result-limit` | 1 | 0 | `result_limit` |
| `closed-registry` | 0 | 0 | `unknown_tool` |
| `call-budget` | 8 | 0 | `ok,ok,ok,ok,ok,ok,ok,ok,call_budget` |

<!-- r19-results:end -->

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。Rust 版按本章计划实现后另行验证。

![MCP 服务发现的外部工具经适配进入统一工具池。](/learn-agent-rust/figures/upstream/r19-mcp-architecture.svg)

图源：[参考章节](https://learn.shareai.run/zh/s19/) · [原图](https://learn.shareai.run/course-assets/s19_mcp_plugin/mcp-architecture.svg)。关注发现、命名与调用路径，Rust 版将锁定客户端和协议版本后验证。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

回到[学习路径](./learning-path.md#r19)查看本章位置。
