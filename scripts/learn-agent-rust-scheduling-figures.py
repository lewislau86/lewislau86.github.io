"""R14 figures from verified SQLite and timezone experiments."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    data = json.loads((root / "scripts/data/learn-agent-rust/r14-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/scheduling"
    for name, digest in data["files_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("R14 evidence stale; run verify-agent-scheduling.py")
    rows = {r["name"]: r for r in data["scenarios"]}
    normal = rows["normal"]["steps"][-1]
    schedule = normal["schedules"][0]
    body = panel(40, 90, 400, 130, "持久计划 · 配置不可变", [schedule["timezone"] + " · " + schedule["local_time"], "计划 ID：" + schedule["id"]])
    body += arrow("M440 155 H516")
    body += panel(520, 90, 400, 130, "程序轮询 · 不依赖模型回合", ["日历换算 → 扫描 (cursor, now]", "按配置选择到期点"], "#0f766e")
    body += arrow("M720 220 V260")
    body += panel(40, 268, 880, 130, "一个 SQLite 写事务", ["插入唯一触发任务 + 更新扫描游标", "全部成功，才 COMMIT"], "#b45309")
    body += arrow("M480 398 V438")
    body += panel(40, 446, 880, 100, "持久队列 · 后续执行者的输入", ["正常场景最终保留 {} 条 daily_report / queued".format(len(normal["tasks"]))], "#0f766e")
    body += text(480, 594, "本章验证生产与入队；报告生成、模型调用和完成确认在消费阶段处理。", 18, "#475569")
    save("r14-schedule-to-queue.svg", "时间规则产生工作，队列保留待执行任务", "每日计划经程序轮询与时间换算，将任务和游标放进同一个事务，工作留在持久队列。", 630, body)

    gap = rows["dst-gap"]["steps"][0]
    fold = rows["dst-fold"]["steps"][0]
    body = panel(40, 86, 400, 140, gap["date"] + " · " + gap["local_time"], [gap["zone"], "本地时刻缺失：" + gap["mapping"]], "#b45309")
    body += panel(520, 86, 400, 140, fold["date"] + " · " + fold["local_time"], [fold["zone"], "本地时刻重复：" + fold["mapping"]])
    body += arrow("M240 226 V264") + arrow("M720 226 V264")
    body += panel(40, 272, 400, 128, "UTC 候选为空", ["候选数：" + str(len(gap["utc"])), "chosen=null"], "#b45309")
    body += panel(520, 272, 400, 128, "两个 UTC 候选", [value.split("T")[1] for value in fold["utc"]])
    body += arrow("M240 400 V438") + arrow("M720 400 V438")
    body += panel(40, 446, 400, 100, "策略：该日跳过", ["最终排队 {} 条".format(rows["dst-gap"]["queued"])], "#b45309")
    body += panel(520, 446, 400, 100, "策略：只选较早一次", ["选中 " + fold["chosen"].split("T")[1] + " · 排队 " + str(rows["dst-fold"]["queued"]) + " 条"], "#0f766e")
    body += text(480, 593, "时间来自固定依赖中的 IANA 数据；换算结果和业务选择分别记录。", 18, "#475569")
    save("r14-dst-mapping.svg", "一个本地时刻，可能没有或拥有两个 UTC 结果", "纽约春季缺失时刻不产生候选，秋季重复时刻只选择较早一次，两个场景实测分别排队零条与一条。", 630, body)

    coalesce = next(s for s in rows["coalesce"]["steps"] if s["status"] == "committed")
    skip = next(s for s in rows["skip"]["steps"] if s["status"] == "committed")
    a, b = coalesce["reports"][0], skip["reports"][0]
    body = text(480, 86, "同一起点、时区、当地时分与扫描时刻，只改变策略。", 19, "#475569")
    body += panel(40, 114, 880, 100, "扫描窗口中发现 {} 个到期点".format(a["due_count"]), ["扫描 UTC：" + coalesce["now"]])
    for index in range(a["due_count"]):
        x = 180 + index * 300
        if index:
            body += arrow("M{} 266 H{}".format(x - 270, x - 30))
        body += '<circle cx="{}" cy="266" r="22" fill="{}"/>'.format(x, "#0f766e" if index == a["due_count"]-1 else "#64748b")
        body += text(x, 273, str(index+1), 20, "#fff", True)
    body += text(480, 324, "最近到期点 UTC：" + a["selected"], 19, "#0f766e", True)
    body += panel(40, 366, 400, 145, "coalesce · 合并补最近一次", ["入队 {} 条".format(a["inserted"]), "丢弃 {} 个较早到期点".format(a["discarded"])], "#0f766e")
    body += panel(520, 366, 400, 145, "skip · 最近一次也已过期", ["入队 {} 条".format(b["inserted"]), "丢弃 {} 个到期点".format(b["discarded"])], "#b45309")
    body += text(480, 565, "两种策略都推进游标；丢弃的旧点不会在下一次重复补发。", 18, "#475569")
    save("r14-misfire-policy.svg", "错过三次触发，补什么由策略决定", "同一输入下合并策略补最近一次并丢弃较早两次，跳过策略因最近一次也超宽限而不入队。", 600, body)

    before = rows["exit-before-commit"]["steps"]
    after = rows["exit-after-commit"]["steps"]
    before_state = [s for s in before if s["status"] == "snapshot"][1]
    after_state = [s for s in after if s["status"] == "snapshot"][0]
    for x, steps, state, title, color in [(40,before,before_state,"插入后、提交前退出","#b45309"), (520,after,after_state,"提交后、返回确认前退出","#0f766e")]:
        code = next(s["code"] for s in steps if s["status"] == "process_exit")
        report = [s for s in steps if s["status"] == "committed"][-1]["reports"][0]
        body_part = panel(x, 92, 400, 110, title, ["进程直接退出，code=" + str(code)], color)
        body_part += arrow("M{} 202 V240".format(x+200))
        body_part += panel(x, 248, 400, 130, "新进程读取持久状态", ["排队 {} 条".format(len(state["tasks"])), "游标 " + state["schedules"][0]["cursor"].split("T")[1]], color)
        body_part += arrow("M{} 378 V416".format(x+200))
        body_part += panel(x, 424, 400, 110, "重试同一个扫描时刻", ["新增 {} 条 · 最终 {} 条".format(report["inserted"], len(steps[-1]["tasks"]))], "#0f766e")
        if x == 40:
            body = body_part
        else:
            body += body_part
    body += text(480, 582, "非零退出码不决定是否已提交；新进程先查状态，再决定后续动作。", 18, "#475569")
    save("r14-commit-recovery.svg", "重启看到什么，取决于退出发生在提交哪一侧", "提交前退出时任务与游标回滚，提交后未返回确认时任务与游标已保存，重试两种路径最终均只有一条任务。", 620, body)
