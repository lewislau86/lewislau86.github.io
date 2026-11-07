"""Generate course schematics and R00/R03 figures from verified run data.

Reference website figures are preserved separately by sync-learn-agent-rust-assets.py.
"""

import argparse
from html import escape
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/learn-agent-rust/figures/runtime-architecture.svg"


def text(x, y, content, size=18, color="#172033", bold=False):
    weight = "700" if bold else "400"
    return '<text x="{}" y="{}" text-anchor="middle" font-size="{}" fill="{}" font-weight="{}">{}</text>'.format(x, y, size, color, weight, escape(content))


def box(x, y, width, height, title, subtitle, color="#2563eb"):
    return ('<rect x="{}" y="{}" width="{}" height="{}" rx="12" fill="#fff" stroke="{}" stroke-width="2"/>'.format(x, y, width, height, color)
            + text(x + width / 2, y + 31, title, 20, color, True)
            + text(x + width / 2, y + 57, subtitle, 16, "#475569"))


def arrow(points, color="#64748b"):
    return '<path d="{}" fill="none" stroke="{}" stroke-width="2.5" marker-end="url(#arrow)"/>'.format(points, color)


def runtime_architecture():
    body = text(480, 38, "Rust Agent 的目标架构：模型、工具与状态如何连接", 24, bold=True)
    body += '<rect x="24" y="68" width="624" height="608" rx="16" fill="#eff6ff" stroke="#93c5fd" stroke-dasharray="7 5"/>'
    body += text(336, 98, "一个 Rust 进程 · 一个 Tokio runtime", 17, "#2563eb", True)
    body += box(74, 116, 524, 76, "入口与应用策略", "CLI · 权限 · 预算 · 审批 · 停止条件")
    body += arrow("M336 192 V222")
    body += box(74, 226, 524, 76, "graph-flow：图执行与会话", "Task · 路由 · Session · Storage")
    body += arrow("M336 302 V332")
    body += box(74, 336, 524, 76, "应用节点与消息状态", "ModelTurn · ExecuteTools · 调用 ID · 结果回传")
    body += arrow("M336 412 V444")
    body += arrow("M74 374 H44 V612 H70")
    body += box(74, 448, 524, 84, "langchain-rust", "模型 trait · 消息 · 结构化调用结果")
    body += box(74, 570, 524, 84, "工具注册与执行", "参数校验 · 权限与超时 · 有界结果", "#0f766e")
    body += arrow("M598 493 H690")
    body += box(694, 448, 238, 84, "模型提供方", "假模型或外部服务", "#0f766e")
    body += arrow("M598 264 H690")
    body += box(694, 226, 238, 90, "会话存储", "内存 / 后续 PostgreSQL", "#b45309")
    body += text(806, 344, "成功保存形成检查点", 16, "#b45309")
    body += arrow("M598 612 H690")
    body += box(694, 570, 238, 84, "限定工作区", "练习文件 / 外部工具", "#0f766e")
    body += text(480, 726, "示意图：模块按章节逐步实现；外部服务与恢复能力分别验收。", 17, "#475569")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="750" viewBox="0 0 960 750" role="img" aria-labelledby="title desc">'
           '<title id="title">Rust Agent 的课程目标架构</title>'
           '<desc id="desc">应用策略和 graph-flow 推进模型与工具节点。模型接口连接模型提供方，工具操作限定工作区，会话通过存储保存。目标模块将逐章实现。</desc>'
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#64748b"/></marker></defs>'
           '<rect width="960" height="750" rx="16" fill="#f8fafc"/>'
           '<g font-family="PingFang SC, Microsoft YaHei, sans-serif">' + body + '</g></svg>\n')
    ET.fromstring(svg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print("Generated " + str(OUT.relative_to(ROOT)))


def panel(x, y, w, h, heading, lines, color="#2563eb"):
    body = '<rect x="{}" y="{}" width="{}" height="{}" rx="12" fill="#fff" stroke="{}" stroke-width="2"/>'.format(x, y, w, h, color)
    body += text(x + w / 2, y + 32, heading, 21, color, True)
    for index, line in enumerate(lines):
        body += text(x + w / 2, y + 65 + index * 29, line, 18, "#475569")
    return body


def save_figure(name, title, description, height, body):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{}" viewBox="0 0 960 {}" role="img" aria-labelledby="title desc">'.format(height, height)
           + '<title id="title">' + escape(title) + '</title><desc id="desc">' + escape(description) + '</desc>'
           + '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#64748b"/></marker></defs>'
           + '<rect width="960" height="{}" rx="16" fill="#f8fafc"/>'.format(height)
           + '<g font-family="PingFang SC, Microsoft YaHei, sans-serif">' + text(480, 40, title, 25, bold=True) + body + '</g></svg>\n')
    ET.fromstring(svg)
    path = OUT.parent / name
    path.write_text(svg, encoding="utf-8")
    print("Generated " + str(path.relative_to(ROOT)))


