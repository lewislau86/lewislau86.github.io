"""R08 diagrams generated from verified sources and actual scenario evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r08-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/context-compaction"
    for filename, expected in evidence["source_sha256"].items():
        if hashlib.sha256((package / filename).read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R08 evidence; run verify-agent-compaction.py")
    rows = {r["scenario"]: r for r in evidence["scenarios"]}
    normal = rows["normal"]
    stage = normal["state"]["stages"][0]

    body = panel(40, 86, 410, 114, "准备模型请求", ["核对工具调用与结果是否成组", "保持当前历史不变"])
    body += arrow("M450 143 H503")
    body += panel(510, 86, 410, 114, "先归档原始 JSONL", ["每条消息都有稳定的来源键", "保存大小与 SHA-256"], "#0f766e")
    body += arrow("M715 200 V245")
    body += panel(510, 254, 410, 114, "大结果先落盘", ["注册引用 + 少量正文预览", "后续可以按字符分段读取"], "#0f766e")
    body += arrow("M510 311 H457")
    body += panel(40, 254, 410, 114, "旧结果再占位", ["保留角色和工具调用 ID", "原始正文仍在归档中"], "#2563eb")
    body += arrow("M245 368 V413")
    body += panel(40, 422, 410, 114, "仍超触发线：生成摘要", ["事实值 + 原消息键 + 内容摘要", "有独立的输入与调用预算"], "#b45309")
    body += arrow("M450 479 H503")
    body += panel(510, 422, 410, 114, "验证后提交候选", ["事实 · 来源 · 配对 · 硬预算", "失败则保留当前历史"], "#0f766e")
    body += text(480, 588, "normal 后续：重新加载技能 → 重新读取源码 → 输出结论", 21, "#2563eb", True)
    body += text(480, 626, "graph-flow 推进节点；压缩策略与预算由应用实现。", 18, "#475569")
    save("r08-compaction-pipeline.svg", "先保留原文，再准备下一次模型输入", "应用归档后依次处理大结果、旧结果和历史摘要，候选通过校验后才进入下一次模型调用。", 654, body)

    original = rows["archive-error"]["state"]["items"]
    request = original[2]["message"]["tool_calls"]
    assert len(request) == 2 and original[3]["message"]["id"] == request[0]["id"]
    assert original[4]["message"]["id"] == request[1]["id"]
    body = panel(40, 86, 880, 118, "m2：一条 assistant，两个调用", ["old-skill → load_skill", "old-source → read_file(src/first.rs)"])
    body += arrow("M260 204 V246")
    body += arrow("M700 204 V246")
    body += panel(40, 254, 420, 114, "m3：old-skill 的结果", ["审查方法与版本", "调用 ID 对应 old-skill"], "#0f766e")
    body += panel(500, 254, 420, 114, "m4：old-source 的结果", ["目标路径与真实文件内容", "调用 ID 对应 old-source"], "#0f766e")
    body += text(480, 405, "三个框共同构成一个完整消息组，不能从中间切开。", 21, "#b45309", True)
    body += '<path d="M40 434 H920" stroke="#94a3b8" stroke-dasharray="8 6"/>'
    body += panel(40, 466, 880, 114, "normal 留下的最近两个完整组", ["m8 + m9：recent-notes 请求与结果", "m10：用户要求继续；更早的完整组进入摘要范围"], "#2563eb")
    body += text(480, 626, "数据来自同一起点的 archive-error 历史与 normal 压缩结果。", 17, "#475569")
    save("r08-message-groups.svg", "按完整消息组选择摘要切口", "同一 assistant 的两个工具调用必须分别匹配结果，再进入下一消息组；normal 保留最近两个完整组。", 654, body)

    values = [("原始模型历史", stage["before"], "#64748b"),
              ("大结果落盘后", stage["externalized"], "#2563eb"),
              ("旧结果占位后", stage["micro"], "#b45309"),
              ("事实摘要提交后", stage["after"], "#0f766e")]
    body = ""
    for n, (label, value, color) in enumerate(values):
        y = 88 + n * 82
        width = 455 * value / values[0][1]
        body += text(174, y + 24, label, 20, color, True)
        body += '<rect x="350" y="{}" width="{}" height="34" rx="5" fill="{}"/>'.format(y, width, color)
        body += text(350 + width + 46, y + 24, str(value), 19, color, True)
    naive = rows["naive-trim"]["state"]["stages"][0]
    body += panel(40, 444, 880, 112, "只看短不短，还不够", ["normal：{} 字节，保留路径并完成源码重读。".format(stage["after"]),
                 "naive-trim：{} 字节，丢失路径，停止于 missing_evidence。".format(naive["after"])], "#b45309")
    body += text(480, 602, "同一初始历史；单位为序列化 Message JSON 的 UTF-8 字节，不是 token。", 17, "#475569")
    save("r08-context-bytes.svg", "控制输入体积，同时保留继续行动的依据", "柱长来自 normal 实际阶段字节数，naive-trim 的历史更短但丢失了目标路径。", 632, body)

    omitted, invented = rows["omit-fact"], rows["invent-fact"]
    body = panel(40, 86, 880, 114, "应用记录的四项事实", ["目标路径 · 源码发现 · 测试状态 · 技能线索", "每项事实都指向原消息键与正文 SHA-256"], "#2563eb")
    body += arrow("M480 200 V244")
    body += panel(40, 252, 880, 114, "检查摘要候选", ["严格 schema → 逐项比较事实 → 核对来源", "再检查消息配对与输入硬预算"], "#b45309")
    body += arrow("M260 366 V412")
    body += arrow("M700 366 V412")
    body += panel(40, 420, 420, 142, "遗漏 / 虚构：停止", ["Agent 调用：{} / {}".format(omitted["state"]["model_calls"], invented["state"]["model_calls"]),
                 "原消息历史保持不变", "错误码：summary_facts"], "#b91c1c")
    body += panel(500, 420, 420, 142, "normal：提交", ["摘要调用：{}".format(normal["summary_calls"]),
                 "技能重载：{}".format(normal["state"]["reloads"]),
                 "源码重读：{}".format(normal["state"]["reads"])], "#0f766e")
    body += text(480, 612, "本例验证已知事实的保留；任意自然语言摘要的语义质量需另行评估。", 17, "#475569")
    save("r08-summary-gate.svg", "摘要先作为候选，再进入活跃历史", "遗漏目标路径或虚构测试通过均触发 summary_facts，Agent 调用数为零且原历史不变。", 642, body)
