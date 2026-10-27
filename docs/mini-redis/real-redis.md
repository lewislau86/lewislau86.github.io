---
title: "第 11 章：从教学服务器走向 Redis"
description: "持久化、复制、集群分别解决什么问题？"
pageClass: mini-redis-course
---

# 第 11 章：从教学服务器走向 Redis

[课程总览](/mini-redis/index.md) · [上一章](/mini-redis/shutdown-and-tests.md) · [下一章](/mini-redis/exercises-and-index.md)

::: tip 本章学习目标
**要解决的问题：** 持久化、复制、集群分别解决什么问题？

**顺路学到的 Rust：** 区分语言实现与数据库架构
:::

<MiniRedisMap active="real-redis" />

现在你已经能解释一个内存键值服务：解析网络协议、分发命令、维护共享状态、处理过期与订阅。接下来把它放到 Redis 的架构地图里，明确已经学到哪些共通问题，还有哪些部件不在这个仓库中。

## 单机请求链路：共通的是职责

两者都需要完成“连接管理 → 读取字节 → 识别命令 → 访问数据 → 返回结果”。mini-redis 用 Tokio 任务与 `Arc<Mutex<State>>` 组织这些职责；这是教学用的组织方式，真正 Redis 的线程模型与数据结构另有一套实现。

理解 Redis 的经典架构时，可以从事件循环入手：将 socket 就绪事件和定时事件交给相应处理逻辑；命令执行的顺序组织让共享状态管理更集中。

