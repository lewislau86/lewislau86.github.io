---
editLink: false
---

# 11 从教学服务器走向 Redis

[上一章](/mini-redis/10-shutdown-and-tests.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/12-exercises-and-index.md)

现在你已经能解释一个内存键值服务：解析网络协议、分发命令、维护共享状态、处理过期与订阅。接下来把它放到 Redis 的架构地图里，明确已经学到哪些共通问题，还有哪些部件不在这个仓库中。

## 单机请求链路：共通的是职责

两者都需要完成“连接管理 → 读取字节 → 识别命令 → 访问数据 → 返回结果”。mini-redis 用 Tokio 任务与 `Arc<Mutex<State>>` 组织这些职责；不要把它当作真正 Redis 的线程与数据结构实现。

理解 Redis 的经典架构时，可以从事件循环入手：将 socket 就绪事件和定时事件交给相应处理逻辑；命令执行的顺序组织让共享状态管理更集中。但“命令主要顺序执行”不等于“整个 Redis 进程永远只有一个线程”，也不能推导 I/O、持久化后台工作都在同一个执行单元。

官方[事件库文章](https://redis.io/docs/latest/operate/oss_and_stack/reference/internals/internals-rediseventlib/)适合学习事件驱动思想，但页面明确说明它是早期历史材料，不必然反映最新版实现。本章讲基础职责与概念，不替代针对指定 Redis 版本的 C 源码分析。

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

这些是面向使用者的逻辑类型，并不意味着底层永远固定采用某一种编码。更多类型和具体行为查[官方数据类型概览](https://redis.io/docs/latest/develop/data-types/)。本仓库没有这些对象编码、命令和内存布局，不能用一个 HashMap 表替代其学习。

真正 Redis 的 key 和 String 值可以是二进制安全的内容；本地命令解析把 key 转为 Rust String，要求合法 UTF-8。这也是兼容范围的一部分。

## 过期与淘汰回答不同问题

TTL 说明业务允许一个键存活多久；内存淘汰说明达到内存限制时，应该移除哪些键或者拒绝写入。尚未过期的缓存也可能被淘汰；配置了 TTL 不代表内存就有硬上界。

本地只有后台过期清理，没有 `maxmemory` 与相应淘汰策略。Redis 的[内存淘汰文档](https://redis.io/docs/latest/develop/reference/eviction/)描述了按策略选择键、近似 LRU/LFU 等机制；这些不能从 BTreeSet 过期索引直接推导。

例如商品缓存设置 TTL 30 分钟，只解决数据多旧可以接受；如果 5 分钟内写入太多商品，仍需容量控制。两个参数分别约束时间与空间。

## 持久化：重启后从哪里恢复

本地重启就丢数据。Redis 常见的两种持久化路径是：RDB 保存某个时刻的数据快照，AOF 记录用于恢复的写操作，并通过重写控制日志体积。快照恢复点、AOF 刷盘策略会影响故障时可能丢失的数据与运行成本。

考虑 `SET order:7 paid` 已返回成功后机器掉电：能否恢复这条写入取决于实际持久化方式、刷盘策略与故障时点。不要把“响应成功”直接等同于“已经耐久写盘”。也不要把文件落盘与备份恢复策略混为一谈。参见[官方持久化说明](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)。

这里学到的 Db::set 只是修改内存状态，没有任何 WAL/AOF 写入点。若想加持久化，首先需要定义成功响应代表何种保证，再决定日志写入、刷盘与内存修改的顺序。

## 复制：让另一台机器拥有数据副本

复制让 primary 的数据传播给 replica，承担冗余和读扩展等职责。Redis 基础复制通常是异步的，因此主节点已确认的写入可能尚未到达副本；发生故障切换时不能自动推导零丢失。

初次同步/差距过大时需要较完整的数据同步，条件允许时可通过复制历史续传。它不是把本地 Db 的 Arc clone 到另一台机器：Arc 只能共享同一进程中的资源，跨机器需要协议、偏移记录、重连和一致性约定。参见[官方复制说明](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/)。

复制也不同于备份：误删可能同样传播到副本，而备份需要保存可回到过去的恢复点。

## Sentinel 与 Cluster 各自解决什么

Sentinel 关注非 Cluster 部署中主从节点的监测、故障切换以及帮助客户端发现当前主节点。它不负责把所有 key 自动分摊到多个独立主节点。详见 [Sentinel 文档](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)。

Cluster 使用 16384 个哈希槽组织 key 的分片归属，节点管理槽并承担故障处理，客户端需要理解重定向。跨槽多键操作存在限制，设计 key 与 hash tag 时需要考虑共同访问模式。参见 [Cluster 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)。

```text
单机：        Client → 一个 Redis 节点

复制：        Client → Primary → Replica
                                  数据副本

Sentinel：    Sentinel 监测主从、协调故障切换
              客户端发现当前 Primary

Cluster：     Client → 持有所需槽的节点 A / B / C
                       每个主节点还可配副本
```

这张图描述职责，不代表所有部署拓扑或完整故障协议。mini-redis 未实现其中任何跨进程数据复制与分片。

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

一个商品服务既想减少数据库查询，又要求支付记录在故障后不丢。能否只凭“Redis 很快”给两者配置相同的存储策略？

<details>
<summary>参考答案</summary>

不能。可重建缓存首先关心命中率、TTL、容量和源数据；支付记录关心耐久性、故障时的一致性和恢复能力。应先定义数据责任与故障保证，再选择相应存储与部署方案。这个教学服务器只帮助理解请求与内存状态路径，没有为关键记录提供耐久保证。

</details>
