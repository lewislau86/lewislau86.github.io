"""R04 figures, called by generate-learn-agent-rust-figures.py --lesson R04."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r04-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/hooks.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R04 evidence is stale; rerun verify-agent-hooks.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}

    normal = rows["normal"]
    descriptions = {
        "UserPromptSubmit": ["接收输入，之后生成固定工具请求", "input-log"],
        "PreToolUse": ["已核对批准，再运行执行前检查", "before-check → before-log"],
        "PostToolUse": ["已得到真实工具结果，再运行后置检查", "after-check → after-log"],
        "Stop": ["任务停止时统一收尾，保留停止原因", "stop-log"],
    }
    body = ""
    for index, event in enumerate(normal["events"]):
        y = 78 + index * 150
        body += panel(80, y, 800, 118, event, descriptions[event], "#b45309" if event == "Stop" else "#2563eb")
        if index < len(normal["events"]) - 1:
            body += arrow("M480 {} V{}".format(y + 118, y + 141))
    body += text(480, 702, "正常路径实测顺序；Pre 与 Post 之间发生一次真实文件写入。", 18, "#475569")
    save("r04-lifecycle-order.svg", "把扩展放到边界，沿一次工具轮次观察", "四个事件与回调顺序来自 R04 normal 实际运行。批准检查在前置事件之前，工具执行在前置与后置事件之间。", 734, body)

    body = text(480, 85, "文件结果与任务结果分开核对；各场景的 Stop 均只触发一次。", 18, "#475569")
    for x, label in [(155, "场景"), (367, "尝试 / 成功"), (585, "工具结果"), (815, "任务通过")]:
        body += text(x, 133, label, 20, bold=True)
    selected = ["normal", "permission-deny", "pre-block", "pre-timeout", "post-error", "post-timeout", "tool-error", "stop-error", "stop-timeout"]
    for index, name in enumerate(selected):
        row = rows[name]
        y = 178 + index * 49
        if index % 2 == 0:
            body += '<rect x="28" y="{}" width="904" height="46" rx="6" fill="#e2e8f0"/>'.format(y - 29)
        body += text(155, y, name, 19)
        body += text(367, y, "{} / {}".format(row["write_attempts"], row["write_successes"]), 21, "#0f766e", True)
        body += text(585, y, row["result_status"], 18)
        body += text(815, y, "是" if row["task_ok"] else "否", 20, "#0f766e" if row["task_ok"] else "#b91c1c", True)
    body += text(480, 655, "后置或停止回调失败：文件已经写入，工具的 ok 结果仍然保留。", 18, "#b45309", True)
    body += text(480, 693, "数据来自真实文件实验；固定请求与既有批准由可信测试入口提供。", 17, "#475569")
    save("r04-failure-results.svg", "在哪个阶段失败，决定了文件已经发生什么", "实际运行显示前置阻止与超时均未写入；后置和停止回调失败保留文件与工具结果，但任务未通过。", 724, body)

    body = panel(36, 86, 410, 168, "父进程：Agent 运行时", ["启动本程序的固定 worker 模式", "try_wait 检查退出状态", "Instant 检查本次时间预算"])
    body += panel(514, 86, 410, 168, "直属子进程：故障回调", ["panic：异常退出", "hang：持续等待", "本实验不创建后代进程"], "#b45309")
    body += arrow("M446 166 H505")
    body += arrow("M720 254 V304 H480 V340")
    body += panel(170, 350, 620, 142, "超过预算：kill 后继续 wait", ["确认直属 worker 已结束并回收", "才返回 TimeoutReaped"], "#b91c1c")
    body += text(480, 541, "普通 Rust 回调仍在进程内；超时实验单独采用子进程边界。", 19, bold=True)
    body += text(480, 584, "本图说明资源生命周期，不承诺通用进程树终止、沙箱或实时调度。", 17, "#475569")
    save("r04-worker-timeout.svg", "超时后，谁负责结束并回收回调？", "父进程启动固定 worker，检测时间预算，超时后终止并等待直属子进程，再返回类型化错误。", 616, body)