def request_and_action():
    body = panel(48, 78, 864, 86, "用户提出目标", ["读取 README.md，告诉我如何启动项目。"])
    body += arrow("M245 164 V207")
    body += panel(48, 214, 390, 142, "模型返回：行动请求", ['read_file("README.md")', "此时只有名称、参数和调用 ID。"])
    body += arrow("M438 284 H513")
    body += panel(522, 214, 390, 142, "程序执行：真实读取", ["检查策略，再调用 std::fs。", "文件内容或错误成为工具结果。"], "#0f766e")
    body += arrow("M717 356 V398 H245 V438")
    body += text(480, 425, "工具结果写回消息历史", 18, "#0f766e")
    body += panel(48, 446, 864, 92, "模型再次获得上下文", ["看到 README 的内容后，才能据此生成回答。"])
    body += text(480, 579, "示意图：请求动作、允许动作与执行动作是不同的步骤。", 18, "#475569")
    save_figure("r00-request-and-action.svg", "从一句请求，到一次真实的文件读取", "模型提出工具请求，应用检查策略并读取文件，结果交回模型形成回答。", 608, body)


def message_trace():
    evidence = json.loads((ROOT / "scripts/data/learn-agent-rust/r00-results.json").read_text())
    source = ROOT / "docs/public/learn-agent-rust/code/architecture-and-setup.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R00 evidence is stale; rerun verify-learn-agent-rust.py")
    normal = evidence["scenarios"][0]
    names = ["提出问题", "请求读取 README", "回传文件内容", "给出启动命令"]
    body = ""
    for index, role in enumerate(normal["roles"]):
        y = 80 + 84 * index
        color = "#0f766e" if role == "tool" else "#2563eb"
        body += '<rect x="48" y="{}" width="864" height="62" rx="10" fill="#fff" stroke="{}" stroke-width="2"/>'.format(y, color)
        body += text(255, y + 38, "{} · {}".format(index + 1, role), 21, color, True)
        body += text(638, y + 38, names[index], 21)
        if index < len(normal["roles"]) - 1:
            body += arrow("M480 {} V{}".format(y + 62, y + 79))
    body += text(480, 452, "真实运行对照：应用是否进行了文件读取？", 22, bold=True)
    body += text(205, 491, "场景", 18, "#475569")
    body += text(480, 491, "读取尝试 / 读取成功", 18, "#475569")
    body += text(752, 491, "任务结果", 18, "#475569")
    labels = {"normal": "正常", "deny": "策略拒绝", "missing-file": "文件不存在"}
    for index, row in enumerate(evidence["scenarios"]):
        y = 532 + 39 * index
        body += text(205, y, labels[row["name"]], 19)
        body += text(480, y, "{} / {}".format(row["read_attempts"], row["read_successes"]), 20, "#0f766e", True)
        body += text(752, y, row["outcome"], 19)
    body += text(480, 658, "数据来自 R00 的固定规则模型与临时文件实验；未请求外部模型。", 17, "#475569")
    save_figure("r00-message-trace.svg", "一次往返，消息历史逐条增加", "消息顺序与读取计数来自 R00 实际运行记录。拒绝时读取次数为零，缺失文件时读取尝试失败。", 688, body)


