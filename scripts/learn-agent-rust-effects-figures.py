"""P02 diagrams derived from checked Rust source and actual two-database runs."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/p02-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/side-effect-reliability"
    for name, digest in evidence["source_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Stale P02 evidence; run verify-agent-effects.py")
    rows = {r["scenario"]: r for r in evidence["scenarios"]}

    body = panel(40, 85, 880, 112, "① 客户端事务 · client.sqlite", ["actions + outbox 一起提交", "先保存稳定 operation ID 与冻结参数"], "#2563eb")
    body += arrow("M480 197 V239")
    body += panel(40, 247, 880, 112, "② 服务端事务 · provider.sqlite", ["tickets + keys + receipt 一起提交", "这里退出：外部已成功，客户端仍可能 unknown"], "#0f766e")
    body += arrow("M480 359 V401")
    body += panel(40, 409, 880, 112, "③ 客户端事务 · client.sqlite", ["先保存合法回执为 acked", "checkpoints + actions + outbox 一起完成"], "#2563eb")
    body += text(480, 568, "两份数据库独立提交；本地事务没有覆盖外部工单。", 20, "#b45309", True)
    body += text(480, 608, "图示三个阶段；unknown 标记与 acked 保存另有本地提交。", 17, "#475569")
    save("p02-commit-windows.svg", "一次业务操作，三个阶段分别提交", "客户端与服务端位于独立进程，各自写入数据库。服务端提交与本地确认之间存在未知结果窗口；发送前标记与回执保存还有独立的本地提交。", 642, body)

    replay = rows["response-lost-replay"]["provider"]
    conflict = rows["provider-conflict"]["provider"]
    fresh = rows["new-operation-id"]["provider"]
    body = panel(40, 85, 880, 112, "身份 = tenant + operation_id", ["冻结 title，计算完整请求摘要", "客户意图跨重试保持；不使用新调用 ID 代替"], "#2563eb")
    for x in [180, 480, 780]:
        body += arrow("M{} 197 V239".format(x))
    body += panel(40, 247, 270, 174, "同键 · 同参数", ["返回原回执", "apply 提交：{}".format(replay["committed_apply_calls"]), "工单：{}".format(replay["ticket_count"])], "#0f766e")
    body += panel(345, 247, 270, 174, "同键 · 参数变化", ["idempotency_conflict", "拒绝第二份内容", "工单：{}".format(conflict["ticket_count"])], "#b91c1c")
    body += panel(650, 247, 270, 174, "新键 · 相同标题", ["独立业务意图", "创建另一张工单", "工单：{}".format(fresh["ticket_count"])], "#b45309")
    body += panel(40, 475, 880, 112, "并发也要在服务端保护", ["{} 个独立 provider 进程 → {} 张工单".format(rows["concurrent-provider"]["provider"]["committed_apply_calls"], rows["concurrent-provider"]["provider"]["ticket_count"]), "事务内检查键、创建工单与保存回执"], "#0f766e")
    body += text(480, 631, "数量来自真实数据库；键作用域与保留期属于接口契约。", 18, "#475569")
    save("p02-idempotency-scope.svg", "幂等识别同一意图，也拒绝身份被复用", "相同键和参数的两次提交只创建一张工单；同键不同参数冲突；不同操作键创建两张。", 665, body)

    body = panel(40, 85, 420, 112, "pending", ["已保存意图，尚未尝试发送"], "#64748b")
    body += arrow("M460 141 H492")
    body += panel(500, 85, 420, 112, "unknown", ["发送前落盘；累计 attempts +1"], "#b45309")
    body += arrow("M710 197 V239")
    body += panel(500, 247, 420, 132, "acked", ["验证身份、参数与摘要", "合法回执单独持久化"], "#0f766e")
    body += arrow("M500 313 H468")
    body += panel(40, 247, 420, 132, "completed", ["本地检查点事务已提交", "重启后无需再发 apply"], "#2563eb")
    body += panel(40, 445, 880, 144, "unknown 的恢复选择", ["有效幂等窗口内：原键重放，或先按业务引用查询", "唯一匹配：保存回执；无幂等且查不到：保持未知", "多条结果 / 查询不完整 / 不可用：停止自动重发"], "#b45309")
    body += text(480, 635, "Outbox 保存发送意图；外部去重与对账分别处理业务结果。", 18, "#475569")
    save("p02-outbox-recovery.svg", "未知结果需要保留，也需要可恢复的入口", "Outbox 从 pending 到 unknown，再由合法回执进入 acked 与 completed。未知结果通过幂等重放或对账处理。", 668, body)

    unsafe = rows["expired-key-unsafe"]["provider"]["ticket_count"]
    stopped = rows["expired-client-stop"]
    reconciled = rows["expired-reconcile"]
    body = panel(40, 85, 880, 112, "幂等缓存只在保留期内保护原操作", ["服务保留首次成功后的 100 tick；客户端从准备时起限制 100 tick", "now ≥ safe_until：客户端停止发送；tick 是实验逻辑输入"], "#b45309")
    for x in [180, 480, 780]:
        body += arrow("M{} 197 V239".format(x))
    body += panel(40, 247, 270, 174, "过期后直接重放", ["旧键已经删除", "重复创建真实业务行", "工单：{}".format(unsafe)], "#b91c1c")
    body += panel(345, 247, 270, 174, "客户端期限保护", ["retry_window_expired", "保持 unknown", "工单：{}".format(stopped["provider"]["ticket_count"])], "#b45309")
    body += panel(650, 247, 270, 174, "按业务引用对账", ["从工单表找回原回执", "不增加业务工单", "检查点：{}".format(reconciled["local"]["checkpoints"])], "#0f766e")
    body += text(480, 478, "删除缓存键没有删除工单；对账依赖服务保留客户引用。", 19, "#475569")
    body += text(480, 518, "真实服务的保留期、查询可见性与迟到请求需要单独核实。", 18, "#475569")
    save("p02-retention-boundary.svg", "缓存到期，重放保证也有边界", "幂等缓存到期后直接重放生成两张工单；客户端停止发送或按业务引用对账，仍保留一张工单。", 555, body)
