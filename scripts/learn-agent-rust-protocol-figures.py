"""R16 protocol diagrams from checked source and real Tokio/file evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r16-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/team-protocols"
    for name, digest in evidence["source_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Stale R16 evidence; run verify-agent-protocols.py")
    rows = {r["scenario"]: r for r in evidence["scenarios"]}
    request = rows["wrong-sender"]["before_cleanup"]["requests"]["plan-1"]
    body = panel(40, 85, 880, 112, "① Core 提交 PlanRequest", ["request_id = plan-1", "Endpoint 绑定发送者；正文只携带业务字段"], "#2563eb")
    body += arrow("M480 197 V239")
    body += panel(40, 247, 880, 144, "② 请求表保存预期关系", ["kind = {} · requester = {} · responder = {}".format(request["kind"], request["requester"], request["responder"]), "deadline = {} tick · 原计划快照 + SHA-256".format(request["deadline"]), "回复必须匹配 ID、类型、双方身份与 Pending"], "#0f766e")
    body += arrow("M270 391 V433") + arrow("M690 391 V433")
    body += panel(40, 441, 420, 112, "Lead → Core", ["有效 PlanResponse", "Approve / Reject 决定状态"], "#0f766e")
    body += panel(500, 441, 420, 112, "Config → Core", [rows["wrong-sender"]["errors"][0], "plan-1 仍为 {}".format(request["status"])], "#b91c1c")
    body += text(480, 603, "Progress 仅记日志；正文中的“同意”不会进入审批分支。", 19, "#475569")
    save("r16-request-correlation.svg", "同意之前，先确定谁在回复哪次请求", "请求表固定原申请者与预期回复者，config 伪造批准被拒绝，计划保持 pending。", 637, body)

    revised = rows["resubmit"]
    q = revised["before_cleanup"]["requests"]
    body = panel(40, 85, 420, 112, "plan-1 · revision 1", ["Pending → {}".format(q["plan-1"]["status"]), "保留反馈；旧 ID 不能覆盖"], "#b45309")
    body += arrow("M460 141 H492")
    body += panel(500, 85, 420, 112, "plan-2 · revision 2", ["重新提交 → Approved", "冻结 revision / path / content"], "#2563eb")
    body += arrow("M710 197 V239 H480 V269")
    body += panel(40, 277, 880, 144, "执行入口逐项检查", ["原申请者 + Approved + now < deadline", "计划 SHA-256 一致 + 工具 ACL 独立允许", "仅 Core 创建 review.txt · create_new 保护已有路径"], "#0f766e")
    body += arrow("M480 421 V463")
    body += panel(40, 471, 880, 112, "Executing → Completed / Failed", ["修订场景实际写入：{} 次".format(revised["after_cleanup"]["writes"]), "完成后不能重放；I/O 失败记 Failed，不自动重试"], "#0f766e")
    body += text(480, 629, "摘要用于本实现的内容一致性；权限仍由执行端决定。", 19, "#475569")
    save("r16-plan-gate.svg", "批准具体内容，再消费一次执行机会", "被退回的旧请求保留，修订计划以新 ID 重新审批；执行端检查身份、期限、原计划和权限。", 663, body)

    full = rows["mailbox-full"]
    body = panel(40, 85, 880, 112, "① clone 请求表 → 验证候选状态", ["候选：建立 stop-core，冻结成员，撤销未执行批准", "权威表此时还保持原状"], "#2563eb")
    body += arrow("M270 197 V239") + arrow("M690 197 V239")
    body += panel(40, 247, 420, 144, "② 邮箱已满 · try_send 失败", [full["errors"][0], "丢弃候选；不占关闭 ID", "不冻结成员、不撤销原批准"], "#b91c1c")
    body += panel(500, 247, 420, 144, "② 邮箱有空间 · try_send 成功", ["消息实际入队", "随后提交候选表", "本地锁内无 await"], "#0f766e")
    body += arrow("M270 391 V433 H480 V463")
    body += panel(40, 471, 880, 112, "③ 满邮箱实验：释放空间，再用原 ID 发送", ["回滚检查：{} · 计划实际写入：{} 次".format(str(full["observations"]["failed_send_rolled_back"]).lower(), full["after_cleanup"]["writes"]), "stop-core 最终收到合法关闭回复"], "#0f766e")
    body += text(480, 629, "这是进程内投递与状态边界；内存候选不提供崩溃恢复。", 19, "#475569")
    save("r16-delivery-commit.svg", "投递失败，请求表也保留原状", "满邮箱时丢弃候选状态，释放空间后可以用相同关闭 ID 重投。", 663, body)

    body = text(200, 96, "实验场景", 20, "#2563eb", True)
    body += text(525, 96, "关闭记录 · 清理前 → 后", 20, "#2563eb", True)
    body += text(810, 96, "Core join", 20, "#0f766e", True)
    for index, name in enumerate(["normal", "shutdown-rejected", "shutdown-timeout", "shutdown-panic", "ack-without-exit", "abort-fallback"]):
        row = rows[name]
        y = 122 + index * 66
        q0 = row["before_cleanup"]["requests"]["stop-core"]["status"]
        q1 = row["after_cleanup"]["requests"]["stop-core"]["status"]
        body += '<rect x="40" y="{}" width="880" height="54" rx="8" fill="#fff" stroke="#cbd5e1"/>'.format(y)
        body += text(200, y + 33, name, 18)
        body += text(525, y + 33, "{} → {}".format(q0, q1), 18, "#475569")
        body += text(810, y + 33, row["joined"][0]["outcome"], 18, "#b45309" if row["joined"][0]["aborted"] else "#0f766e", True)
    body += panel(40, 552, 880, 144, "统一收尾：watch 取消 → 等待 JoinHandle", ["忽略协作取消的异步任务：100ms 后 abort，继续 await", "只有 abort-fallback 发生强制取消；panic 单独识别", "以上场景均 joined=2、active=0，随后删除临时目录"], "#0f766e")
    body += text(480, 739, "协议决定与资源退出分别记录，Approved 不代替 join。", 19, "#475569")
    save("r16-shutdown-join.svg", "队友同意退出之后，还要等到任务结束", "六个场景分别记录关闭协议与真实回收结果，批准但存活和 panic 无回复需要独立处理。", 774, body)
