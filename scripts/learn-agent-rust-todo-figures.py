"""R05 figures (ADK-Rust 3.0): schematic transitions and snapshots from the verified Cargo archive."""
import hashlib
import json


def generate(root, text, panel, arrow, save_figure):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r05-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/todo-planning"
    for name, digest in evidence["source_sha256"].items():
        # 取源码脚本与基线文件打包时从 scripts/ 加入，不在章节目录里
        source = package / name if (package / name).exists() else root / "scripts" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise SystemExit("Stale R05 evidence; run verify-learn-agent-rust-r05.py first")
    normal, claims = evidence["reports"]["normal"], evidence["reports"]["claims-only"]

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

    body = text(480, 85, "每次请求模型之前，before_model 回调放入会话状态里的最新清单", 20, "#475569")
    columns = [(95, "模型轮次"), (225, "清单版本"), (395, "读取 README"), (605, "整理说明"), (815, "核对原文")]
    for x, label in columns:
        body += text(x, 133, label, 19, bold=True)
    labels = {"pending": "待开始", "in_progress": "进行中", "completed": "已完成"}
    colors = {"pending": "#64748b", "in_progress": "#b45309", "completed": "#0f766e"}
    for index, item in enumerate(evidence["normal_snapshots"]):
        y = 156 + index * 52
        body += '<rect x="40" y="{}" width="880" height="44" rx="8" fill="{}"/>'.format(y, "#fff" if index % 2 == 0 else "#eff6ff")
        body += text(95, y + 29, str(index + 1), 19)
        body += text(225, y + 29, str(item["revision"]), 19, "#2563eb", True)
        for x, task_id in [(395, "read"), (605, "summarize"), (815, "check")]:
            status = item["items"].get(task_id)
            body += text(x, y + 29, labels.get(status, "尚未建单"), 18, colors.get(status, "#64748b"))
    body += text(480, 568, "第 3 轮真实读文件，不更新清单：第 4 轮看到的仍是版本 2。", 19, "#0f766e")
    body += text(480, 607, "数据：normal 中模型每次收到的请求；清单版本与模型调用次数分别计数。", 17, "#475569")
    save_figure("r05-plan-snapshots.svg", "计划在每一次请求中如何变化？", "七次模型请求里看到的清单版本来自 normal 实际运行记录，文件读取不会自动完成清单条目。", 638, body)

    body = panel(40, 85, 390, 140, "会话状态 plan + 事件历史", ["before_model 回调读最新清单", "放进本次 LlmRequest"])
    body += arrow("M430 153 H520")
    body += panel(530, 85, 390, 140, "PlanLlm 只看请求", ["todo_read / todo_write", "read_file / write_file"], "#0f766e")
    body += arrow("M725 225 V265")
    body += panel(530, 275, 390, 140, "Runner：策略 → 工具", ["todo_write：校验 → state_delta", "write_file：应用策略拒绝"], "#b45309")
    body += arrow("M530 345 H235 V235")
    body += text(267, 382, "事件产出时合并 state_delta", 18, "#475569")
    for x, report, title in [(40, normal, "正常读取"), (530, claims, "只改完成标记")]:
        body += panel(x, 470, 390, 147, title, [
            "清单全部完成：" + str(report["all_completed"]).lower(),
            "成功读取 {} 次 · 目标验收 {}".format(report["reads"], str(report["goal_verified"]).lower()),
        ], "#0f766e" if report["goal_verified"] else "#b91c1c")
    body += text(480, 659, "上方是接线示意；下方来自 normal 与 claims-only 的实际输出。", 17, "#475569")
    save_figure("r05-visible-loop.svg", "计划可见，执行证据仍要单独核对", "清单保存在会话状态里，before_model 回调每次请求前放入最新清单，todo_write 校验后经 state_delta 写回。完成标记和任务验收在对照实验中分离。", 690, body)
