"""R07 figures generated only from checked source and actual run evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r07-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/skill-loading"
    for filename, expected in evidence["source_sha256"].items():
        if hashlib.sha256((package / filename).read_bytes()).hexdigest() != expected:
            raise ValueError("R07 evidence is stale; run verify-agent-skills.py")
    rows = {row["scenario"]: row for row in evidence["scenarios"]}
    normal, repeat, denied = (rows[name] for name in ("normal", "repeat", "permission"))

    body = panel(40, 82, 420, 130, "启动：发现技能目录", ["rust-review@1.0.0", "sql-style@1.0.0", "只向模型展示名称、说明与版本"])
    body += panel(500, 82, 420, 130, "SKILL.md 留在本地", ["YAML 元信息 + Markdown 正文", "保存内容摘要，按需重新核对"], "#64748b")
    body += arrow("M250 212 V254")
    body += panel(40, 262, 420, 116, "模型提出 load_skill 请求", ["call-1 → rust-review", "经 ExecuteTools 分派"], "#2563eb")
    body += arrow("M460 320 H494")
    body += panel(500, 262, 420, 116, "应用：校验、核对与限额", ["注册名称 · SHA-256 · 注入预算", "按调用 ID 返回来源和正文"], "#0f766e")
    body += arrow("M710 378 V420")
    body += panel(500, 428, 420, 116, "tool_result 进入消息历史", ["完整正文进入当前会话", "sql-style 正文没有进入上下文"], "#0f766e")
    body += panel(40, 428, 420, 116, "下一轮读取目标代码", ["再给出固定规则的审查回答", "模型轮次：{}；加载正文：{} 份".format(normal["state"]["model_turns"], len(normal["state"]["loaded"]))])
    body += arrow("M500 486 H466")
    body += text(480, 594, "目录先出现，正文后进入；工具循环与调用 ID 契约沿用 R02。", 18, "#475569")
    save("r07-progressive-loading.svg", "把发现、加载与使用分成可观察的步骤", "启动时只展示两份技能的元信息，模型请求后按调用 ID 加载 rust-review 正文，随后读取代码。", 624, body)

    values = [
        ("两份技能的目录文本", normal["catalog_bytes"], "#2563eb"),
        ("两份技能的全部正文", normal["all_instructions_bytes"], "#64748b"),
        ("normal 注入的正文", normal["state"]["injected_bytes"], "#0f766e"),
        ("repeat 累计注入的正文", repeat["state"]["injected_bytes"], "#b45309"),
    ]
    maximum = max(value for _, value, _ in values)
    body = ""
    for index, (label, value, color) in enumerate(values):
        y = 100 + index * 96
        body += text(190, y + 24, label, 19, color, True)
        width = 470 * value / maximum
        body += '<rect x="390" y="{}" width="{}" height="36" rx="5" fill="{}"/>'.format(y, width, color)
        body += text(390 + width + 40, y + 25, str(value), 18, color, True)
    body += panel(40, 494, 880, 102, "同一份正文只累计一次", ["repeat 实际请求加载 {} 次，注入 {} 份正文。".format(repeat["state"]["load_requests"], len(repeat["state"]["loaded"])),
                    "比较的是 UTF-8 文本字节，不是 token；工具消息外壳仍有额外开销。"], "#0f766e")
    body += text(480, 639, "数据来自 R07 实际运行；两份目录和两份正文是不同层次的文本，不能相加当总上下文。", 16, "#475569")
    save("r07-context-bytes.svg", "只注入相关正文，重复加载不重复注入", "柱长来自真实 UTF-8 字节统计，重复加载与首次加载的正文累计字节相同。", 668, body)

    body = panel(40, 86, 880, 104, "故障注入：技能声明 allowed-tools 并要求写文件", ["技能正文成功加载，模型随后提出 write_file 请求。"], "#b45309")
    body += arrow("M480 190 V230")
    body += panel(40, 238, 880, 112, "应用策略仍是 allow_write = false", ["World.dispatch 在文件写入入口检查权限", "加载代码没有修改策略字段"], "#2563eb")
    body += arrow("M480 350 V390")
    body += panel(40, 398, 880, 112, "按原调用 ID 返回 permission_denied", ["写入尝试：{}；review.txt 是否产生：{}".format(denied["state"]["write_attempts"], "是" if denied["review_file_exists"] else "否"),
                     "目标代码是否保持原样：{}".format("是" if denied["source_unchanged"] else "否")], "#b91c1c")
    body += text(480, 559, "验证的是这一份应用的执行边界；技能内容质量与真实模型行为另行评估。", 18, "#475569")
    save("r07-permission-boundary.svg", "技能内容进入上下文，执行权限仍由应用决定", "故障场景成功加载带写入要求的技能，但写入请求在应用入口被拒绝，实际写入次数为零。", 590, body)
