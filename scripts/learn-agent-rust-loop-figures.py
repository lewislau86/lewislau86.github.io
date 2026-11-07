"""R01 figures, called by generate-learn-agent-rust-figures.py --lesson R01."""

import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r01-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/agent-loop.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R01 evidence is stale; run verify-learn-agent-rust-loop.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    normal = rows["normal"]
    body = ""
    roles = [("user", "读取 README，告诉我启动命令"),
             ("assistant · 请求", 'read-1 / read_file("README.md")'),
             ("tool · 结果", "read-1 / 启动命令：cargo run"),
             ("assistant · 回答", "README 里的启动命令是：cargo run")]
    for i, (role, content) in enumerate(roles):
        y = 80 + i * 112
        body += panel(40, y, 620, 88, role, [content], "#0f766e" if i == 2 else "#2563eb")
        if i < 3:
            body += arrow("M350 {} V{}".format(y + 88, y + 107))
    body += panel(704, 108, 216, 128, "模型轮次", [str(normal["model_turns"])], "#2563eb")
    body += panel(704, 266, 216, 128, "工具执行", [str(normal["tool_calls"])], "#0f766e")
    body += panel(704, 424, 216, 128, "历史消息", [str(normal["messages"])], "#b45309")
    body += text(480, 594, "计数与调用 ID 来自 normal 场景实际运行；模型为固定规则替身。", 17, "#475569")
    save("r01-message-cycle.svg", "一次文件读取，经过两轮模型调用", "请求和结果通过 read-1 关联。正常路径产生四条消息、两轮模型调用和一次工具执行。", 622, body)

    body = panel(40, 82, 550, 88, "检查模型预算", ["model_turns 是否还有剩余额度？"])
    body += arrow("M590 126 H678")
    body += panel(686, 82, 234, 88, "额度耗尽", ["ModelBudget"], "#b45309")
    body += arrow("M315 170 V204")
    body += panel(40, 212, 550, 88, "调用模型，记录响应", ["Final 文本 / ToolCalls 列表"])
    body += arrow("M590 256 H678")
    body += panel(686, 212, 234, 88, "最终文本", ["FinalAnswer"], "#b45309")
    body += arrow("M315 300 V334")
    body += panel(40, 342, 550, 88, "校验调用 ID 与整批工具额度", ["异常 ID 停止；超额整批拒绝"])
    body += arrow("M590 386 H678")
    body += panel(686, 342, 234, 88, "入口拒绝", ["InvalidCall / ToolBudget"], "#b45309")
    body += arrow("M315 430 V464")
    body += panel(40, 472, 550, 88, "顺序执行工具，追加所有结果", ["成功与错误都带原调用 ID"], "#0f766e")
    body += arrow("M40 516 H20 V126 H36")
    body += text(480, 612, "循环箭头：追加结果后重新检查模型预算。模型接口错误另以 ModelError 停止。", 17, "#475569")
    save("r01-loop-control.svg", "循环由应用推进，预算在行动前检查", "模型预算在调用前检查，工具 ID 和整批额度在执行前检查，工具结果写回后继续下一轮。", 644, body)

    good, denied = rows["two-tools"], rows["batch-budget"]
    body = ""
    for x, row, color, title in [(40, good, "#0f766e", "工具额度充足"), (500, denied, "#b45309", "只剩一次工具额度")]:
        body += panel(x, 86, 420, 110, title, ["一个 assistant 消息：read-1、read-2"], color)
        body += arrow("M{} 196 V232".format(x + 210))
        status = "文件内容" if row is good else "tool_budget 错误"
        body += panel(x, 240, 420, 110, "两个 tool 结果", ["read-1 → " + status, "read-2 → " + status], color)
        body += arrow("M{} 350 V386".format(x + 210))
        body += panel(x, 394, 420, 142, row["stop"],
                      ["读取尝试：{}；成功：{}".format(row["read_attempts"], row["read_successes"]),
                       "模型轮次：{}；消息：{}".format(row["model_turns"], row["messages"])], color)
    body += text(480, 583, "调用 ID 关联每份结果；整批预算检查先于任何工具执行。", 18, "#475569")
    save("r01-call-pairing.svg", "同一轮两个调用，各自得到一个结果", "工具额度充足时读取两次，额度不足时整批拒绝且没有读取，两个结果都保留原调用 ID。", 616, body)
