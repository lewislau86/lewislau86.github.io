"""R06 figures (ADK-Rust 3.0), called by generate-learn-agent-rust-figures.py --lesson R06."""

import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r06-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/subagents"
    for name, digest in evidence["source_sha256"].items():
        source = package / name if (package / name).exists() else root / "scripts" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("R06 evidence is stale; run verify-agent-subagents.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    normal, limited, transfer = rows["normal"], rows["parent-answer-budget"], rows["transfer"]

    body = text(240, 85, "父模型的请求（coordinator）", 22, "#2563eb", True)
    body += text(720, 85, "子模型的请求（reader，新会话）", 22, "#0f766e", True)
    parent = [(112, "system", "PARENT_ONLY_NOTE"), (210, "user", "项目怎么启动？"),
              (308, "model：调用 reader", "parent/delegate-1 {request}"),
              (602, "function：reader 的结果", '{"response":"启动命令：cargo run"}'),
              (700, "model：回答用户", "项目的启动命令：cargo run")]
    child = [(112, "system", "reader 的 instruction"), (210, "user", "父模型给的 request 文字"),
             (308, "model：调用 read_file", "child-1/read-1"),
             (406, "function：文件原文", "含 CHILD_RAW_ONLY 标记"),
             (504, "model：最终回答", "启动命令：cargo run")]
    for y, title, line in parent:
        body += panel(40, y, 400, 82, title, [line], "#2563eb")
    for y, title, line in child:
        body += panel(520, y, 400, 82, title, [line], "#0f766e")
    for start, end in [(194, 210), (292, 308), (684, 700)]:
        body += arrow("M240 {} V{}".format(start, end - 4))
    body += arrow("M240 390 V420 H64 V560 H240 V598")
    for y in [194, 292, 390, 488]:
        body += arrow("M720 {} V{}".format(y, y + 12))
    body += arrow("M440 349 H478 V251 H516")
    body += arrow("M520 545 H486 V643 H444")
    body += text(246, 474, "子事件只转发给宿主诊断", 18, "#475569")
    body += text(480, 834, "实测：父模型请求 {} 次 / 子模型请求 {} 次；父请求里没有 CHILD_RAW_ONLY，子请求里没有 PARENT_ONLY_NOTE。".format(
        normal["parent_model_calls"], normal["child_model_calls"]), 18, "#0f766e", True)
    body += text(480, 872, "标记只检查本实验的数据流；文件系统仍由工具自己限制。", 17, "#475569")
    save("r06-context-boundary.svg", "只把任务交出去，只把最终回答带回来",
         "AgentTool 为子 Agent 建新会话：父模型的请求只包含委派和子 Agent 的最终回答，子模型的请求从自己的说明和任务开始，文件原文只在子 Agent 一侧。", 900, body)

    body = panel(40, 90, 540, 110, "一份运行预算（Runner 上的 RunBudget）", ["父子的模型请求、工具调用都记在这里"])
    body += arrow("M200 200 V240") + arrow("M560 200 H600 V382 H310 V396")
    body += panel(40, 248, 540, 112, "父 Agent", ["模型 {} 次：委派、回答".format(normal["parent_model_calls"]), "工具 1 次：reader"])
    body += panel(40, 400, 540, 112, "子 Agent（AgentTool 新会话）", ["模型 {} 次：读取、提取".format(normal["child_model_calls"]), "工具 1 次：read_file"], "#0f766e")
    body += panel(620, 90, 300, 144, "总模型额度只有 3", ["父 Agent 先用 1 次", "子 Agent 再用 2 次"], "#b45309")
    body += arrow("M770 234 V274")
    body += panel(620, 282, 300, 112, "子 Agent 已完成", ["读取 {}".format(limited["reads"].replace("/", " 次，成功 ") + " 次")], "#0f766e")
    body += arrow("M770 394 V434")
    body += panel(620, 442, 300, 112, "父 Agent 的回答被拦下", [limited["stop"]], "#b45309")
    body += text(480, 612, "实测 parent-answer-budget：父 {} 次 / 子 {} 次；子任务完成，练习目标仍为 false。".format(
        limited["parent_model_calls"], limited["child_model_calls"]), 19, "#b45309", True)
    body += text(480, 650, "子 Agent 没有自己的一份新预算；局部上限只能用它自己的 max_iterations。", 17, "#475569")
    save("r06-shared-budget.svg", "父子共用一份运行预算",
         "正常路径父子各两次模型请求、各一次工具调用，记在同一份运行预算上；总模型额度为 3 时，子 Agent 完成后父 Agent 的回答无法开始。", 682, body)

    body = text(240, 86, "当工具调用：AgentTool", 22, "#2563eb", True)
    body += text(720, 86, "交接控制权：transfer_to_agent", 22, "#0f766e", True)
    body += panel(40, 112, 400, 100, "父模型调用 reader 工具", ["传一段任务文字"])
    body += arrow("M240 212 V248")
    body += panel(40, 256, 400, 100, "reader 在新会话里运行", ["只看到自己的说明和任务"])
    body += arrow("M240 356 V392")
    body += panel(40, 400, 400, 100, "最终回答作为工具结果返回", ["父 Agent 继续，再回答用户"], "#2563eb")
    body += panel(520, 112, 400, 100, "父模型调用 transfer_to_agent", ["参数是 reader 的名字"], "#0f766e")
    body += arrow("M720 212 V248")
    body += panel(520, 256, 400, 100, "reader 在同一个会话里接手", ["看到用户原话；可以再交回"], "#0f766e")
    body += arrow("M720 356 V392")
    body += panel(520, 400, 400, 100, "reader 直接回答用户", ["父 Agent 不再继续"], "#0f766e")
    body += text(480, 552, "实测 transfer：父模型请求 {} 次，子模型 {} 次，回答者 {}。".format(
        transfer["parent_model_calls"], transfer["child_model_calls"], transfer["answered_by"]), 19, "#0f766e", True)
    save("r06-transfer-vs-tool.svg", "两种把工作交出去的方式",
         "AgentTool 让子 Agent 在新会话里运行并把最终回答交回父 Agent；transfer_to_agent 让子 Agent 在同一个会话里接手并直接回答用户。", 590, body)
