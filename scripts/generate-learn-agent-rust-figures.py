"""Generate the course's own conceptual architecture figure (no experiment data).

Reference website figures are preserved separately by sync-learn-agent-rust-assets.py.
"""

from html import escape
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


def main():
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


if __name__ == "__main__":
    main()
