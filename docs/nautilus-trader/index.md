---
title: 深入理解 NautilusTrader
description: 从源码读开源量化交易平台 NautilusTrader：先看全景架构（分层、源码目录、核心数据结构），再读 Rust 核心（运行时、增加一个券商、其他需要重点理解的主题），最后读 Python 层。
---

# 深入理解 NautilusTrader

**从源码读一个量化交易平台**

[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) 是一个开源的事件驱动交易平台：同一套策略代码既能回测，也能接实盘。它的核心已经全部用 Rust 实现，Python 层通过 PyO3 调用 Rust。本书先读 Rust 部分，再读 Python 部分。Rust 部分以“给它接入一个新券商（富途）”为主线：要接一个券商，就得弄清楚平台和外部世界之间的边界在哪里、边界两侧各自负责什么。

::: tip 阅读约定
源码以 GitHub 上 `develop` 分支为准，文中引用的文件路径、trait 和函数名都在 2026-11 核对过。项目更新很快，读到时如有出入，以仓库为准。网上很多资料讲的是旧的 Cython 版本（v1，现在在 `develop_v1` 分支），读的时候要分清。
:::

## 导读

- [第 0 章 · NautilusTrader 架构](./nautilus-architecture.md)：一个节点的四层（Python、PyO3、节点外壳、内核）和两种线程；Rust 24 个 crate 的七层分层与每个 crate 的目录；Python 包怎样从 `_libnautilus` 转出、哪些是纯 Python；Rust 核心数据结构（定点数、标识符、行情、订单簿、订单、仓位、`Cache`、`MessageBus`）；这些结构投影到 Python 后的三种关系和快照语义

## 动手准备

- [从零编译：Rust 与 Python 两部分](./build-from-source.md)：从一台干净的 macOS 或 Ubuntu 开始，装工具链、取源码；Rust 部分用 `cargo` 跑通 `engine-ema-cross` 回测示例和单元测试，Python 部分用 `make build-debug` 编出 `_libnautilus` 并跑通一个 Python 回测；解释锁定的工具链、依赖冷却期检查、`PYO3_PYTHON` 等环境变量和各种构建 profile

## 第一部分 · Rust 核心

- [第 1 章 · 整体架构](./architecture.md)：设计理念（单线程核心、回测实盘同构、crash-only），crate 分层与依赖图，`NautilusKernel`，线程局部的消息总线，一条报价和一笔订单的完整路径，组件与策略，回测、沙盒、实盘三种模式的异同
- [第 2 章 · 增加一个券商：以富途为例](./futu-adapter.md)：适配器要实现的 trait，富途适配器在 crate 依赖图和运行时里的位置，为什么参照 IB 适配器，富途 OpenD 协议要点，两边概念对照，Python 绑定的三条路线（PyO3 注册表、纯 Python 客户端、独立扩展），五个实现里程碑
- [第 3 章 · 其他需要重点理解的主题](./core-topics.md)：定点数值类型、时钟与两种时间戳、订单状态机与事件溯源、缓存、并发模型、风控与订单仿真、对账、数据与持久化、PyO3 边界、测试与错误处理

## 第二部分 · Python 层

待定。