def state_lifetimes():
    body = panel(32, 92, 280, 186, "消息历史", ["用户说了什么？", "请求了哪个工具？", "工具返回了什么？"])
    body += panel(340, 92, 280, 186, "运行控制状态", ["已经调用几轮？", "是否允许读取？", "当前应该停止吗？"], "#0f766e")
    body += panel(648, 92, 280, 186, "持久化检查点", ["保存恢复所需状态", "记录恢复位置与版本", "成功写入存储才成立"], "#b45309")
    body += '<path d="M48 326 H912" stroke="#94a3b8" stroke-dasharray="8 6" stroke-width="2"/>'
    body += text(480, 320, "当前进程退出", 20, "#475569", True)
    body += text(326, 379, "本章的内存状态随进程结束而丢失", 20, "#2563eb")
    body += text(788, 379, "后续章节单独验证恢复", 18, "#b45309")
    body += text(480, 436, "示意图：消息放进 Vec，并不会自动成为数据库中的检查点。", 18, "#475569")
    save_figure("r00-state-lifetimes.svg", "看过的内容、控制进度与恢复记录，分别放在哪里？", "消息历史和控制状态可以存放在内存。跨进程恢复需要成功保存恢复所需状态，本章不实现持久化。", 468, body)


def control_flow():
    body = text(480, 91, "固定工作流：下一步由事先写好的程序决定", 22, "#2563eb", True)
    body += panel(38, 122, 240, 104, "接收请求", ["输入项目位置"])
    body += panel(360, 122, 240, 104, "读取 README", ["预先固定的动作"])
    body += panel(682, 122, 240, 104, "输出说明", ["按固定方式整理"])
    body += arrow("M278 174 H351") + arrow("M600 174 H673")
    body += text(480, 310, "Agent 循环：程序根据模型的结构化结果选择分支", 22, "#0f766e", True)
    body += panel(38, 354, 240, 126, "当前上下文", ["问题、已有结果", "及可用工具"])
    body += panel(360, 354, 240, 126, "调用模型", ["返回工具请求", "或最终回答"], "#0f766e")
    body += panel(682, 354, 240, 126, "检查并执行工具", ["策略允许后执行", "把结果回传"], "#0f766e")
    body += arrow("M278 416 H351") + arrow("M600 416 H673")
    body += text(641, 395, "工具", 17, "#0f766e")
    body += arrow("M802 480 V535 H158 V487")
    body += text(480, 528, "追加结果，再判断下一步", 18, "#0f766e")
    body += arrow("M480 480 V584")
    body += text(480, 615, "最终回答 → 停止", 22, "#b45309", True)
    body += text(480, 667, "图节点也能承载这些分支；画成图本身不会产生模型决策。", 18, "#475569")
    save_figure("r00-workflow-and-agent.svg", "写死一条业务路径，还是让模型参与选择下一步？", "上方为固定流程，下方为目标 Agent 循环。图执行器承载路由，应用解释模型的工具请求并检查执行条件。", 696, body)


def permission_routes():
    body = panel(180, 78, 600, 100, "模型提出 ToolCall", ["调用 ID + 工具类型 + 完整参数"])
    body += arrow("M480 178 V210")
    body += panel(180, 218, 600, 95, "应用执行 check_permission", ["按明确规则分类；未命中许可范围则拒绝"])
    body += arrow("M300 313 V343 H167 V373")
    body += arrow("M480 313 V373")
    body += arrow("M660 313 V343 H793 V373")
    body += panel(28, 382, 278, 136, "Allow", ["读取 README.md", "直接调用文件工具"], "#0f766e")
    body += panel(341, 382, 278, 136, "AskApproval", ["写入 notes/summary.txt", "保存请求，返回等待"], "#b45309")
    body += panel(654, 382, 278, 136, "Deny", ["其他动作或超长内容", "生成 denied 工具结果"], "#b91c1c")
    body += text(480, 562, "只有等待分支保留 pending；此时不生成写入工具结果。", 20, "#b45309", True)
    body += text(480, 604, "示意图：本章使用固定文件规则，应用自己决定动作权限。", 18, "#475569")
    save_figure("r03-permission-routes.svg", "一次请求，在执行前分成三条路径", "只读请求直接执行，指定写入等待审批，其余请求直接拒绝；等待期间没有写入结果。", 636, body)


