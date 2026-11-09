"""R05 figures: schematic transitions and snapshots from the verified Cargo archive."""
import hashlib
import json


def generate(root, text, panel, arrow, save_figure):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r05-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/todo-planning"
    for name, digest in evidence["source_sha256"].items():
        if hashlib.sha256((package / name).read_bytes()).hexdigest() != digest:
            raise SystemExit("Stale R05 evidence; run verify-learn-agent-rust-r05.py first")
    reports = {item["scenario"]: item for item in evidence["scenarios"]}
    normal, claims = reports["normal"], reports["claims-only"]

    body = panel(40, 105, 240, 115, "pending", ["已列入计划，尚未开始"])
    body += panel(360, 105, 240, 115, "in_progress", ["当前正在推进的步骤"], "#b45309")
    body += panel(680, 105, 240, 115, "completed", ["保留记录，终态"], "#0f766e")
    body += arrow("M280 160 H350") + arrow("M600 160 H670")
    body += text(320, 139, "开始", 17) + text(640, 139, "完成", 17)
    body += arrow("M480 220 V270 H160 V230")
    body += text(320, 300, "让出当前步骤：回到 pending", 18, "#b45309")
    body += panel(40, 340, 880, 140, "整份候选清单一起校验", ["新增条目从 pending 开始；每份快照最多一个 in_progress。",
        "ID 唯一、内容不变、历史保留、版本匹配；全部通过才替换当前清单。"], "#0f766e")
    body += text(480, 522, "示意图：每个状态也允许保持原状；这些是本章的应用规则。", 18, "#475569")
    save_figure("r05-state-transitions.svg", "清单条目怎样迁移？", "本章允许开始、完成和让出步骤，已完成条目保留，整批通过才提交。", 554, body)

    body = text(480, 85, "每次模型调用前，重新读取运行时的清单与历史", 20, "#475569")
    columns = [(95, "模型轮次"), (225, "清单版本"), (395, "读取 README"), (605, "整理说明"), (815, "核对原文")]
    for x, label in columns:
        body += text(x, 133, label, 19, bold=True)
    labels = {"pending": "待开始", "in_progress": "进行中", "completed": "已完成"}
    colors = {"pending": "#64748b", "in_progress": "#b45309", "completed": "#0f766e"}
    for index, item in enumerate(normal["inputs"]):
        y = 156 + index * 52
        body += '<rect x="40" y="{}" width="880" height="44" rx="8" fill="{}"/>'.format(y, "#fff" if index % 2 == 0 else "#eff6ff")
        body += text(95, y + 29, str(index + 1), 19)
        body += text(225, y + 29, str(item["plan"]["revision"]), 19, "#2563eb", True)
        tasks = {task["id"]: task for task in item["plan"]["items"]}
        for x, task_id in [(395, "read"), (605, "summarize"), (815, "check")]:
            status = tasks.get(task_id, {}).get("status")
            body += text(x, y + 29, labels.get(status, "尚未建单"), 18, colors.get(status, "#64748b"))
    body += text(480, 568, "第 3 轮真实读文件，不更新清单：第 4 轮看到的仍是版本 2。", 19, "#0f766e")
    body += text(480, 607, "数据：normal 的 inputs；清单版本与模型轮次分别计数。", 17, "#475569")
    save_figure("r05-plan-snapshots.svg", "计划在每一轮输入中如何变化？", "七轮输入和版本来自 normal 实际运行记录，文件读取不会自动完成清单条目。", 638, body)

    body = panel(40, 85, 390, 140, "Runtime 拥有当前状态", ["目标 + 最新 Plan + 消息历史", "构造本轮 ModelInput"])
    body += arrow("M430 153 H520")
    body += panel(530, 85, 390, 140, "脚本模型提出请求", ["todo_read / todo_write", "read_file / write_file"], "#0f766e")
    body += arrow("M725 225 V265")
    body += panel(530, 275, 390, 140, "工具派发器", ["清单：校验 → 整批替换", "文件：独立检查权限 → 执行"], "#b45309")
    body += arrow("M530 345 H235 V235")
    body += text(267, 382, "按 call_id 写回结果", 18, "#475569")
    for x, report, title in [(40, normal, "正常读取"), (530, claims, "只改完成标记")]:
        body += panel(x, 470, 390, 147, title, [
            "清单全部完成：" + str(report["all_completed"]).lower(),
            "成功读取 {} 次 · 目标验收 {}".format(report["reads"], str(report["goal_verified"]).lower()),
        ], "#0f766e" if report["goal_verified"] else "#b91c1c")
    body += text(480, 659, "上方是接线示意；下方来自 normal 与 claims-only 的实际输出。", 17, "#475569")
    save_figure("r05-visible-loop.svg", "计划可见，执行证据仍要单独核对", "运行时每轮提供最新清单，工具校验并回传结果。完成标记和任务验收在对照实验中分离。", 690, body)
