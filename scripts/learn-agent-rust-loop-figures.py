"""R01 figures (ADK-Rust 3.0 version), called by generate-learn-agent-rust-figures.py --lesson R01."""

import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r01-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/agent-loop"
    for name, digest in evidence["source_sha256"].items():
        # 下载包另外放进 fetch-adk-rust.py 与基线文件，它们的唯一来源在 scripts/
        path = package / name if (package / name).exists() else root / "scripts" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("R01 evidence is stale; run verify-learn-agent-rust-loop.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    normal = rows["normal"]
    body = ""
    roles = [("user", "读取 README，告诉我启动命令"),
             ("model · 请求", 'read-1 / read_file("README.md")'),
             ("function · 结果", "read-1 / 启动命令：cargo run"),
             ("model · 回答", "README 里的启动命令是：cargo run")]
    for i, (role, content) in enumerate(roles):
        y = 80 + i * 112
        body += panel(40, y, 620, 88, role, [content], "#0f766e" if i == 2 else "#2563eb")
        if i < 3:
            body += arrow("M350 {} V{}".format(y + 88, y + 107))
    body += panel(704, 108, 216, 128, "模型调用", [str(normal["model_calls"])], "#2563eb")
    body += panel(704, 266, 216, 128, "工具结果", [str(normal["tool_results"])], "#0f766e")
    body += panel(704, 424, 216, 128, "会话事件", [str(normal["session_events"])], "#b45309")
    body += text(480, 594, "计数与调用 ID 来自 normal 场景实际运行；模型是按规则回复的 RuleLlm。", 17, "#475569")
    save("r01-message-cycle.svg", "一次文件读取，经过两次模型调用", "请求和结果通过 read-1 关联。正常路径产生四条会话事件、两次模型调用和一条工具结果。", 622, body)

    body = panel(40, 82, 550, 88, "LlmAgent：调用模型前检查", ["循环上限到了吗？Runner 装上的预算还有余量吗？"])
    body += arrow("M590 126 H678")
    body += panel(686, 82, 234, 88, "超限", ["budget.model_calls / agent.legacy"], "#b45309")
    body += arrow("M315 170 V204")
    body += panel(40, 212, 550, 88, "LlmAgent：调用模型，记录回复", ["文本回答 / 一批工具调用"])
    body += arrow("M590 256 H678")
    body += panel(686, 212, 234, 88, "文本回答", ["final_answer"], "#b45309")
    body += arrow("M315 300 V334")
    body += panel(40, 342, 550, 88, "LlmAgent：整批申请工具额度", ["额度不够：整批 not_run，一个都不执行"])
    body += arrow("M590 386 H678")
    body += panel(686, 342, 234, 88, "额度不足", ["budget.tool_calls"], "#b45309")
    body += arrow("M315 430 V464")
    body += panel(40, 472, 550, 88, "执行工具，记录全部结果", ["成功与错误都带原调用 ID"], "#0f766e")
    body += arrow("M40 516 H20 V126 H36")
    body += text(480, 612, "循环箭头：结果写回后再检查预算。模型接口出错时运行以错误码结束。", 17, "#475569")
    save("r01-loop-control.svg", "循环在框架里，预算在行动前检查", "LlmAgent 在每次请求模型前检查循环上限和预算，工具调用按整批申请额度，工具结果写回后继续下一次请求。", 644, body)

    good, denied = rows["two-tools"], rows["batch-budget"]
    body = ""
    for x, row, color, title in [(40, good, "#0f766e", "工具额度充足"), (500, denied, "#b45309", "只剩一次工具额度")]:
        body += panel(x, 86, 420, 110, title, ["一条模型回复：read-1、read-2"], color)
        body += arrow("M{} 196 V232".format(x + 210))
        status = "文件内容" if row is good else "not_run（budget.tool_calls）"
        body += panel(x, 240, 420, 110, "两条工具结果", ["read-1 → " + status, "read-2 → " + status], color)
        body += arrow("M{} 350 V386".format(x + 210))
        body += panel(x, 394, 420, 142, row["stop"],
                      ["读取尝试：{}；成功：{}".format(row["read_attempts"], row["read_successes"]),
                       "模型调用：{}；会话事件：{}".format(row["model_calls"], row["session_events"])], color)
    body += text(480, 583, "调用 ID 关联每条结果；整批预算检查先于任何工具执行。", 18, "#475569")
    save("r01-call-pairing.svg", "同一轮两个调用，各自得到一条结果", "工具额度充足时读取两次；额度不足时整批不执行、没有读取，两条结果都保留原调用 ID。", 616, body)