官方[事件库文章](https://redis.io/docs/latest/operate/oss_and_stack/reference/internals/internals-rediseventlib/)适合学习事件驱动思想，页面也明确说明它是早期历史材料，最新版实现可能已有变化。本章讲基础职责与概念；某个具体 Redis 版本怎样实现，要对照该版本的 C 源码分析。

## 键空间之外，还有值类型

mini-redis 的每个值就是 Bytes。真正 Redis 根据命令提供不同的数据类型与操作语义。例如：

| 业务需要 | 常见类型 | 关键操作思想 |
| --- | --- | --- |
| 缓存页面或对象编码 | String | 取整块值、覆盖值、计数 |
| 用户的一组字段 | Hash | 按字段访问一个对象 |
| 有顺序的元素序列 | List | 从两端推入/取出 |
| 唯一成员集合 | Set | 去重、集合运算 |
| 排行榜 | Sorted Set | 成员关联分数，按分数排序 |
| 追加记录与消费进度 | Stream | 记录 ID、消费组等机制 |

这些是面向使用者的逻辑类型，同一种逻辑类型在底层可以采用不同的编码。更多类型和具体行为查[官方数据类型概览](https://redis.io/docs/latest/develop/data-types/)。本仓库没有这些对象编码、命令和内存布局，这部分需要在 HashMap 之外另行学习。

真正 Redis 的 key 和 String 值可以是二进制安全的内容；本地命令解析把 key 转为 Rust String，要求合法 UTF-8。这也是兼容范围的一部分。

## 过期与淘汰回答不同问题

TTL 说明业务允许一个键存活多久；内存淘汰说明达到内存限制时，应该移除哪些键或者拒绝写入。尚未过期的缓存也可能被淘汰。

本地只有后台过期清理，没有 `maxmemory` 与相应淘汰策略。Redis 的[内存淘汰文档](https://redis.io/docs/latest/develop/reference/eviction/)描述了按策略选择键、近似 LRU/LFU 等机制；它们是独立于 BTreeSet 过期索引的另一套机制。

例如商品缓存设置 TTL 30 分钟，只解决数据多旧可以接受；如果 5 分钟内写入太多商品，仍需容量控制。两个参数分别约束时间与空间。

## 持久化：重启后从哪里恢复

本地重启就丢数据。Redis 常见的两种持久化路径是：RDB 保存某个时刻的数据快照，AOF 记录用于恢复的写操作，并通过重写控制日志体积。快照恢复点、AOF 刷盘策略会影响故障时可能丢失的数据与运行成本。

考虑 `SET order:7 paid` 已返回成功后机器掉电：能否恢复这条写入取决于实际持久化方式、刷盘策略与故障时点。文件落盘与备份恢复策略也是两件事。参见[官方持久化说明](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)。

这里学到的 Db::set 只是修改内存状态，没有任何 WAL/AOF 写入点。若想加持久化，首先需要定义成功响应代表何种保证，再决定日志写入、刷盘与内存修改的顺序。

## 复制：让另一台机器拥有数据副本

复制让 primary 的数据传播给 replica，承担冗余和读扩展等职责。Redis 基础复制通常是异步的，因此主节点已确认的写入可能尚未到达副本；发生故障切换时，这部分写入可能丢失。

初次同步/差距过大时需要较完整的数据同步，条件允许时可通过复制历史续传。Arc 只在同一进程内共享资源，跨机器的复制依靠协议、偏移记录、重连和一致性约定。参见[官方复制说明](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/)。

误删同样会传播到副本；备份的职责是保存可回到过去的恢复点。

## Sentinel 与 Cluster 各自解决什么

Sentinel 关注非 Cluster 部署中主从节点的监测、故障切换以及帮助客户端发现当前主节点；把 key 分摊到多个独立主节点是 Cluster 的职责。详见 [Sentinel 文档](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)。

Cluster 使用 16384 个哈希槽组织 key 的分片归属，节点管理槽并承担故障处理，客户端需要理解重定向。跨槽多键操作存在限制，设计 key 与 hash tag 时需要考虑共同访问模式。参见 [Cluster 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)。

![单机、主从复制、Sentinel 和 Cluster 四种部署形态的结构对比](/mini-redis/figures/redis-topologies.svg)

这张图只描述各自的职责，实际部署拓扑和完整故障协议更复杂。mini-redis 未实现其中任何跨进程数据复制与分片。

## 把学习边界放在同一张表里

| 主题 | 本地代码已展示 | 继续学习真正 Redis 时要补的内容 |
| --- | --- | --- |
| 网络 | TCP、读缓冲、RESP 子集 | 完整协议、输入限制、连接管理 |
| 执行 | Tokio 每连接任务、锁内状态操作 | 指定版本事件循环与执行路径 |
| 数据 | HashMap + Bytes | 多数据类型、内部编码、命令复杂度 |
| 时间与空间 | 后台 TTL 清理 | 访问过期、主动过期、容量淘汰 |
| 消息 | 有界 broadcast、订阅连接状态 | Redis Pub/Sub 与 Streams 的不同保证 |
| 故障恢复 | 本进程优雅退出 | 持久化、复制、备份与恢复演练 |
| 高可用与扩展 | 无 | Sentinel、Cluster、客户端重定向 |
| 多操作一致性 | 单次锁内修改 | 事务、脚本、原子命令及其边界 |

::: warning 常见误区
- **mini-redis 的结构不是 Redis 的实现。** Tokio 任务和 `Arc<Mutex<State>>` 是教学组织方式，Redis 的线程模型、对象编码和内存布局另有设计。
- **命令顺序执行不等于整个进程只有一个线程。** 也不能由此推导 I/O、持久化等后台工作都在同一个执行单元。
- **配置 TTL 不等于内存有上界。** TTL 约束时间，容量要靠 `maxmemory` 与淘汰策略控制。
- **响应成功不等于已经耐久写盘。** 能否恢复取决于持久化方式、刷盘策略与故障时点。
- **有了复制不等于零丢失，也不等于有了备份。** 异步复制可能丢失已确认的写入，误删也会同步到副本。
:::

## 本章结论 {#summary}

mini-redis 与 Redis 共通的是单机请求链路的职责：连接管理、读取字节、识别命令、访问数据、返回结果。真正的 Redis 在此之上还提供多种值类型、容量淘汰、RDB/AOF 持久化、主从复制，以及 Sentinel 的故障切换和 Cluster 的哈希槽分片。

这些能力各自回答一个独立问题：TTL 管时间，淘汰管空间，持久化管重启恢复，复制管冗余副本，备份管回到过去，Cluster 管分片扩展。为一份数据选择方案时，先写清它需要哪种保证，再对应到相应机制。

## 检查理解

1. 一个商品服务既想减少数据库查询，又要求支付记录在故障后不丢。能否只凭“Redis 很快”给两者配置相同的存储策略？

   <details><summary>参考答案</summary>

   不能。可重建缓存首先关心命中率、TTL、容量和源数据；支付记录关心耐久性、故障时的一致性和恢复能力。应先定义数据责任与故障保证，再选择相应存储与部署方案。这个教学服务器只帮助理解请求与内存状态路径，没有为关键记录提供耐久保证。

   </details>

2. 商品缓存都设置了 30 分钟 TTL，为什么仍可能需要配置内存淘汰？

   <details><summary>参考答案</summary>

   TTL 只约束数据能存活多久；如果短时间内写入大量商品，在任何键到期之前内存就可能耗尽。达到内存上限时移除哪些键或者拒绝写入，由 `maxmemory` 和淘汰策略决定，尚未过期的键也可能被淘汰。

   </details>

3. 在 mini-redis 中 `SET order:7 paid` 返回 OK 后进程重启，这条数据还在吗？换成 Redis 呢？

   <details><summary>参考答案</summary>

   mini-redis 中不在：Db::set 只修改内存状态，没有 WAL/AOF 写入点，重启就丢数据。Redis 中能否恢复取决于是否启用 RDB 或 AOF、AOF 的刷盘策略以及故障发生的时点。

   </details>

4. Sentinel 和 Cluster 分别解决什么问题？

   <details><summary>参考答案</summary>

   Sentinel 用于非 Cluster 部署，负责监测主从节点、执行故障切换并帮助客户端发现当前主节点。Cluster 用 16384 个哈希槽把 key 分片到多个主节点，客户端需要处理重定向，跨槽多键操作受限。

   </details>

下一章把前面学到的内容变成动手练习和知识索引：[第 12 章：动手练习与知识索引](/mini-redis/exercises-and-index.md)。
