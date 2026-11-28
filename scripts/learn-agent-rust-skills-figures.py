"""R07 figures (ADK-Rust 3.0 / adk-skill), generated only from checked source and actual run evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r07-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/skill-loading"
    for filename, expected in evidence["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("R07 evidence is stale; run verify-agent-skills.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    normal, repeat, truncated, injected, denied = (
        rows[name] for name in ("normal", "repeat", "truncated", "auto-inject", "permission"))

    body = panel(40, 82, 420, 130, "启动：load_skill_index", ["扫描 .skills/，解析 frontmatter", "索引保存元信息、正文与内容摘要"])
    body += panel(500, 82, 420, 130, "每次请求前：SkillToolset", ["加一条技能使用说明（不入会话）", "工具：list_skills / load_skill / load_skill_resource"], "#64748b")
    body += arrow("M250 212 V254")
    body += panel(40, 262, 420, 116, "L1：list_skills", ["名称、说明、摘要", "目录里 {} 份技能".format(normal["catalog"])], "#2563eb")
    body += arrow("M460 320 H494")
    body += panel(500, 262, 420, 116, "L2：load_skill(rust-review)", ["正文作为工具结果进入会话", "激活记录写进会话状态"], "#0f766e")
    body += arrow("M710 378 V420")
    body += panel(500, 428, 420, 116, "L3：load_skill_resource（需要时）", ["只读 references/ assets/ scripts/", "路径不出技能目录"], "#0f766e")
    body += panel(40, 428, 420, 116, "读取 src/lib.rs，给出审查", ["sql-style 正文没有进入会话", "进入会话的正文：{} 字节".format(normal["skill_text_bytes"])])
    body += arrow("M500 486 H466")
    body += text(480, 594, "目录、正文、资源分三层进入；每一层都是一次工具往返。", 18, "#475569")
    save("r07-progressive-loading.svg", "把发现、加载与使用分成可观察的步骤",
         "启动时建索引；模型先用 list_skills 看目录，再用 load_skill 取 rust-review 正文，需要时读附带资源，随后读取代码。", 624, body)

    values = [
        ("normal：加载 1 次", normal["skill_text_bytes"], "#0f766e"),
        ("repeat：加载 2 次", repeat["skill_text_bytes"], "#b45309"),
        ("truncated：12 字符上限", truncated["skill_text_bytes"], "#b91c1c"),
        ("auto-inject：放进用户消息", injected["skill_text_bytes"], "#2563eb"),
    ]
    maximum = max(value for _, value, _ in values)
    body = ""
    for index, (label, value, color) in enumerate(values):
        y = 100 + index * 96
        body += text(190, y + 24, label, 19, color, True)
        width = 470 * value / maximum
        body += '<rect x="390" y="{}" width="{}" height="36" rx="5" fill="{}"/>'.format(y, width, color)
        body += text(390 + width + 40, y + 25, str(value), 18, color, True)
    body += panel(40, 494, 880, 102, "正文不去重，超长被截断", ["repeat 加载 {} 次，正文进入会话 {} 字节，是一次的两倍。".format(repeat["load_skill_calls"], repeat["skill_text_bytes"]),
                    "统计的是 UTF-8 字节，不是 token；工具结果的外壳另有开销。"], "#0f766e")
    body += text(480, 639, "数据来自 R07 实际运行。", 16, "#475569")
    save("r07-context-bytes.svg", "进入会话的技能正文有多少",
         "柱长来自真实 UTF-8 字节统计：重复加载使正文翻倍，截断只留下开头，自动注入把正文放进用户消息。", 668, body)

    body = panel(40, 86, 880, 104, "故障注入：技能声明 allowed-tools: write_file，正文要求写文件", ["load_skill 成功，激活记录写入会话状态"], "#b45309")
    body += arrow("M480 190 V230")
    body += panel(40, 238, 880, 112, "可见：write_file 从宿主工具表取出，加进模型的工具列表", ["加载前的请求里没有它；加载后的请求里有了"], "#2563eb")
    body += arrow("M480 350 V390")
    body += panel(40, 398, 880, 112, "获准：应用策略拒绝 write_file，结果 refused", ["写入次数：{}；review.txt 是否产生：{}".format(denied["writes"], "是" if denied["review_txt"] else "否")], "#b91c1c")
    body += text(480, 559, "技能决定工具是否可见，执行仍由应用策略决定。", 18, "#475569")
    save("r07-permission-boundary.svg", "技能能让工具出现，不能让工具获准",
         "带 allowed-tools 的技能激活后，write_file 出现在模型的工具列表里；模型调用它时应用策略拒绝，实际写入为零。", 590, body)
