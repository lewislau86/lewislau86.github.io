"""Generate course schematics and chapter figures from verified run data.

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
    # ADK-Rust 3.0 版（2026-11 迁移）；全书迁移期间，尚未迁移的章节仍按旧版两库实现
    body = text(480, 38, "Rust Agent 的目标架构：ADK-Rust 3.0 的各部分怎样连接", 24, bold=True)
    body += '<rect x="24" y="68" width="624" height="608" rx="16" fill="#eff6ff" stroke="#93c5fd" stroke-dasharray="7 5"/>'
    body += text(336, 98, "一个 Rust 进程 · 一个 Tokio runtime", 17, "#2563eb", True)
    body += box(74, 116, 524, 76, "应用：入口、策略与验收", "DeclarativePolicy · 预算 · 审批 · 任务是否完成")
    body += arrow("M336 192 V222")
    body += box(74, 226, 524, 76, "Runner（adk-runner）", "加载会话 · 装入策略与预算 · 保存事件")
    body += arrow("M336 302 V332")
    body += box(74, 336, 524, 76, "LlmAgent / 图（adk-agent · adk-graph）", "模型 ↔ 工具循环 · 行动前检查策略与预算")
    body += arrow("M336 412 V444")
    body += arrow("M74 374 H44 V612 H70")
    body += box(74, 448, 524, 84, "Llm trait（adk-core · adk-model）", "ScriptedLlm / 规则模型 / 真实服务适配器")
    body += box(74, 570, 524, 84, "FunctionTool（adk-tool）", "schema 校验 · 副作用声明 · 有界结果", "#0f766e")
    body += arrow("M598 493 H690")
    body += box(694, 448, 238, 84, "模型提供方", "脚本模型或外部服务", "#0f766e")
    body += arrow("M598 264 H690")
    body += box(694, 226, 238, 90, "会话与账本", "内存 / SQLite / PostgreSQL", "#b45309")
    body += text(806, 344, "adk-session：事件、检查点、账本", 15, "#b45309")
    body += arrow("M598 612 H690")
    body += box(694, 570, 238, 84, "限定工作区", "练习文件 / 外部工具", "#0f766e")
    body += text(480, 726, "示意图：模块按章节逐步使用；外部服务与恢复能力分别验收。", 17, "#475569")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="750" viewBox="0 0 960 750" role="img" aria-labelledby="title desc">'
           '<title id="title">Rust Agent 的课程目标架构</title>'
           '<desc id="desc">应用的策略与验收在最外层；Runner 管理会话并装入策略和预算；LlmAgent 与图运行模型和工具的循环，在行动前检查策略和预算；Llm trait 连接模型提供方，FunctionTool 操作限定工作区，会话与账本由 adk-session 保存。</desc>'
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
    body += panel(522, 214, 390, 142, "程序执行：真实读取", ["策略允许后，工具读取文件。", "文件内容或错误成为工具结果。"], "#0f766e")
    body += arrow("M717 356 V398 H245 V438")
    body += text(480, 425, "工具结果写回消息历史", 18, "#0f766e")
    body += panel(48, 446, 864, 92, "模型再次获得上下文", ["看到 README 的内容后，才能据此生成回答。"])
    body += text(480, 579, "示意图：请求动作、允许动作与执行动作是不同的步骤。", 18, "#475569")
    save_figure("r00-request-and-action.svg", "从一句请求，到一次真实的文件读取", "模型提出工具请求，应用检查策略并读取文件，结果交回模型形成回答。", 608, body)


def message_trace():
    evidence = json.loads((ROOT / "scripts/data/learn-agent-rust/r00-results.json").read_text())
    package = ROOT / "docs/public/learn-agent-rust/code/architecture-and-setup"
    for name, digest in evidence["source_sha256"].items():
        source = package / name if (package / name).exists() else ROOT / "scripts" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("R00 evidence is stale; rerun verify-learn-agent-rust.py")
    normal = evidence["scenarios"][0]
    names = ["提出问题", "请求读取 README", "回传文件内容", "给出启动命令"]
    body = ""
    for index, role in enumerate(normal["roles"]):
        y = 80 + 84 * index
        color = "#0f766e" if role == "function" else "#2563eb"
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
    body += text(480, 658, "数据来自 R00 的 ScriptedLlm 与临时文件实验；未请求外部模型。", 17, "#475569")
    save_figure("r00-message-trace.svg", "一次往返，消息历史逐条增加", "消息顺序与读取计数来自 R00 实际运行记录。拒绝时读取次数为零，缺失文件时读取尝试失败。", 688, body)


def state_lifetimes():
    body = panel(32, 92, 280, 186, "消息历史", ["用户说了什么？", "请求了哪个工具？", "工具返回了什么？"])
    body += panel(340, 92, 280, 186, "运行控制状态", ["已经调用几次模型？", "是否允许读取？", "当前应该停止吗？"], "#0f766e")
    body += panel(648, 92, 280, 186, "持久化检查点", ["保存恢复所需状态", "记录恢复位置与版本", "成功写入存储才成立"], "#b45309")
    body += '<path d="M48 326 H912" stroke="#94a3b8" stroke-dasharray="8 6" stroke-width="2"/>'
    body += text(480, 320, "当前进程退出", 20, "#475569", True)
    body += text(326, 379, "本章的内存会话随进程结束而丢失", 20, "#2563eb")
    body += text(788, 379, "后续章节单独验证恢复", 18, "#b45309")
    body += text(480, 436, "示意图：会话放在内存里，并不会自动成为数据库中的检查点。", 18, "#475569")
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
    save_figure("r00-workflow-and-agent.svg", "写死一条业务路径，还是让模型参与选择下一步？", "上方为固定流程，下方为 Agent 循环：LlmAgent 根据模型的结构化回复决定是否执行工具，策略检查执行条件。", 696, body)


def permission_routes():
    # ADK-Rust 3.0 版：策略是应用实现的 ToolPolicy，装在 Runner 上，由 LlmAgent 在执行工具前检查
    body = panel(180, 78, 600, 100, "模型提出工具调用", ["调用 ID + 工具名 + 完整参数"])
    body += arrow("M480 178 V210")
    body += panel(180, 218, 600, 95, "LlmAgent 询问 SummaryPolicy（ToolPolicy）", ["只看请求，不做 I/O；未命中允许范围就拒绝"])
    body += arrow("M300 313 V343 H167 V373")
    body += arrow("M480 313 V373")
    body += arrow("M660 313 V343 H793 V373")
    body += panel(28, 382, 278, 136, "Allow", ["读取 README.md", "直接调用工具"], "#0f766e")
    body += panel(341, 382, 278, 136, "RequireApproval", ["写入 notes/summary.txt", "挂起：记入审批记录"], "#b45309")
    body += panel(654, 382, 278, 136, "Deny", ["其他已注册工具的请求", "结果状态 refused"], "#b91c1c")
    body += text(480, 562, "挂起的调用得到 held 结果，本次运行结束；工具没有执行。未注册的工具在策略之前就是 not_run。", 18, "#b45309", True)
    body += text(480, 604, "示意图：本章的策略是固定的文件规则，由应用自己编写。", 18, "#475569")
    save_figure("r03-permission-routes.svg", "一次请求，在执行前分成三条路径", "只读请求直接执行，指定写入挂起等待批准，其余请求直接拒绝；挂起期间工具没有执行。", 636, body)


def approval_binding():
    body = panel(30, 86, 420, 226, "审批记录保存完整请求", ["会话范围：app / user / session", "指纹 = 执行的 Agent + 工具来源与声明", "+ 工具名 + 规范化参数", "调用 ID 不在指纹里"], "#b45309")
    body += panel(510, 86, 420, 226, "审批人按指纹记下决定", ["只对 pending() 里的指纹做决定", "不一致：等待中的调用继续等待", "多出的决定会变成预先批准", "审批人的身份由外层系统负责"])
    body += arrow("M450 200 H501")
    body += arrow("M720 312 V363 H480 V378")
    body += text(480, 347, "下一次运行开始时，取走决定（取走即用掉）", 18, "#b45309", True)
    body += panel(30, 390, 420, 130, "拒绝", ["工具不执行", "结果 refused，带原调用 ID"], "#b91c1c")
    body += panel(510, 390, 420, 130, "批准", ["执行原来那次调用：同一调用 ID、同一参数", "结果 ok 或 failed"], "#0f766e")
    body += text(480, 563, "两条分支都用掉这次决定；执行失败也不退回。", 20, bold=True)
    body += text(480, 606, "示意图：本章审批记录只在内存里；跨进程恢复在后续章节验证。", 17, "#475569")
    save_figure("r03-approval-binding.svg", "批准绑定到哪一次调用？", "审批记录保存完整请求并合成指纹；决定按指纹记录，下一次运行取走决定后拒绝或执行原来那次调用。", 638, body)


def permission_results():
    evidence = json.loads((ROOT / "scripts/data/learn-agent-rust/r03-results.json").read_text())
    package = ROOT / "docs/public/learn-agent-rust/code/permissions"
    for name, digest in evidence["source_sha256"].items():
        source = package / name if (package / name).exists() else ROOT / "scripts" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
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
    body += text(480, 644, "工具结果包含读取结果与“等待批准”的结果；“仍在等待”来自审批记录。", 18, "#475569")
    body += text(480, 681, "数据来自 R03 的真实文件实验；模型请求与审批人的决定为固定输入。", 17, "#475569")
    save_figure("r03-permission-results.svg", "规则是否生效，用文件调用次数核对", "实际运行的十个场景中，等待、拒绝和改了内容的批准都没有写入尝试；批准只写一次，再次提出同一写入又要等待；写入失败计一次尝试零次成功。", 710, body)


def r02_figures():
    """Generate the R02 schematics and message trace from verified package output."""
    evidence = json.loads((ROOT / "scripts/data/learn-agent-rust/r02-results.json").read_text())
    package = ROOT / "docs/public/learn-agent-rust/code/tools-and-graph"
    for name, digest in evidence["source_sha256"].items():
        # 下载包另外放进 fetch-adk-rust.py 与基线文件，它们的唯一来源在 scripts/
        source = package / name if (package / name).exists() else ROOT / "scripts" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("R02 evidence is stale; rerun verify-learn-agent-rust-r02.py")

    # ADK-Rust 3.0 版（2026-11 迁移）：数据来自 r02-results.json 的事件轨迹与请求记录
    body = panel(48, 82, 864, 128, "模型：看到每个工具的声明", ["名称 · 说明 · 由 PathArgs 生成的参数 schema", "本例由 ScriptedLlm 返回固定调用；真实服务另验收"])
    body += arrow("M480 272 V218")
    body += text(690, 247, "LlmAgent 声明给模型", 18, "#2563eb")
    body += panel(48, 280, 864, 132, "FunctionTool：一处定义，两种用途", ["read_file：名称 · 说明 · schema · 处理函数 · ReadOnly", "list_files：名称 · 说明 · schema · 处理函数 · ReadOnly"], "#0f766e")
    body += arrow("M480 420 V470")
    body += text(712, 452, "收到调用：按名称找到工具", 18, "#0f766e")
    body += panel(48, 478, 864, 100, "FunctionTool 先按 schema 校验参数，再运行处理函数", ["取值规则（如只能读 README.md）仍写在处理函数里；结果带原调用 ID。"], "#b45309")
    body += text(480, 621, "示意图：新增工具就是多注册一个 FunctionTool，循环由 LlmAgent 负责。", 18, "#475569")
    save_figure("r02-tool-registry.svg", "工具描述与执行入口来自同一份定义", "FunctionTool 把名称、说明、schema 与处理函数放在一起；LlmAgent 向模型声明前三者，收到调用后由 FunctionTool 先校验参数再运行处理函数。", 650, body)

    normal = next(row for row in evidence["scenarios"] if row["scenario"] == "normal")["direct"]
    rows = [("1 · system + user", "Agent 指令与用户问题", "#2563eb")]
    for line in normal["trace"]:
        kind = line.split("]", 1)[1].split()[0]
        ident = line.split("id=")[1].split(" ")[0] if "id=" in line else ""
        if kind == "call":
            tool = line.split(ident, 1)[1].split()[0]
            rows.append(("{} · model".format(len(rows) + 1), "调用 {} · ID={}".format(tool, ident), "#2563eb"))
        elif kind == "result":
            detail = "目录结果" if "entries" in line else "README 正文"
            rows.append(("{} · function".format(len(rows) + 1), "{} · ID={}".format(detail, ident), "#0f766e"))
        elif kind == "text":
            rows.append(("{} · model".format(len(rows) + 1), "最终回答：启动命令 cargo run", "#2563eb"))
    body = ""
    for index, (label, detail, color) in enumerate(rows):
        y = 80 + index * 82
        body += '<rect x="48" y="{}" width="864" height="62" rx="10" fill="#fff" stroke="{}" stroke-width="2"/>'.format(y, color)
        body += text(194, y + 38, label, 20, color, True)
        body += text(625, y + 38, detail, 18)
        if index < len(rows) - 1:
            body += arrow("M480 {} V{}".format(y + 62, y + 76))
    y = 80 + len(rows) * 82
    body += text(480, y + 20, "真实运行：{} 次模型调用 · {} 条工具结果 · 回答{}通过检查".format(
        normal["model_calls"], normal["tool_results"], "" if normal["verified"] else "未"), 21, "#0f766e", True)
    body += text(480, y + 60, "数据：ScriptedLlm + 真实临时文件；Runner 直接运行与放进图里运行的轨迹一致。", 17, "#475569")
    save_figure("r02-message-history.svg", "两次工具往返怎样形成完整的消息历史？", "消息顺序、调用 ID 与计数均来自 R02 normal 实际运行记录。", y + 92, body)

    body = panel(38, 96, 250, 112, "START", ["用户问题进入图状态"], "#475569")
    body += arrow("M288 152 H345")
    body += panel(354, 86, 300, 270, "assistant（AgentNode）", ["整个 LlmAgent：", "调用模型 → 执行工具", "→ 再调用模型 …", "直到回答或达到上限", "", "输出：answer · readme"], "#2563eb")
    body += arrow("M654 152 H711")
    body += panel(720, 96, 202, 112, "check_answer", ["普通函数节点", "写入 verified"], "#0f766e")
    body += arrow("M821 208 V262")
    body += panel(720, 270, 202, 86, "END", ["结论交回 Runner"], "#475569")
    body += arrow("M504 356 V410", "#b45309")
    body += panel(270, 418, 468, 96, "Agent 出错（预算、循环上限）", ["图停在 assistant，check_answer 不运行"], "#b45309")
    body += text(480, 556, "图调度 Agent 和普通步骤；单次工具往返留在 LlmAgent 内部。", 18, "#475569")
    save_figure("r02-graph-routing.svg", "把同一个 Agent 放进图节点", "图从 START 进入 assistant 节点，节点内部是 LlmAgent 完整的模型与工具往返；结束后进入 check_answer 函数节点核对回答，再到 END；Agent 出错时图停在 assistant。", 590, body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r02", action="store_true", help="Generate only the R02 figures")
    parser.add_argument("--lesson", choices=["R00", "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R11", "R12", "R10", "R13", "R14", "R15", "R16", "R18", "R19", "R20", "P02", "P01", "R17", "P04", "P03", "P05", "P06", "K01", "K02", "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "G01", "G02", "G03", "patterns", "all"], default="all")
    args = parser.parse_args()
    if args.r02:
        args.lesson = "R02"
    if args.lesson in ("patterns", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pattern_figures", ROOT / "scripts/learn-agent-rust-pattern-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if args.lesson in ("P05", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("goal_figures", ROOT / "scripts/learn-agent-rust-goal-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R16", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("protocol_figures", ROOT / "scripts/learn-agent-rust-protocol-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R17", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("worker_figures", ROOT / "scripts/learn-agent-rust-worker-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("P04", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("production_figures", ROOT / "scripts/learn-agent-rust-production-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("P01", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("checkpoint_figures", ROOT / "scripts/learn-agent-rust-checkpoint-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R19", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mcp_figures", ROOT / "scripts/learn-agent-rust-mcp-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R18", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("worktree_figures", ROOT / "scripts/learn-agent-rust-worktree-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R13", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("background_figures", ROOT / "scripts/learn-agent-rust-background-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R14", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("scheduling_figures", ROOT / "scripts/learn-agent-rust-scheduling-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R12", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("task_figures", ROOT / "scripts/learn-agent-rust-task-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R11", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("recovery_figures", ROOT / "scripts/learn-agent-rust-recovery-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R09", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("agent_r09", ROOT / "scripts/learn-agent-rust-memory-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R06", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("subagent_figures", ROOT / "scripts/learn-agent-rust-subagent-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R01", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("loop_figures", ROOT / "scripts/learn-agent-rust-loop-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("G01", "G02", "G03", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("orchestration_figures", ROOT / "scripts/learn-agent-rust-orchestration-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("K01", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rag_figures", ROOT / "scripts/learn-agent-rust-rag-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "patterns", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pattern_adk_figures", ROOT / "scripts/learn-agent-rust-pattern-adk-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure, None if args.lesson in ("patterns", "all") else args.lesson)
    if args.lesson in ("K02", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("websearch_figures", ROOT / "scripts/learn-agent-rust-websearch-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)
    if args.lesson in ("R00", "all"):
        runtime_architecture()
        request_and_action()
        message_trace()
        state_lifetimes()
        control_flow()
    if args.lesson in ("R02", "all") and (ROOT / "scripts/data/learn-agent-rust/r02-results.json").exists():
        r02_figures()
    if args.lesson in ("R03", "all"):
        permission_routes()
        approval_binding()
        permission_results()
    if args.lesson in ("R04", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("hook_figures", ROOT / "scripts/learn-agent-rust-hooks-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R05", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("todo_figures", ROOT / "scripts/learn-agent-rust-todo-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R07", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("skills_figures", ROOT / "scripts/learn-agent-rust-skills-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R10", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_figures", ROOT / "scripts/learn-agent-rust-prompt-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R08", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("compaction_figures", ROOT / "scripts/learn-agent-rust-compaction-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R15", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("teams_figures", ROOT / "scripts/learn-agent-rust-teams-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("P02", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("effects_figures", ROOT / "scripts/learn-agent-rust-effects-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("R20", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("integration_figures", ROOT / "scripts/learn-agent-rust-integration-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("P03", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("evaluation_figures", ROOT / "scripts/learn-agent-rust-evaluation-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


    if args.lesson in ("P06", "all"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("review_figures", ROOT / "scripts/learn-agent-rust-review-figures.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT, text, panel, arrow, save_figure)


if __name__ == "__main__":
    main()
