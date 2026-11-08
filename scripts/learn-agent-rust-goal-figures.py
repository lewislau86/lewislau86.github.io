"""P05 diagrams from verified goal-control traces and source hashes."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/p05-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/workflow-and-goal-control"
    for name, digest in evidence["files_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("P05 evidence stale; run verify-agent-goals.py")
    rows = {row["scenario"]: row for row in evidence["scenarios"]}
    body = panel(40, 90, 880, 100, "固定流程：准备数量合同与预检查", ["冻结源数据、期望值与运行上限；已有合格结果可直接完成"])
    body += arrow("M240 190 V244")
    body += panel(40, 252, 400, 145, "内部 episode", ["提议读取、写入或返回", "程序检查策略后执行"], "#0f766e")
    body += arrow("M440 324 H505")
    body += panel(520, 252, 400, 145, "固定验收", ["重读真实文件，核对合同", "答案不参与自我评分"])
    body += arrow("M720 397 V454 H240 V485")
    body += arrow("M720 454 V485")
    body += panel(40, 493, 400, 110, "完成", ["正常返回 + 产物达标"], "#0f766e")
    body += panel(520, 493, 400, 110, "交接", ["异常、阻塞或额度用完"], "#b45309")
    body += arrow("M720 252 V222 H240 V244")
    body += text(480, 215, "可修复且有额度：带反馈继续，共用原账本", 18, "#0f766e")
    body += text(480, 653, "Final 只返回控制权；完成、继续与交接由外层决定。", 19, "#475569")
    save("p05-workflow-boundary.svg", "固定业务步骤包住有边界的内部循环", "准备、验收和交接由程序决定，内部执行者提出动作，继续沿用原预算。", 695, body)

    body = ""
    for x, name, title, color in [(40, "false-final", "只声称完成", "#b45309"), (520, "normal", "实际写出合格文件", "#0f766e")]:
        row = rows[name]
        body += panel(x, 95, 400, 185, title, ["正常返回 = {} 次".format(row["normal_returns"]), "产物达标 = {}".format(str(row["goal_verified"]).lower()), "最终状态 = " + row["status"]], color)
    body += panel(40, 335, 880, 135, "产物达标与运行终态还要分开记录", ["valid-then-model-error：goal_verified = {}".format(str(rows["valid-then-model-error"]["goal_verified"]).lower()), "模型阶段异常，status = " + rows["valid-then-model-error"]["status"]], "#b45309")
    body += text(480, 525, "判断器只读冻结合同与实际文件，不读取“我已完成”的声明。", 19, "#475569")
    save("p05-return-and-goal.svg", "正常返回、产物达标与业务终态分别核对", "声称完成两次仍没有产物；正常写入后可完成；产物合格但模型异常仍转人工。", 570, body)

    stall = rows["no-progress"]
    evaluations = [event for event in stall["trace"] if event["phase"] == "evaluate"]
    calls, cumulative = 0, []
    for event in stall["trace"]:
        calls += event["phase"] == "model"
        if event["phase"] == "evaluate":
            cumulative.append(calls)
    for i, event in enumerate(evaluations):
        x = 40 + i * 306
        progress = "首次提高历史最佳" if i == 0 else "连续 {} 次无提升".format(i)
        body_piece = panel(x, 105, 268, 160, "episode {}".format(event["episode"]), ["正确字段 = {}".format(event["verdict"]["score"]), "累计调用 = {}".format(cumulative[i]), progress], "#0f766e" if i == 0 else "#b45309")
        if i == 0:
            body = body_piece
        else:
            body += body_piece
        if i < len(evaluations)-1:
            body += arrow("M{} 185 H{}".format(x+268, x+296))
    body += panel(40, 325, 880, 105, "重复写入仍只有两个正确字段", ["第一次有进展；随后连续 {} 次不超过历史最佳，停止".format(stall["limits"]["stagnant"])], "#b45309")
    body += panel(40, 475, 880, 100, "保留部分报告与累计账本", ["reason = {} · 写入 = {} 次".format(stall["reason"], stall["writes"])], "#0f766e")
    body += text(480, 623, "进度来自业务合同；文件修改时间与答案长度不参与计分。", 19, "#475569")
    save("p05-bounded-continuation.svg", "有动作不代表有进展，继续必须有上限", "连续三次验收正确字段均为二，累计调用三、五、七次，连续两次无提升后交接。", 670, body)

    limited = rows["model-budget"]
    success = rows["continue-success"]
    body = panel(40, 95, 400, 170, "continue-success", ["{} 段 · {} 次调用".format(success["used"]["episodes"], success["used"]["model_calls"]), "{} 次工具 · {} 字节预留".format(success["used"]["tools"], success["used"]["write_bytes"]), "同一账本累计到完成"], "#0f766e")
    body += panel(520, 95, 400, 170, "model-budget", ["调用上限 = {}".format(limited["limits"]["model_calls"]), "第 {} 段前仍已用 {} 次".format(limited["used"]["episodes"], limited["used"]["model_calls"]), "调用前拒绝，保留部分报告"], "#b45309")
    body += panel(40, 325, 880, 140, "交接保留什么？", ["冻结输入与期望值 · 原累计用量与额度", "停止原因 · 最近验收 · 已有动作计数"], "#0f766e")
    body += text(480, 520, "继续复用预算；handoff.json 不授予新预算，也不自动恢复。", 19, "#475569")
    save("p05-shared-budget.svg", "继续与交接都沿用同一份累计账本", "修复成功总计五次调用；三次调用用尽的场景在第二段新调用前停止并保存交接。", 565, body)
