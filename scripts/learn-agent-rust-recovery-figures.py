"""R11 figures from verified virtual-clock and filesystem evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r11-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/error-recovery.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R11 evidence is stale; rerun verify-agent-recovery.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    body = panel(220, 80, 520, 104, "先检查输入、权限与取消", ["通过后，先记账，再派发尝试。"])
    body += arrow("M480 184 V218")
    body += panel(220, 228, 520, 104, "保留类型化失败", ["同时核对操作是否允许安全重试。"])
    for x in (163, 480, 797):
        body += arrow("M480 332 V365 H{} V396".format(x))
    body += panel(20, 405, 286, 172, "临时错误 + 只读", ["检查次数与任务总预算", "安排有限退避", "恢复仍复用同一账本"], "#0f766e")
    body += panel(337, 405, 286, 172, "输入 / 权限 / 永久错误", ["结束当前调用", "返回明确错误", "由上层决定修正方式"], "#b45309")
    body += panel(654, 405, 286, 172, "写入结果不明", ["保留已发生的文件效果", "停止自动重放", "要求核对实际结果"], "#b91c1c")
    body += text(480, 623, "分类告诉程序下一步做什么；停止原因说明为什么结束。", 19, bold=True)
    save("r11-recovery-routes.svg", "恢复前先回答：还能再做一次吗？",
         "R11 实现将临时只读失败送入有限退避，永久错误结束调用，写入结果不明要求核对。", 660, body)

    row = rows["backoff"]
    starts = row["starts_ms"]
    waits = [int(item.split("delay_ms=")[1].split()[0]) for item in row["trace"] if item.startswith("schedule")]
    for index, x in enumerate((50, 355, 660)):
        body_part = panel(x, 92, 250, 140, "尝试 {}".format(index + 1),
                          ["开始 {} ms".format(starts[index]), "失败" if index < 2 else "真实读取成功"],
                          "#b45309" if index < 2 else "#0f766e")
        if index == 0:
            body = body_part
        else:
            body += body_part
        if index < 2:
            body += arrow("M{} 162 H{}".format(x + 250, x + 296))
            body += text(x + 276, 268, "{} ms".format(waits[index]), 19, "#b45309", True)
    body += panel(70, 318, 820, 132, "累计账本来自 backoff 实际运行",
                  ["尝试 {} 次；等待 {} ms；虚拟时钟到 {} ms".format(row["calls"], row["waited_ms"], row["now_ms"]),
                   "每次尝试注入 10 ms；两次退避合计 300 ms。"], "#2563eb")
    body += text(480, 498, "虚拟时间用于验证顺序与预算；本实验不 sleep，也不测真实网络延迟。", 18, "#475569")
    save("r11-backoff-timeline.svg", "先预测三次尝试分别在什么时候开始",
         "backoff 场景开始时间为 0、110、320 毫秒，含每次尝试注入的十毫秒与一百、二百毫秒等待。", 538, body)

    selected = ["normal", "attempt-limit", "call-budget", "wait-budget", "resume-budget",
                "resume-expired", "cancelled-backoff", "shared-budget", "append-unknown"]
    body = text(480, 86, "累计尝试含失败；日志行数由验证器直接读取文件核对。", 18, "#475569")
    for x, label in [(170, "场景"), (418, "总尝试"), (592, "日志行数"), (805, "停止原因")]:
        body += text(x, 132, label, 20, bold=True)
    for index, name in enumerate(selected):
        row = rows[name]
        y = 183 + index * 48
        if index % 2 == 0:
            body += '<rect x="24" y="{}" width="912" height="44" rx="6" fill="#e2e8f0"/>'.format(y - 28)
        body += text(170, y, name, 18)
        body += text(418, y, str(row["calls"]), 22, "#0f766e", True)
        body += text(592, y, str(row["lines"]), 22, "#b45309", True)
        body += text(805, y, row["stop"], 17)
    body += text(480, 654, "恢复保留总账；换一个 call_id 也不能越过任务额度。", 19, bold=True)
    body += text(480, 693, "append-unknown：写入一行后丢弃回复，程序只执行一次。", 18, "#b45309")
    save("r11-recovery-results.svg", "恢复后的任务仍然有终点",
         "九个实际场景展示预算、截止时间、取消与结果不明的停止；源于二十一个场景的实验记录。", 730, body)
