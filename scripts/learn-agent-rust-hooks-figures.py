"""R04 figures (ADK-Rust 3.0 version), called by generate-learn-agent-rust-figures.py --lesson R04."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r04-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/hooks"
    for name, digest in evidence["source_sha256"].items():
        path = package / name if (package / name).exists() else root / "scripts" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("R04 evidence is stale; rerun verify-agent-hooks.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}

    # 1. 正常路径：四个位置与实测顺序
    normal = [h.split(" ")[0] for h in rows["normal"]["hooks"]]
    groups = [("before_agent", "Agent 开始前", "#2563eb"), ("before_tool", "工具执行前（策略检查之前）", "#2563eb"),
              ("after_tool", "工具执行后", "#0f766e"), ("after_agent", "Agent 结束时", "#b45309")]
    body = ""
    for index, (point, title, color) in enumerate(groups):
        names = [h.split("/")[1] for h in normal if h.startswith(point + "/")]
        y = 78 + index * 150
        body += panel(80, y, 800, 118, "{} · {}".format(point, title), [" → ".join(names)], color)
        if index < len(groups) - 1:
            middle = "策略检查 → 执行 write_summary" if point == "before_tool" else ""
            body += arrow("M480 {} V{}".format(y + 118, y + 141))
            if middle:
                body += text(700, y + 136, middle, 16, "#475569")
    body += text(480, 702, "回调顺序取自正常路径的回调日志；策略的位置依据框架的受控路径（策略本身不写日志）。", 17, "#475569")
    save("r04-lifecycle-order.svg", "四个位置，沿一次工具调用观察", "回调顺序来自 R04 normal 实际运行：before_agent、before_tool、策略与执行、after_tool、after_agent。", 734, body)

    # 2. 各阶段失败的后果
    body = text(480, 85, "文件结果、模型看到的结果、任务结果分开核对。", 18, "#475569")
    for x, label in [(155, "场景"), (367, "写入尝试 / 成功"), (585, "结果状态"), (815, "任务通过")]:
        body += text(x, 133, label, 20, bold=True)
    selected = ["normal", "permission-deny", "pre-block", "pre-timeout", "post-error", "post-rewrite", "tool-error", "stop-error", "prompt-error"]
    for index, name in enumerate(selected):
        row = rows[name]
        y = 178 + index * 49
        if index % 2 == 0:
            body += '<rect x="28" y="{}" width="904" height="46" rx="6" fill="#e2e8f0"/>'.format(y - 29)
        body += text(155, y, name, 19)
        body += text(367, y, "{} / {}".format(row["write_attempts"], row["write_successes"]), 21, "#0f766e", True)
        body += text(585, y, "—" if row["result_status"] in ("none", "") else row["result_status"], 18)
        body += text(815, y, "是" if row["task_ok"] else "否", 20, "#0f766e" if row["task_ok"] else "#b91c1c", True)
    body += text(480, 655, "after_tool 出错：文件已写入，模型只看到 withheld；after_agent 出错：运行以错误结束。", 17, "#b45309", True)
    body += text(480, 693, "数据来自真实文件实验；模型请求为固定脚本。", 17, "#475569")
    save("r04-failure-results.svg", "在哪个阶段失败，决定了已经发生什么", "实际运行显示：执行前的回调拦下或超时都没有写入；执行后的回调出错时文件已写入但结果被扣下；结束回调出错时运行以错误结束。", 724, body)

    # 3. 工具调用的受控流水线：每一站失败的后果
    stages = [("before_tool 回调", "出错 / panic / 超时 → not_run（失败即关闭）", "#2563eb"),
              ("策略检查（ToolPolicy）", "拒绝 → refused；回调无法放行被拒绝的调用", "#b91c1c"),
              ("执行工具", "失败 → failed；after 回调照常运行", "#0f766e"),
              ("after_tool 回调", "出错 → withheld：结果扣下，后面的回调不再运行", "#b45309")]
    body = ""
    for index, (title, line, color) in enumerate(stages):
        y = 80 + index * 128
        body += panel(120, y, 720, 100, title, [line], color)
        if index < len(stages) - 1:
            body += arrow("M480 {} V{}".format(y + 100, y + 121))
    body += text(480, 612, "框架不给回调限时：本章的回调用 tokio::time::timeout 自己设上限。", 17, "#475569")
    save("r04-tool-pipeline.svg", "一次工具调用经过的几站，以及每站失败的后果", "before_tool 回调在策略之前运行，失败时调用不执行；策略拒绝的调用不执行也不触发 after_tool；工具失败时 after 回调照常运行；after_tool 回调失败时结果被扣下。", 644, body)
