"""P04 figures: only numbers from verified real PostgreSQL drills."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/p04-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/production-readiness"
    for name, digest in evidence["files_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("P04 evidence stale; run verify-agent-production.py")
    rows = {r["scenario"]: r for r in evidence["scenarios"]}
    rollback, forward = rows["migration-rollback"], rows["migration-forward"]
    body = panel(40, 90, 880, 105, "升级前先具备兼容读路径", ["新 reader 能读格式 1 与 2；旧 reader 只接受格式 1"])
    body += arrow("M480 195 V231")
    body += panel(40, 239, 880, 105, "迁移事务：检查 → DDL → 数据 → schema", ["同一事务锁住配置行；执行 SQL 后、提交前注入失败"])
    body += arrow("M280 344 V382 H240 V402") + arrow("M680 344 V382 H720 V402")
    body += panel(40, 410, 400, 145, "失败：事务回滚", ["schema = {} · 旧会话 = {}".format(rollback["schema"], rollback["old_sessions"]),
                  "workflow 列 = {}".format(rollback["workflow_columns"])], "#b45309")
    body += panel(520, 410, 400, 145, "成功：格式切换", ["schema = {} · 新会话 = {}".format(forward["schema"], forward["migrated_sessions"]),
                  "spent = {} · status = {}".format(forward["spent"], forward["status"])], "#0f766e")
    body += text(480, 598, "成功后旧 reader 明确拒绝；未验证在线迁移或反向迁移。", 18, "#475569")
    save("p04-migration-boundary.svg", "旧会话升级，先验证失败后还剩什么", "真实 PostgreSQL 迁移事务失败后结构和数据回滚，成功后保留推进位置和累计预算。", 635, body)

    load, drain = rows["load-burst"], rows["drain-and-finish"]
    body = panel(40, 90, 880, 105, "{} 个独立进程并发提交".format(load["attempted"]), ["所有准入回复后再结束任务；容量 = {}".format(load["capacity"])])
    body += arrow("M480 195 V231")
    body += panel(40, 239, 880, 105, "锁配置行，原子预留名额", ["读取容量 + 插入作业 + active 增加，在同一事务内完成"])
    body += arrow("M280 344 V382 H240 V402") + arrow("M680 344 V382 H720 V402")
    body += panel(40, 410, 400, 115, "接收 = {}".format(load["accepted"]), ["active = {}，容量未超发".format(load["active"])], "#0f766e")
    body += panel(520, 410, 400, 115, "拒绝 = {}".format(load["rejected"]), ["返回 Overloaded，保留拒绝计数"], "#b45309")
    body += text(480, 576, "停止接单后排空：active = {} · finished = {}".format(drain["active"], drain["finished"]), 22, "#0f766e", True)
    body += text(480, 617, "这是单轮容量边界演练，没有测模型延迟或长期吞吐。", 18, "#475569")
    save("p04-admission-evidence.svg", "容量满时，拒绝也要留下证据", "接收、拒绝和排空计数来自十二个独立 Rust 客户端并发提交的实际结果。", 655, body)

    backup, restored = rows["backup-snapshot"], rows["restore-separate-cluster"]
    body = panel(40, 90, 400, 140, "源集群：阻断接单后备份", ["active = {} · recovery = true".format(backup["in_flight"]),
                  "{} 会话 / {} 完成作业 / {} 结果".format(backup["sessions"], backup["completed_jobs"], backup["results"])])
    body += arrow("M440 160 H510")
    body += panel(520, 90, 400, 140, "独立目标：pg_restore", ["先拒绝损坏归档，再恢复正确备份", "结构、数据和预算逐值核对"], "#0f766e")
    body += arrow("M240 230 V266")
    body += panel(40, 274, 400, 140, "备份之后：又提交一次", ["随后源数据库停止", "目标中缺少 {} 条提交".format(restored["missing_post_backup_commits"])], "#b45309")
    body += arrow("M720 230 V266")
    body += panel(520, 274, 400, 140, "目标先不接单", ["recovery 仍为 true", "完成本地核对后由操作员放行"], "#0f766e")
    body += text(480, 469, "恢复基线一致 ≠ 没有数据缺口；外部业务需要另行对账。", 20, "#b45309", True)
    body += text(480, 511, "本地恢复步骤计时不包含故障发现、环境准备与流量切换。", 18, "#475569")
    save("p04-restore-boundary.svg", "恢复到另一个集群，再说明丢了什么", "源库停止后将备份恢复到另一个 PostgreSQL 实例，核对逻辑基线并报告备份后的一条缺失提交。", 550, body)
