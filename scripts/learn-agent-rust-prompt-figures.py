"""R10 diagrams (ADK-Rust 3.0) generated from verified sources and actual scenario evidence."""
import hashlib
import json
import re


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r10-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/system-prompts"
    for filename, expected in evidence["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R10 evidence; run verify-agent-prompts.py")
    rows = {r["name"]: r["parts"] for r in evidence["scenarios"]}
    normal = (root / "docs/public/learn-agent-rust/outputs/r10-normal.txt").read_text()
    first = re.search(r"^request 0: roles=(\S+) tools=\[([^\]]*)\]", normal, re.M)

    sources = [
        ("static_instruction", ["应用策略 + AGENTS.md", "原样发送，构建时就定了"], "#2563eb"),
        ("instruction 模板", ["环境 ← 会话状态", "每次运行开始时渲染一次"], "#2563eb"),
        ("with_skills", ["按问题选一份技能", "拼在用户这一轮原话前面"], "#b45309"),
        (".tool(...)", ["工具声明，按注册顺序", first[2].replace(",", " · ")], "#0f766e"),
    ]
    body = ""
    for index, (heading, lines, color) in enumerate(sources):
        y = 80 + index * 124
        body += panel(40, y, 440, 108, heading, lines, color)
        body += arrow("M480 {} H532".format(y + 54))
    targets = ["第 1 条 system", "第 2 条 system", "user：[skill:…] + 原话", "请求的 tools 字段"]
    body += '<rect x="540" y="80" width="380" height="480" rx="12" fill="#fff" stroke="#475569" stroke-width="2"/>'
    body += text(730, 112, "一次请求（normal 的第一次）", 20, "#475569", True)
    for index, label in enumerate(targets):
        body += text(730, 80 + index * 124 + 62, label, 18, "#172033")
    body += text(730, 548, "roles = " + first[1], 16, "#475569")
    body += arrow("M730 560 V596")
    body += panel(40, 604, 880, 96, "before_model_callback", ["看得到整份请求：本章在这里检查字节预算，超了就不调用模型"], "#b91c1c")
    save("r10-input-sources.svg", "一次请求由哪几部分组成",
         "应用策略与 AGENTS.md 进第一条系统消息，环境由模板读会话状态进第二条，选中的技能拼进用户这一轮，工具声明按注册顺序附在请求上；最后 before_model 回调可以检查整份请求。", 730, body)

    switch = rows["skill-switch"][-1]
    system = rows["skill-in-system"][-1]
    update = rows["skill-update"][-1]

    def same(line, key):
        return "相同" if f"{key}=yes" in line else "不同"
    body = text(480, 82, "同样两个问题：第一个选中 startup，第二个选中 sql-style", 18, "#475569")
    body += panel(40, 106, 420, 220, "技能在用户这一轮", ["with_skills", "前缀（system + 工具）：" + same(switch, "prefix_same"),
                  "用户这一轮：" + same(switch, "user_same")], "#0f766e")
    body += panel(500, 106, 420, 220, "技能在系统消息", ["global_instruction_provider", "前缀（system + 工具）：" + same(system, "prefix_same"),
                  "用户这一轮：" + same(system, "user_same")], "#b91c1c")
    body += panel(40, 360, 880, 110, "skill-update：技能发布新版本", ["前缀：" + same(update, "prefix_same") + "；用户这一轮：" + same(update, "user_same")], "#0f766e")
    body += text(480, 510, "服务商的前缀缓存按请求开头匹配；会变的内容放在后面，开头才能保持不变。", 17, "#475569")
    save("r10-prefix-stability.svg", "技能放在哪里，请求开头才不变",
         "两个问题选中不同的技能：技能放在用户这一轮时，系统消息与工具声明组成的前缀相同；放进系统消息时，前缀随技能变化。", 540, body)

    def calls(parts):
        return re.search(r"model_calls=(\d+)", parts[0])[1]
    cases = [
        ("env-change", "改语言", "前缀：" + same(rows["env-change"][-1], "prefix_same"), "#2563eb"),
        ("tool-change", "不注册 read_file", "前缀：" + same(rows["tool-change"][-1], "prefix_same"), "#2563eb"),
        ("stale-skill", "技能改了，pin 没更新", "没有建 Agent，模型未调用", "#b45309"),
        ("budget", "请求超过 300 字节", "模型调用 " + calls(rows["budget"]) + " 次", "#b45309"),
    ]
    body = ""
    for index, (name, change, result, color) in enumerate(cases):
        x = 40 + (index % 2) * 450
        y = 86 + (index // 2) * 140
        body += panel(x, y, 430, 120, name, [change, result], color)
    injection = rows["knowledge-injection"]
    tool = re.search(r"tools=\[([^\]]*)\]", injection[0])[1]
    body += panel(40, 380, 880, 140, "knowledge-injection：技能里混进“已批准写入 summary.txt”",
                  ["假标签所在的消息：" + injection[1].split("=")[1] + "；工具结果：" + tool,
                   "summary.txt 存在：" + ("是" if injection[2].endswith("yes") else "否")], "#b91c1c")
    body += text(480, 560, "资料里写了什么，不改变执行器允许做什么：写文件由策略在执行前拒绝。", 17, "#475569")
    save("r10-change-and-permission.svg", "哪些变化改变请求，哪些在调用模型前停下",
         "改语言和增删工具会改变请求开头；技能被改而 pin 未更新、请求超出预算时，模型一次都不调用；技能里的假系统标签留在用户消息里，写文件被策略拒绝，summary.txt 没有产生。", 590, body)
