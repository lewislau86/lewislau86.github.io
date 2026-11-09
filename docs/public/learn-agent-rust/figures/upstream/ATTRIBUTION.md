# Learn Agent by Rust：参考原图来源

本文件由 scripts/sync-learn-agent-rust-assets.py 生成。原图来自 Learn Claude Code 网站，按实际文件的 SHA-256 固定快照，未修改 SVG。

网站采用 20 章目录，关联仓库固定快照采用 17 章目录；两者编号及图中文字分别记录。原图中的 Python/Claude 接口、工具数量和效果不代表 Rust 版已经实现或验证。

上游：shareAI-lab/learn-claude-code；Copyright (c) 2024 shareAI Lab；MIT。

许可来源：https://raw.githubusercontent.com/shareAI-lab/learn-claude-code/7226f555d48900076eba126acf37c9ed5f002b5d/LICENSE

许可固定 commit：`7226f555d48900076eba126acf37c9ed5f002b5d`。完整许可保留于同目录 UPSTREAM-LICENSE.txt。网站图片以内容校验值标识版本，不宣称与许可 commit 的同名图片字节一致。

| 本地文件 | 原始章节 | 原图 | 日期 | SHA-256 |
| --- | --- | --- | --- | --- |
| `r01-agent-loop.svg` | [R01](https://learn.shareai.run/zh/s01/) | [source](https://learn.shareai.run/course-assets/s01_agent_loop/agent-loop.svg) | 2026-11-07 | `e4cfee663fad87ba2d5b2eac32404bf8b688d062a691bb8b9bf074a71ed600da` |
| `r02-tool-dispatch.svg` | [R02](https://learn.shareai.run/zh/s02/) | [source](https://learn.shareai.run/course-assets/s02_tool_use/tool-dispatch.svg) | 2026-11-07 | `feddc453fde1c7d043aef9b48cc5667491ec6eb5f4338301ad2334df6cb34b1c` |
| `r02-concurrency-comparison.svg` | [R02](https://learn.shareai.run/zh/s02/) | [source](https://learn.shareai.run/course-assets/s02_tool_use/concurrency-comparison.svg) | 2026-11-07 | `d4736b61a1903cc4bc7dd35184cfca51b2e0fe04e2516a72d8681ac2a52452b8` |
| `r03-permission-overview.svg` | [R03](https://learn.shareai.run/zh/s03/) | [source](https://learn.shareai.run/course-assets/s03_permission/permission-overview.svg) | 2026-11-07 | `3592616c6a1ee3ae721c2ce8328910cde93a7d60fb12a4586d72337cd845a247` |
| `r03-permission-pipeline.svg` | [R03](https://learn.shareai.run/zh/s03/) | [source](https://learn.shareai.run/course-assets/s03_permission/permission-pipeline.svg) | 2026-11-07 | `fc69aa4106f45d39734b47fa29d4e01b43aa9c1998d3a44f884bd8a888f1dbe3` |
| `r04-hooks-overview.svg` | [R04](https://learn.shareai.run/zh/s04/) | [source](https://learn.shareai.run/course-assets/s04_hooks/hooks-overview.svg) | 2026-11-07 | `9d1ce568380bac06456b170ef230750a3ff677618b227cc36e0c718ecd76f820` |
| `r05-todo-overview.svg` | [R05](https://learn.shareai.run/zh/s05/) | [source](https://learn.shareai.run/course-assets/s05_todo_write/todo-overview.svg) | 2026-11-07 | `81eae3cf51d1d0d7066417688a1634c0be0a24dfc6d0b088ae0dbc4b985675cf` |
| `r06-subagent-overview.svg` | [R06](https://learn.shareai.run/zh/s06/) | [source](https://learn.shareai.run/course-assets/s06_subagent/subagent-overview.svg) | 2026-11-07 | `6010d141e617d2885f9c54f2ce0ca8147b6aaefa96e1f10ab1950b19ac3ce166` |
| `r07-skill-overview.svg` | [R07](https://learn.shareai.run/zh/s07/) | [source](https://learn.shareai.run/course-assets/s07_skill_loading/skill-overview.svg) | 2026-11-07 | `7052e3da135ea1b81a847e117dd2c1e6b1516f73dafcc5da23132d3032986950` |
| `r08-compact-overview.svg` | [R08](https://learn.shareai.run/zh/s08/) | [source](https://learn.shareai.run/course-assets/s08_context_compact/compact-overview.svg) | 2026-11-07 | `7fa919db4b1153dc189e61d2d21fd0f995e1dbf7886cf6f9e339a4d61eedea7e` |
| `r08-compaction-layers.svg` | [R08](https://learn.shareai.run/zh/s08/) | [source](https://learn.shareai.run/course-assets/s08_context_compact/compaction-layers.svg) | 2026-11-07 | `0fda52e058163a6ed90888548a0af5f05d834d2445b6452c5111e4147acccda6` |
| `r08-micro-compact.svg` | [R08](https://learn.shareai.run/zh/s08/) | [source](https://learn.shareai.run/course-assets/s08_context_compact/micro-compact.svg) | 2026-11-07 | `b43575fc314ae5a7637152186a0cd15c2a8842d09d48448d0541e7a1f4219896` |
| `r08-layer1-budget.svg` | [R08](https://learn.shareai.run/zh/s08/) | [source](https://learn.shareai.run/course-assets/s08_context_compact/layer1-budget.svg) | 2026-11-07 | `c0283f9a4355651c5a4cad9053e816e1f6dca294087f33ba764b05d905e1d375` |
| `r08-auto-compact.svg` | [R08](https://learn.shareai.run/zh/s08/) | [source](https://learn.shareai.run/course-assets/s08_context_compact/auto-compact.svg) | 2026-11-07 | `657168aa53ce18791efff40a7c85cbd7a9fcc4369c7d212a56e036298893cf1f` |
| `r09-memory-overview.svg` | [R09](https://learn.shareai.run/zh/s09/) | [source](https://learn.shareai.run/course-assets/s09_memory/memory-overview.svg) | 2026-11-07 | `fb23bb3f41fe0468d643700c97354404ec6e8800b134769e2fd3546269f1527f` |
| `r09-memory-subsystems.svg` | [R09](https://learn.shareai.run/zh/s09/) | [source](https://learn.shareai.run/course-assets/s09_memory/memory-subsystems.svg) | 2026-11-07 | `d34a6f27a20e90a979f363f885b1a274875654a2867ea763e3da3ec19ab8cadb` |
| `r10-system-prompt-overview.svg` | [R10](https://learn.shareai.run/zh/s10/) | [source](https://learn.shareai.run/course-assets/s10_system_prompt/system-prompt-overview.svg) | 2026-11-07 | `9d744bc5a6213e93ee573d9a78801ea97de42aed6ee8d82eb850f011b223e48d` |
| `r11-error-recovery-overview.svg` | [R11](https://learn.shareai.run/zh/s11/) | [source](https://learn.shareai.run/course-assets/s11_error_recovery/error-recovery-overview.svg) | 2026-11-07 | `939a30535c9d159f4f54ddd527fcaaa338ed501ec8a477688ecf5fd26d7f781f` |
| `r12-task-system-overview.svg` | [R12](https://learn.shareai.run/zh/s12/) | [source](https://learn.shareai.run/course-assets/s12_task_system/task-system-overview.svg) | 2026-11-07 | `b34eaa9625e83405eac239afbf6b22a803788ec7ce7335f0ae26247ef8c9f241` |
| `r12-task-dag.svg` | [R12](https://learn.shareai.run/zh/s12/) | [source](https://learn.shareai.run/course-assets/s12_task_system/task-dag.svg) | 2026-11-07 | `888923ee0be24bfe390941a44c6fd03e09faa003b4b587cd827fcfdbd5e5e7b8` |
| `r13-background-tasks-overview.svg` | [R13](https://learn.shareai.run/zh/s13/) | [source](https://learn.shareai.run/course-assets/s13_background_tasks/background-tasks-overview.svg) | 2026-11-07 | `b98c3c9a1a56d668017f8eb81b65da0d5af47121465e21c3e43095edf2ade6a4` |
| `r14-cron-scheduler-overview.svg` | [R14](https://learn.shareai.run/zh/s14/) | [source](https://learn.shareai.run/course-assets/s14_cron_scheduler/cron-scheduler-overview.svg) | 2026-11-07 | `d645115f453e2336117ef8299defb7c9421807f1563780d4300f253d944bc472` |
| `r15-agent-teams-overview.svg` | [R15](https://learn.shareai.run/zh/s15/) | [source](https://learn.shareai.run/course-assets/s15_agent_teams/agent-teams-overview.svg) | 2026-11-07 | `8bf1a20084829220eba3b7127ad59eebdc4ee4e08ef8b3f795cb9d0a75910bc4` |
| `r15-team-topology.svg` | [R15](https://learn.shareai.run/zh/s15/) | [source](https://learn.shareai.run/course-assets/s15_agent_teams/team-topology.svg) | 2026-11-07 | `21376474372d182f88538bc16fa6917ea0763fdb04a5a87a9549c8a0d645c7fd` |
| `r16-team-protocols-overview.svg` | [R16](https://learn.shareai.run/zh/s16/) | [source](https://learn.shareai.run/course-assets/s16_team_protocols/team-protocols-overview.svg) | 2026-11-07 | `eda6c0249030e97eefb5cbb3ff57996ff9c0faca035a820ade14c3e9e1b22fd8` |
| `r17-autonomous-agents-overview.svg` | [R17](https://learn.shareai.run/zh/s17/) | [source](https://learn.shareai.run/course-assets/s17_autonomous_agents/autonomous-agents-overview.svg) | 2026-11-07 | `ed49098eb74b1b931fb03adf2c036487b31e7a18a196ba9e811e579af9a4d4a3` |
| `r18-worktree-overview.svg` | [R18](https://learn.shareai.run/zh/s18/) | [source](https://learn.shareai.run/course-assets/s18_worktree_isolation/worktree-overview.svg) | 2026-11-07 | `b99eb1c843eeff4d0e327ebc8f394893b5fa5c2639295d349fb18f087ce1922e` |
| `r19-mcp-architecture.svg` | [R19](https://learn.shareai.run/zh/s19/) | [source](https://learn.shareai.run/course-assets/s19_mcp_plugin/mcp-architecture.svg) | 2026-11-07 | `47a23a5722bf2162821caa3da3287b66aa6d987488cdac6bab879931ad90f565` |
| `r20-system-architecture.svg` | [R20](https://learn.shareai.run/zh/s20/) | [source](https://learn.shareai.run/course-assets/s20_comprehensive/system-architecture.svg) | 2026-11-07 | `1514df6a381ed681bea88f7de78cae621335f3b07ca2fdf44a8ea6888c2d8cda` |
