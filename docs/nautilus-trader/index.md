---
title: nautilus_trader 源码笔记
description: 从 Rust 源码读 nautilus_trader：适配器边界、数据与执行引擎、实盘节点，以及为它接入富途券商的实践记录。
---

# nautilus_trader 源码笔记

**从 Rust 源码读一个量化交易平台**

[nautilus_trader](https://github.com/nautechsystems/nautilus_trader) 是一个开源的事件驱动交易平台：同一套策略代码既能回测，也能接实盘。它的核心已经大部分用 Rust 重写，Python 层通过 PyO3 调用 Rust。本笔记先读 Rust 源码，以“给它接入一个新券商（富途）”为主线：要接一个券商，就得弄清楚平台和外部世界之间的那条边界在哪里、边界两侧各自负责什么。

::: tip 阅读约定
源码以 GitHub 上 `develop` 分支为准，文中引用的文件路径、trait 和函数名都在 2026-11-13 核对过。项目更新很快，读到时如有出入，以仓库为准。
:::

## 笔记目录

- [给 nautilus_trader 加一个券商：富途适配器怎么做](./futu-adapter.md)（已成文）：适配器的接口边界、应该参照哪个现有适配器、富途 OpenD 协议要点、两边概念的对照表，以及从协议层到实盘节点的里程碑

规划中（顺序可能调整）：

- `DataClient` 与 `ExecutionClient`：适配器 trait 逐个方法读
- 从命令到事件：一笔订单在 `ExecutionEngine`、`ExecutionClientCore` 和适配器之间怎样流转
- 对账：`generate_mass_status` 与重启后的状态恢复
- `LiveNode`：工厂、配置与运行时任务（`TaskGroup`）
- `nautilus_network`：HTTP、WebSocket、Socket 客户端与限流、重连
- 富途适配器实现记录：协议层（M0）、标的（M1）、行情（M2）、模拟盘交易（M3）