def approval_binding():
    body = panel(30, 86, 420, 226, "pending 保存完整快照", ["当前会话的工作区 scope", "审批序号 + call_id", "工具类型 + 路径 + 写入内容", "每个字段都参与相等比较"], "#b45309")
    body += panel(510, 86, 420, 226, "可信入口提交人工决定", ["展示快照后选择批准或拒绝", "回复必须匹配保存的快照", "不匹配：保留等待状态", "批准身份由外层 UI 负责"])
    body += arrow("M450 200 H501")
    body += arrow("M720 312 V347 H480 V378")
    body += text(480, 347, "匹配后先 take()，移走 pending", 18, "#b45309", True)
    body += panel(30, 390, 420, 130, "人工拒绝", ["不调用文件工具", "返回 declined + 原 call_id"], "#b91c1c")
    body += panel(510, 390, 420, 130, "人工批准", ["执行保存的原始动作", "返回 ok 或 tool_error"], "#0f766e")
    body += text(480, 563, "两条分支都消耗本次审批；执行失败也不恢复已用审批。", 20, bold=True)
    body += text(480, 606, "示意图：状态只在当前进程；跨进程恢复与外部幂等在后续专题验证。", 17, "#475569")
    save_figure("r03-approval-binding.svg", "批准绑定到哪一次动作？", "审批比较会话、序号、调用 ID、工具类型和全部参数；匹配后先消耗，再拒绝或执行保存的动作。", 638, body)


def permission_results():
    evidence = json.loads((ROOT / "scripts/data/learn-agent-rust/r03-results.json").read_text())
    source = ROOT / "docs/public/learn-agent-rust/code/permissions.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R03 evidence is stale; rerun verify-agent-permissions.py")
    body = text(480, 84, "每个场景都先完成一次 README 读取；下表只比较写入与审批状态。", 18, "#475569")
    for x, label in [(155, "场景"), (390, "写入尝试"), (540, "写入成功"), (695, "工具结果数"), (845, "仍在等待")]:
        body += text(x, 135, label, 20, bold=True)
    for index, row in enumerate(evidence["scenarios"]):
        y = 171 + index * 44
        if index % 2 == 0:
            body += '<rect x="28" y="{}" width="904" height="42" rx="6" fill="#e2e8f0"/>'.format(y - 28)
        body += text(155, y, row["name"], 19)
        for x, key in [(390, "write_attempts"), (540, "write_successes"), (695, "tool_results")]:
            body += text(x, y, str(row[key]), 21, "#0f766e", True)
        body += text(845, y, "是" if row["pending"] else "否", 19, "#b45309" if row["pending"] else "#475569")
    body += text(480, 644, "工具结果包含读取结果；审批错配和重复回复不会再生成工具结果。", 18, "#475569")
    body += text(480, 681, "数据来自 R03 的真实文件实验；模型请求与人工回复为固定测试输入。", 17, "#475569")
    save_figure("r03-permission-results.svg", "规则是否生效，用文件调用次数核对", "实际运行的十个场景中，等待、拒绝和参数替换没有写入尝试；批准和重复批准只写一次；写入失败计一次尝试零次成功。", 710, body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson", choices=["R00", "R03", "all"], default="all")
    args = parser.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if args.lesson in ("R00", "all"):
        runtime_architecture()
        request_and_action()
        message_trace()
        state_lifetimes()
        control_flow()
    if args.lesson in ("R03", "all"):
        permission_routes()
        approval_binding()
        permission_results()


if __name__ == "__main__":
    main()
