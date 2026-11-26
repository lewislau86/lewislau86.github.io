"""Regenerate figures for 《思考与行动之间》 (docs/thinking-and-acting/).

Run from any directory: python scripts/generate-thinking-acting-figures.py
Figures are written to docs/public/thinking-and-acting/figures/.

Agent 记忆一章的数字全部读取自 scripts/data/thinking-acting/agent-memory-official.json，
该文件转录自 Anthropic 原文（The components of agent memory, 2026-11-06）的正文与图注；
图中“推算”字样的数值由本脚本从这些官方数字计算得到，不是本站实验结果。
示意图手写 SVG（文字可选中）；数据图用 matplotlib，文字转为路径。
"""

from html import escape
from math import sqrt
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/thinking-and-acting/figures"
DATA = ROOT / "scripts/data/thinking-acting/agent-memory-official.json"
BLUE = "#2563eb"
TEAL = "#0f766e"
ORANGE = "#b45309"
RED = "#b91c1c"
GRAY = "#64748b"
PURPLE = "#7c3aed"
INK = "#172033"
SOFT = "#475569"
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'
SOURCE_NOTE = "数据：Anthropic《The components of agent memory》（2026-11-06）"


# ---------- 手写 SVG 工具 ----------

def svg(name, title, description, height, body, width=960):
    markers = "".join(
        f'<marker id="arrow-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{c}"/></marker>'
        for c in (BLUE, TEAL, ORANGE, RED, GRAY, PURPLE, INK))
    document = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
                f'role="img" aria-labelledby="title desc">\n'
                f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>\n'
                f'<defs>{markers}</defs>\n'
                f'<rect width="{width}" height="{height}" rx="16" fill="#f8fafc"/>\n'
                f"<g font-family='{FONT}' fill=\"{INK}\" text-anchor=\"middle\">{body}</g></svg>")
    ET.fromstring(document)
    (OUT / name).write_text(document + "\n", encoding="utf-8")
    print("Generated " + str((OUT / name).relative_to(ROOT)))


def text(x, y, value, size=18, color=INK, weight="normal", anchor="middle"):
    return (f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}">{escape(value)}</text>')


def box(x, y, w, h, stroke="#cbd5e1", fill="#ffffff", dash=False, width=2, rx=10):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    return (f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"{extra}/>')


def arrow(x1, y1, x2, y2, color=GRAY, width=2.5, dash=False):
    extra = ' stroke-dasharray="6 5"' if dash else ""
    return (f'<path d="M{x1:g} {y1:g}L{x2:g} {y2:g}" stroke="{color}" stroke-width="{width}" fill="none" '
            f'marker-end="url(#arrow-{color[1:]})"{extra}/>')


def path(d, color=GRAY, width=2.5, dash=False, marker=True):
    extra = ' stroke-dasharray="6 5"' if dash else ""
    end = f' marker-end="url(#arrow-{color[1:]})"' if marker else ""
    return f'<path d="{d}" stroke="{color}" stroke-width="{width}" fill="none"{end}{extra}/>'


def card(x, y, w, h, title, lines, color=BLUE, title_size=19, line_size=15, gap=24, fill="#ffffff"):
    body = box(x, y, w, h, color, fill)
    body += text(x + w / 2, y + 30, title, title_size, color, "bold")
    for i, line in enumerate(lines):
        body += text(x + w / 2, y + 58 + i * gap, line, line_size, SOFT)
    return body


# ---------- matplotlib 公共设置 ----------

def configure_plots():
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/System/Library/Fonts/PingFang.ttc"),
                  *Path("/usr/share/fonts").rglob("NotoSansCJK-Regular.ttc")]
    family = "sans-serif"
    for preferred in candidates:
        if preferred.exists():
            font_manager.fontManager.addfont(str(preferred))
            family = font_manager.FontProperties(fname=str(preferred)).get_name()
            break
    plt.rcParams.update({"font.family": family, "font.size": 13, "svg.fonttype": "path",
                         "svg.hashsalt": "thinking-and-acting", "axes.unicode_minus": False,
                         "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK, "ytick.color": INK,
                         "figure.facecolor": "#f8fafc", "axes.facecolor": "#ffffff",
                         "axes.spines.top": False, "axes.spines.right": False})


def save_plot(fig, name, title, description):
    target = OUT / name
    fig.savefig(target, format="svg", metadata={"Date": None, "Creator": "thinking-and-acting figure generator"})
    plt.close(fig)
    raw = target.read_text(encoding="utf-8")
    pos = raw.index(">", raw.index("<svg"))
    raw = raw[:pos] + ' role="img" aria-labelledby="title desc"' + raw[pos:]
    pos = raw.index(">", raw.index("<svg")) + 1
    raw = raw[:pos] + f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>' + raw[pos:]
    target.write_text(raw, encoding="utf-8")
    print("Generated " + str(target.relative_to(ROOT)))


# ---------- Agent 记忆：示意图 ----------

def memory_hierarchy():
    layers = [  # y, 半宽, 颜色, 标题, 说明
        (88, 140, RED, "注入上下文", "每次会话开头自动加载 · 必须很小"),
        (178, 180, ORANGE, "记忆表征（如 wiki）", "按主题组织、互相链接的页面"),
        (268, 220, TEAL, "记忆笔记", "Claude 写下的显著观察与规则"),
        (358, 260, BLUE, "原始记录（transcripts）", "可搜索的完整事件日志"),
    ]
    cx = 470
    body = text(480, 44, "Agent 记忆的四层结构，以及离线“做梦”在其中的位置", 23, weight="bold")
    for y, half, color, title, sub in layers:
        body += box(cx - half, y, half * 2, 70, color, "#ffffff", width=2.4)
        body += text(cx, y + 30, title, 19, color, "bold")
        body += text(cx, y + 55, sub, 15, SOFT)
    # 会话
    body += card(22, 88, 150, 70, "下一次会话", [], INK, 18)
    body += text(97, 145, "从顶层开始", 14, SOFT)
    body += arrow(cx - 140, 123, 176, 123, RED)
    body += text(253, 114, "启动即加载", 14, RED)
    body += card(22, 268, 150, 160, "本次会话", [], INK, 18)
    body += text(97, 330, "执行任务", 15, SOFT)
    body += text(97, 354, "与用户交互", 15, SOFT)
    body += arrow(172, 296, cx - 222, 296, TEAL)
    body += text(212, 287, "写笔记", 14, TEAL)
    body += arrow(172, 400, cx - 262, 400, BLUE)
    body += text(192, 391, "自动", 14, BLUE)
    # 做梦
    body += box(782, 88, 158, 340, PURPLE, "#faf5ff", dash=True)
    body += text(861, 114, "做梦（离线）", 19, PURPLE, "bold")
    body += text(861, 134, "会话之间运行", 13, SOFT)
    body += arrow(782, 148, cx + 142, 148, PURPLE)
    body += text(861, 170, "晋升 / 下放", 15, PURPLE)
    body += text(861, 188, "让顶层保持小", 13, SOFT)
    body += arrow(782, 222, cx + 182, 222, PURPLE)
    body += text(861, 244, "建 wiki · 补断链", 15, PURPLE)
    body += arrow(782, 304, cx + 222, 304, PURPLE)
    body += text(861, 326, "纠错 · 补写", 15, PURPLE)
    body += text(861, 344, "跨会话找规律", 13, SOFT)
    body += arrow(cx + 262, 380, 780, 380, PURPLE)
    body += text(861, 405, "回看原始记录", 15, PURPLE)
    # 两端对照
    body += path("M40 466 H920", "#cbd5e1", 2, marker=False)
    body += text(250, 498, "越往上：越小、越常被读到、写错代价越大", 16, RED)
    body += text(712, 498, "越往下：越完整、越接近事实、查找越贵", 16, BLUE)
    body += text(480, 538, "示意图：依原文图 1 的层级关系重绘；箭头方向表示信息的整理与流动。", 14, GRAY)
    svg("agent-memory-hierarchy.svg", "Agent 记忆的四层结构",
        "自下而上依次是原始记录、记忆笔记、记忆表征和注入上下文。会话自动写原始记录，并把显著观察写成笔记；"
        "做梦在会话之间回看原始记录，纠正笔记、构建 wiki，并决定哪些内容晋升到每次会话都会加载的顶层。", 560, body)


def learning_loop():
    body = text(480, 44, "记忆的学习闭环：不同模型各走到了哪一步", 23, weight="bold")
    stages = ["记录失败", "提出原因假设", "检验 / 确认", "写成可复用规则"]
    left, span = 240, 640
    xs = [left + span * (i + 0.5) / 4 for i in range(4)]
    for i, (x, s) in enumerate(zip(xs, stages)):
        body += box(x - 68, 76, 136, 54, BLUE, "#eff6ff")
        body += text(x, 109, s, 16, BLUE, "bold")
        if i < 3:
            body += arrow(x + 68, 103, xs[i + 1] - 70, 103, BLUE)
    body += path(f"M{xs[3]:g} 130 V150 H{xs[0]:g} V134", BLUE, 2, dash=True)
    body += text(left + span / 2, 168, "下一题开新会话：先读记忆目录，再作答", 14, BLUE)
    rows = [
        ("Sonnet 4.6", 2, GRAY, "散落的多个文件，每个列着几条未经检验的猜测"),
        ("Opus 4.7", 2.6, ORANGE, "合并成一份参考文档，开始标注“已核对 / 未确认”"),
        ("Sonnet 5", 3, ORANGE, "判分后把答案标为“已确认”；答错就写更正"),
        ("Opus 5", 4, TEAL, "规则 + 它为何成立 + 早前答案 + 踩过的陷阱"),
        ("Opus 5.5 / Sonnet 5.5", 4, TEAL, "同样闭环：把验证过的作答规则存进记忆"),
    ]
    for i, (name, reach, color, note) in enumerate(rows):
        y = 200 + i * 70
        body += text(left - 14, y + 27, name, 16, INK, "bold", "end")
        body += box(left, y + 8, span, 26, "#e2e8f0", "#f1f5f9", rx=13)
        body += f'<rect x="{left}" y="{y + 8}" width="{span * reach / 4:g}" height="26" rx="13" fill="{color}" opacity="0.85"/>'
        body += text(left + span / 2, y + 58, note, 14, SOFT)
    body += text(480, 572, "依原文对 CL-Bench 数据库任务中各模型记忆目录的描述归纳；进度条长度是本站的定性示意，不是测量值。", 13, GRAY)
    svg("agent-memory-learning-loop.svg", "记忆学习闭环与各模型的进展",
        "学习闭环分四步：记录失败、提出原因假设、检验确认、写成可复用规则。Sonnet 4.6 停在未经检验的假设，"
        "Opus 4.7 与 Sonnet 5 开始区分已确认和未确认，Opus 5、Opus 5.5、Sonnet 5.5 完成了闭环。", 590, body)


def pokemon_memory(d):
    p = d["pokemon_memory"]
    a, b = p["Sonnet 3.7"], p["Fable 5"]
    big = 290
    small = big * sqrt(b["characters"] / a["characters"])
    body = text(480, 44, "同样走到约 1 万步：写得越多，并不走得越远", 23, weight="bold")
    # Sonnet 3.7：面积 ∝ 字符数，内部 413 个小格表示文件数
    x0, y0 = 95, 82
    body += box(x0, y0, big, big, GRAY, "#f1f5f9", rx=4)
    cols = 21
    cell = big / cols
    for k in range(a["files"]):
        r, c = divmod(k, cols)
        body += (f'<rect x="{x0 + c * cell + 1:.1f}" y="{y0 + r * cell + 1:.1f}" width="{cell - 2:.1f}" '
                 f'height="{cell - 2:.1f}" fill="{GRAY}" opacity="0.35"/>')
    body += text(x0 + big / 2, 408, "Claude Sonnet 3.7", 19, GRAY, "bold")
    body += text(x0 + big / 2, 436, f"{a['files']} 个文件 · {a['folders']} 个文件夹", 16, SOFT)
    body += text(x0 + big / 2, 460, f"{a['characters']:,} 个字符", 16, SOFT)
    # Fable 5
    x1 = 620
    y1 = y0 + big - small
    body += box(x1, y1, small, small, TEAL, "#ccfbf1", rx=3)
    body += f'<line x1="{x1 + small * 0.4:.1f}" y1="{y1:.1f}" x2="{x1 + small * 0.4:.1f}" y2="{y1 + small:.1f}" stroke="{TEAL}" stroke-width="1.5"/>'
    body += f'<line x1="{x1 + small * 0.4:.1f}" y1="{y1 + small * 0.55:.1f}" x2="{x1 + small:.1f}" y2="{y1 + small * 0.55:.1f}" stroke="{TEAL}" stroke-width="1.5"/>'
    body += text(x1 + small + 14, y1 + 16, "global.md：当前目标、打道馆计划、记忆使用规则", 14, TEAL, anchor="start")
    body += text(x1 + small + 14, y1 + 38, "locations/：路线导航计划", 14, TEAL, anchor="start")
    body += text(x1 + small + 14, y1 + 60, "gameplay/：验证过的玩法策略", 14, TEAL, anchor="start")
    body += text(745, 408, "Claude Fable 5", 19, TEAL, "bold")
    body += text(745, 436, f"{b['files']} 个文件 · {b['folders']} 个文件夹 + global.md", 16, SOFT)
    body += text(745, 460, f"{b['characters']:,} 个字符", 16, SOFT)
    # 徽章
    def badges(cx, n, color):
        out = ""
        for i in range(4):
            fill = color if i < n else "#ffffff"
            out += f'<circle cx="{cx - 54 + i * 36}" cy="500" r="13" fill="{fill}" stroke="{color}" stroke-width="2"/>'
        return out
    body += badges(x0 + big / 2, a["badges"], GRAY) + text(x0 + big / 2, 538, f"{a['badges']} 枚徽章", 16, GRAY, "bold")
    body += badges(745, b["badges"], TEAL) + text(745, 538, f"{b['badges']} 枚徽章", 16, TEAL, "bold")
    ratio_chars = a["characters"] / b["characters"]
    ratio_files = a["files"] / b["files"]
    body += text(480, 230, f"字符 {ratio_chars:.1f} 倍", 17, ORANGE, "bold")
    body += text(480, 256, f"文件 {ratio_files:.0f} 倍", 17, ORANGE, "bold")
    body += arrow(420, 243, 395, 243, ORANGE) + arrow(540, 243, 600, 243, ORANGE)
    body += text(480, 580, "方块面积与记忆字符数成正比（同一比例尺）；左侧每个小格代表一个文件。各取一次运行，倍数为本站按原文数字推算。", 13, GRAY)
    svg("agent-memory-pokemon.svg", "Pokémon 中两个模型的记忆目录对比",
        f"约 1 万步时，Sonnet 3.7 写了 {a['files']} 个文件、{a['characters']:,} 个字符，拿到 {a['badges']} 枚徽章；"
        f"Fable 5 只有 {b['files']} 个文件、{b['characters']:,} 个字符，拿到 {b['badges']} 枚徽章。字符数相差约 {ratio_chars:.1f} 倍。", 600, body)


def mt_moon(d):
    m = d["mt_moon"]
    body = text(480, 44, "Mt. Moon：一条写错的笔记，怎样把 Agent 困在山脚", 23, weight="bold")
    # 地图条
    places = [(95, "来时的路线", GRAY), (285, "洞口 + PokéCenter", BLUE), (480, "Mt. Moon 洞穴", INK),
              (675, "东侧出口", BLUE), (865, "Cerulean City", TEAL)]
    for x, name, color in places:
        body += box(x - 85, 96, 170, 50, color, "#ffffff")
        body += text(x, 127, name, 16, color, "bold")
    for a_, b_ in ((285, 480), (480, 675), (675, 865)):
        body += arrow(a_ + 86, 121, b_ - 88, 121, GRAY, 2)
    body += path("M215 146 C200 180 170 180 150 150", RED, 2.5)
    body += text(185, 192, "单向台阶：掉下去就回不来", 14, RED)
    body += text(285, 86, "西侧", 14, SOFT) + text(675, 86, "东侧", 14, SOFT)
    # 错误自我强化
    body += box(30, 212, 900, 140, ORANGE, "#fffbeb")
    body += text(480, 240, "原始记忆：错误在会话内自我强化", 18, ORANGE, "bold")
    steps = [("笔记写错：", "PokéCenter 在东侧"), ("走出中心就宣布：", "“Mt Moon is behind me”"),
             ("把笔记更新成：", "“Mt Moon DONE”"), ("跌下台阶后解释为：", "“I overshot far west”")]
    for i, (s1, s2) in enumerate(steps):
        x = 136 + i * 229
        body += box(x - 98, 258, 196, 74, ORANGE, "#ffffff")
        body += text(x, 287, s1, 14, ORANGE, "bold")
        body += text(x, 313, s2, 14, INK)
        if i < 3:
            body += arrow(x + 98, 295, x + 129, 295, ORANGE, 2)
    # 三次运行
    body += text(480, 388, f"三次运行的结局（{m['max_actions']:,} 次累计动作内）", 18, INK, "bold")
    rows = [("没有记忆", GRAY, "始终没有越过这座山", 0.42, False),
            ("原始记忆", ORANGE, f"跌下台阶 {m['raw_memory_ledge_falls']} 次，最后退回 Pewter City", 0.36, False),
            ("记忆 + 做梦", TEAL, f"对照原始记录改正笔记 → 回到洞里 → 第 {m['memory_plus_dreaming_reaches_cerulean_at']:,} 次动作到达 Cerulean", 1.0, True)]
    for i, (name, color, note, frac, ok) in enumerate(rows):
        y = 404 + i * 66
        body += text(140, y + 25, name, 16, color, "bold", "end")
        body += box(160, y + 8, 720, 24, "#e2e8f0", "#f1f5f9", rx=12)
        body += f'<rect x="160" y="{y + 8}" width="{720 * frac:g}" height="24" rx="12" fill="{color}" opacity="0.8"/>'
        body += text(520, y + 54, note, 14, SOFT)
    body += text(480, 634, "示意图：依原文图 7、图 8 的描述重绘；只有“第 1,935 次动作到达”是原文给出的数值，前两条进度条长度为示意。", 13, GRAY)
    svg("agent-memory-mt-moon.svg", "Mt. Moon 案例：错误笔记与做梦纠错",
        "笔记把 PokéCenter 记在东侧，Agent 误以为已经过山，跌下单向台阶后又把原因解释成走过头，错误在会话内自我强化。"
        "原始记忆和无记忆的运行都没有到达 Cerulean City；做梦对照原始记录改正笔记后，Agent 在第 1,935 次动作到达。", 656, body)


def wiki_when(d):
    mq, ow = d["merger_questions"], d["overgrown_wiki"]
    body = text(480, 44, "wiki 什么时候值得建？看问题需要跨越几份文档", 23, weight="bold")
    # 卡片 1
    body += box(30, 80, 290, 420, TEAL, "#ffffff")
    body += text(175, 112, "跨文档综合", 20, TEAL, "bold")
    body += text(175, 140, f"并购问答 {mq['questions']} 题 · {mq['documents']} 份文档", 15, SOFT)
    body += text(175, 164, f"过半要拼接多份文档；{mq['need_judgment_or_math']} 题需判断或计算", 13, SOFT)
    for i, (label, v, color) in enumerate((("wiki", mq["score"]["wiki"], TEAL), ("仅搜索", mq["score"]["search only"], GRAY))):
        x = 110 + i * 130
        h = 220 * v
        body += f'<rect x="{x - 32}" y="{440 - h:.1f}" width="64" height="{h:.1f}" rx="6" fill="{color}" opacity="0.85"/>'
        body += text(x, 430 - h, f"{v:.0%}", 18, color, "bold")
        body += text(x, 465, label, 15, INK)
    body += text(175, 490, "wiki 明显占优", 15, TEAL, "bold")
    # 卡片 2
    body += box(335, 80, 290, 420, GRAY, "#ffffff")
    body += text(480, 112, "单文档查找", 20, GRAY, "bold")
    body += text(480, 140, f"LAB 任务 · {d['lab_single_doc']['criteria']} 个评分点", 15, SOFT)
    body += text(480, 164, "多数答案就在一份交易概览备忘录里", 13, SOFT)
    for i in range(6):
        body += box(375, 196 + i * 34, 120, 24, GRAY, "#f1f5f9", rx=4)
        body += arrow(497, 208 + i * 34, 545, 288, GRAY, 1.5)
    body += box(548, 262, 62, 52, ORANGE, "#fffbeb", rx=6)
    body += text(579, 294, "备忘录", 13, ORANGE, "bold")
    body += text(480, 440, "文本搜索一步就能命中", 15, SOFT)
    body += text(480, 490, "wiki 无明显增益", 15, GRAY, "bold")
    # 卡片 3
    body += box(640, 80, 290, 420, RED, "#ffffff")
    body += text(785, 112, "过度生长", 20, RED, "bold")
    body += text(785, 140, f"另一 LAB 任务 · {ow['corpus_docs']} 份文档", 15, SOFT)
    body += text(785, 164, f"wiki：{ow['wiki_pages']} 页、{ow['wiki_links']} 条链接，部分页面无链接", 13, SOFT)
    r1 = 50
    r2 = r1 * sqrt(ow["wiki_kb"] / ow["corpus_kb"])
    body += f'<circle cx="710" cy="300" r="{r1}" fill="#e2e8f0" stroke="{GRAY}" stroke-width="2"/>'
    body += text(710, 296, "原文档", 14, INK, "bold") + text(710, 318, f"{ow['corpus_kb']} KB", 14, SOFT)
    body += f'<circle cx="850" cy="300" r="{r2:.1f}" fill="#fee2e2" stroke="{RED}" stroke-width="2"/>'
    body += text(850, 296, "wiki", 14, RED, "bold") + text(850, 318, f"{ow['wiki_kb']} KB", 14, SOFT)
    body += text(785, 440, f"体积是原文的 {ow['ratio']} 倍", 15, SOFT)
    body += text(785, 490, "地图和疆域一样大", 15, RED, "bold")
    body += text(480, 538, "原文图 11、图 12 的数字；圆面积与文本体积成正比。三项分别来自不同任务，不可横向比较分数。", 13, GRAY)
    svg("agent-memory-wiki-when.svg", "wiki 在三类任务上的表现",
        f"需要跨文档综合的并购问答中，用 wiki 得 {mq['score']['wiki']:.0%}，仅搜索 {mq['score']['search only']:.0%}；"
        f"答案集中在单一文档的任务上 wiki 没有明显增益；另一任务中 wiki 长到 {ow['wiki_kb']} KB，是原文档 {ow['corpus_kb']} KB 的 {ow['ratio']} 倍。", 560, body)


def contract_facts(d):
    c = d["contract_facts"]
    total, kept = c["total_facts"], c["shared_page"]["facts_kept"]
    body = text(480, 44, "合同条款为何丢失：多人改同一页，后保存的覆盖先保存的", 23, weight="bold")

    def grid(x0, y0, keep, color):
        out = ""
        for k in range(total):
            r, col = divmod(k, 19)
            fill = color if k < keep else "#ffffff"
            stroke = color if k < keep else RED
            dash = "" if k < keep else ' stroke-dasharray="3 2"'
            out += (f'<rect x="{x0 + col * 20}" y="{y0 + r * 20}" width="15" height="15" rx="3" fill="{fill}" '
                    f'stroke="{stroke}" stroke-width="1.5"{dash}/>')
        return out

    # 之前
    body += box(30, 78, 435, 470, ORANGE, "#ffffff")
    body += text(247, 110, "之前：共享一张条款表", 19, ORANGE, "bold")
    for i in range(c["agents"]):
        x = 85 + i * 108
        body += box(x - 40, 132, 80, 40, BLUE, "#eff6ff")
        body += text(x, 158, f"Agent {i + 1}", 14, BLUE, "bold")
        body += arrow(x, 172, 247 + (x - 247) * 0.25, 226, BLUE, 2)
    body += box(167, 230, 160, 52, ORANGE, "#fffbeb")
    body += text(247, 262, "provisions.md", 16, ORANGE, "bold")
    body += text(247, 310, "并发保存互相覆盖 · 条款被摘要压缩", 14, SOFT)
    body += grid(58, 336, kept, ORANGE)
    body += text(247, 438, f"简报保住 {kept} / {total} 个事实（{kept / total:.0%}）", 18, ORANGE, "bold")
    body += text(247, 470, "虚线空格：丢失的评分事实", 13, RED)
    # 之后
    body += box(495, 78, 435, 470, TEAL, "#ffffff")
    body += text(712, 110, "之后：每份合同一页、一位作者", 19, TEAL, "bold")
    for i in range(c["agents"]):
        x = 550 + i * 108
        body += box(x - 40, 132, 80, 40, BLUE, "#eff6ff")
        body += text(x, 158, f"Agent {i + 1}", 14, BLUE, "bold")
        body += arrow(x, 172, x, 226, BLUE, 2)
        body += box(x - 44, 230, 88, 52, TEAL, "#f0fdfa")
        body += text(x, 254, f"合同 {i + 1}", 14, TEAL, "bold")
        body += text(x, 273, "逐字引用", 12, SOFT)
    body += text(712, 310, "单写者 · 原文照录，不做摘要", 14, SOFT)
    body += grid(523, 336, total, TEAL)
    body += text(712, 438, f"简报保住 {total} / {total} 个事实（100%）", 18, TEAL, "bold")
    body += text(712, 470, "新指令由 Claude 反思失败后自己改写", 13, SOFT)
    body += text(480, 580, "原文图 14 的数字：57 个评分事实，每个方块代表一个。前后改了两处（写入分工与逐字引用），原文未分别测量。", 13, GRAY)
    svg("agent-memory-contract-facts.svg", "合同条款 wiki 的前后对比",
        f"四个 Agent 同时写一张共享条款表时互相覆盖，简报只保住 {kept}/{total} 个事实；"
        f"改成每份合同一页、由单个 Agent 逐字引用后，{total}/{total} 个事实全部保住。", 600, body)


def wiki_repair(d):
    w = d["wiki_repair"]
    bf, af = w["before"], w["after"]
    body = text(480, 44, "第二轮做梦：修好断链，补上索引", 23, weight="bold")
    for side, x0, color, title in ((0, 30, ORANGE, "第二轮之前"), (1, 495, TEAL, "第二轮之后")):
        body += box(x0, 78, 435, 400, color, "#ffffff")
        body += text(x0 + 217, 110, title, 19, color, "bold")
        cx, cy = x0 + 200, 280
        src = [(x0 + 60, 160), (x0 + 60, 230), (x0 + 60, 300), (x0 + 60, 370), (x0 + 130, 140), (x0 + 130, 400)]
        for sx, sy in src:
            body += f'<circle cx="{sx}" cy="{sy}" r="14" fill="#e2e8f0" stroke="{GRAY}" stroke-width="1.5"/>'
        body += text(x0 + 95, 426, "链出的 6 个页面", 13, SOFT)
        if side == 0:
            body += box(cx + 10, cy - 26, 180, 52, RED, "#fef2f2", dash=True)
            body += text(cx + 100, cy - 3, "escrow-agreement", 14, RED, "bold")
            body += text(cx + 100, cy + 17, "（页面不存在）", 12, RED)
            for i, (sx, sy) in enumerate(src):
                body += path(f"M{sx + 14} {sy} L{cx + 8} {cy + (i - 2.5) * 7:.0f}", RED, 1.6, dash=True)
            stats = f"{bf['entries']} 个条目 · {bf['links']} 条链接"
            note = f"{bf['pages_with_broken_links']} 个页面的 {bf['broken_links']} 条链接指向空页"
        else:
            body += box(cx + 10, cy - 26, 196, 52, TEAL, "#f0fdfa")
            body += text(cx + 108, cy - 3, "buyer-form-escrow-", 13, TEAL, "bold")
            body += text(cx + 108, cy + 16, "agreement", 13, TEAL, "bold")
            for i, (sx, sy) in enumerate(src):
                body += path(f"M{sx + 14} {sy} L{cx + 8} {cy + (i - 2.5) * 7:.0f}", TEAL, 1.6)
            for name, by in (("index", 132), ("instructions email", 172), ("escalations", 372)):
                bx = x0 + 228
                body += box(bx, by, 196, 30, BLUE, "#eff6ff", rx=15)
                body += text(bx + 98, by + 20, "新页：" + name, 13, BLUE, "bold")
            stats = f"{af['entries']} 个条目 · {af['links']} 条链接"
            note = f"{bf['broken_links']} 条链接改指已有页面，新增 {len(af['new_pages'])} 页"
        body += text(x0 + 217, 446, stats, 16, color, "bold")
        body += text(x0 + 217, 467, note, 13, SOFT)
    body += arrow(468, 280, 492, 280, PURPLE, 3)
    body += text(480, 512, "原文图 15 的数字；左右节点为示意，只画出与断链相关的局部。", 13, GRAY)
    svg("agent-memory-wiki-repair.svg", "第二轮做梦修复 wiki 断链",
        f"第二轮之前 wiki 有 {bf['entries']} 个条目、{bf['links']} 条链接，其中 {bf['broken_links']} 条指向不存在的 escrow-agreement；"
        f"之后这些链接改指 buyer-form-escrow-agreement，并新增 index 等 3 页，共 {af['entries']} 个条目、{af['links']} 条链接。", 535, body)


def engineering_analogy():
    body = text(480, 44, "把四层记忆当作一套存储系统来看", 23, weight="bold")
    heads = ["层", "工程类比", "谁写、何时写", "典型故障", "维护手段"]
    xs = [30, 170, 340, 520, 730]
    ws = [140, 170, 180, 210, 200]
    for x, w, h in zip(xs, ws, heads):
        body += box(x, 70, w, 40, INK, "#e2e8f0", rx=4)
        body += text(x + w / 2, 96, h, 16, INK, "bold")
    rows = [
        (RED, "注入上下文", ["CPU 一级缓存", "书的目录页"], ["做梦晋升", "会话内维护索引"],
         ["错误广播到每次会话", "越长越不被遵循"], ["只放索引与当前目标", "细节下放、留链接"]),
        (ORANGE, "记忆表征", ["物化视图", "数据库索引"], ["做梦批量构建", "多 Agent 协作"],
         ["过度生长、断链", "并发写入互相覆盖"], ["合并重复、断链检查", "一页一位作者"]),
        (TEAL, "记忆笔记", ["便签 / 预写日志", "缓冲区"], ["会话内即时写", "凭当下判断显著性"],
         ["一开始就写错", "随环境变化而过期"], ["对照原始记录复核", "记录“怎么知道的”"]),
        (BLUE, "原始记录", ["只追加的事件日志", "（event sourcing）"], ["运行时自动记录", "不经筛选"],
         ["体积大、查找贵", "不直接告诉你规律"], ["保持不可变", "作为唯一事实来源"]),
    ]
    for i, (color, name, *cols) in enumerate(rows):
        y = 116 + i * 92
        body += box(xs[0], y, ws[0], 86, color, "#ffffff", width=2.4, rx=4)
        body += text(xs[0] + ws[0] / 2, y + 50, name, 17, color, "bold")
        for x, w, lines in zip(xs[1:], ws[1:], cols):
            body += box(x, y, w, 86, "#cbd5e1", "#ffffff", rx=4)
            for k, line in enumerate(lines):
                body += text(x + w / 2, y + 38 + k * 24, line, 14, SOFT)
    body += text(480, 512, "本站的分析框架：类比用于帮助记忆各层的取舍，并非原文的表述。", 13, GRAY)
    svg("agent-memory-engineering-analogy.svg", "四层记忆的工程类比",
        "注入上下文像一级缓存或目录页，故障是错误被广播；记忆表征像物化视图，故障是过度生长和并发覆盖；"
        "记忆笔记像便签，可能一开始就写错或过期；原始记录像只追加的事件日志，是做梦复核时的事实来源。", 535, body)


def write_timing():
    body = text(480, 44, "什么时候写记忆：现场写，还是事后整理？", 23, weight="bold")
    body += card(40, 80, 400, 262, "会话内写（现场）", [], TEAL, 20)
    pros = ["+ 显著性在源头捕获，信息最新鲜", "+ 写完立刻可用，后面的轮次就能读", "− 分走主任务的注意力和步数",
            "− 只看得到本次会话", "− 写错了，当下没人复核"]
    for i, s in enumerate(pros):
        body += text(70, 142 + i * 42, s, 15, TEAL if s.startswith("+") else RED, anchor="start")
    body += card(520, 80, 400, 262, "做梦（离线整理）", [], PURPLE, 20)
    cons = ["+ 放到后台，不打断主任务", "+ 跨多次会话找共同规律、共同错误", "+ 可对照原始记录纠错",
            "− 要额外算力，且要决定多久做一次", "− 结果有延迟，当前会话用不上"]
    for i, s in enumerate(cons):
        body += text(550, 142 + i * 42, s, 15, PURPLE if s.startswith("+") else RED, anchor="start")
    body += arrow(442, 200, 516, 200, GRAY) + arrow(518, 222, 444, 222, GRAY)
    body += text(480, 384, "二者是分工而不是二选一：现场负责“别丢”，做梦负责“别错、别乱、别太大”。", 17, INK, "bold")
    body += text(480, 418, "对照原文结尾的开放问题整理；“+ / −”为本站归纳。", 13, GRAY)
    svg("agent-memory-write-timing.svg", "会话内写记忆与离线做梦的取舍",
        "会话内写记忆能在源头捕获显著性、立即可用，但分散注意力、只看到本会话；做梦在后台运行，可跨会话、对照原始记录纠错，"
        "但需要额外算力且结果有延迟。两者是分工关系。", 440, body)


# ---------- Agent 记忆：数据图 ----------

def cl_bench_plot(d):
    rows = d["cl_bench_database"]["models"]
    names = [r["name"] for r in rows]
    base = [r["baseline"] for r in rows]
    mem = [r["memory"] for r in rows]
    closed = [(m - b) / (1 - b) for b, m in zip(base, mem)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw={"width_ratios": [1.5, 1]})
    xs = range(len(rows))
    w = 0.38
    a1.bar([x - w / 2 for x in xs], base, w, color="#cbd5e1", label="无状态基线")
    a1.bar([x + w / 2 for x in xs], mem, w, color=TEAL, label="跨会话记忆目录")
    for x, b, m in zip(xs, base, mem):
        a1.text(x - w / 2, b + 0.015, f"{b:.3f}", ha="center", fontsize=9.5, color=GRAY)
        a1.text(x + w / 2, m + 0.015, f"{m:.3f}", ha="center", fontsize=9.5, color=TEAL)
        a1.text(x, max(b, m) + 0.085, f"+{m - b:.3f}", ha="center", fontsize=11, color=ORANGE, fontweight="bold")
    a1.set_xticks(list(xs), names, fontsize=11)
    a1.set_ylim(0, 1.02)
    a1.set_ylabel("平均 reward（30 题）")
    a1.set_title("记忆带来的绝对提升（橙色数字）", fontsize=13)
    a1.legend(loc="upper right", fontsize=10, framealpha=0.95)
    a1.grid(axis="y", alpha=0.25)
    colors = [TEAL if c > 0.4 else (ORANGE if c > 0.2 else GRAY) for c in closed]
    a2.barh(list(xs), closed, color=colors)
    for x, c in zip(xs, closed):
        a2.text(c + 0.01, x, f"{c:.0%}", va="center", fontsize=11)
    a2.set_yticks(list(xs), names, fontsize=11)
    a2.invert_yaxis()
    a2.set_xlim(0, 0.75)
    a2.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    a2.set_title("剩余差距被记忆补上的比例（推算）", fontsize=13)
    a2.set_xlabel("(有记忆 − 基线) ÷ (1 − 基线)，假设满分为 1")
    a2.grid(axis="x", alpha=0.25)
    fig.text(0.5, 0.005, SOURCE_NOTE + " 图 3；右图为本站据原文数字推算。", ha="center", fontsize=9.5, color=GRAY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    desc = "；".join(f"{n} 从 {b:.3f} 到 {m:.3f}" for n, b, m in zip(names, base, mem))
    save_plot(fig, "agent-memory-cl-bench.svg", "CL-Bench 数据库任务：有无记忆的对比",
              "左：各模型无状态基线与使用记忆目录后的平均 reward，" + desc + "。右：记忆补上剩余差距的比例，Opus 5 最高约 61%，Sonnet 4.6 约 5%。")


def steering_plot(d):
    s = d["steering"]
    sn = s["sonnet_46"]
    gains = {r["name"]: r["memory"] - r["baseline"] for r in d["cl_bench_database"]["models"]}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    labels = ["基线", "有记忆", "有记忆 +\n细化指令"]
    vals = [sn["baseline"], sn["memory"], sn["memory_refined_instruction"]]
    a1.bar(labels, vals, color=["#cbd5e1", "#94a3b8", BLUE], width=0.55)
    for i, v in enumerate(vals):
        a1.text(i, v + 0.015, f"{v:.3f}", ha="center", fontsize=11)
    for (name, v), color in zip(s["reference_lines"].items(), (ORANGE, TEAL)):
        a1.axhline(v, color=color, ls="--", lw=1.3)
        a1.text(2.45, v + 0.012, name.replace("memory", "记忆") + f" {v:.3f}", ha="right", fontsize=10, color=color)
    a1.set_ylim(0, 0.95)
    a1.set_ylabel("平均 reward")
    a1.set_title("Sonnet 4.6：提示它先读记忆、再检验假设", fontsize=13)
    a1.grid(axis="y", alpha=0.25)
    models = list(s["record_only_failures_gain_change"].keys())
    before = [gains[m] for m in models]
    after = [gains[m] + s["record_only_failures_gain_change"][m] for m in models]
    ys = range(len(models))
    h = 0.36
    a2.barh([y - h / 2 for y in ys], before, h, color=TEAL, label="默认（只告诉它有记忆目录）")
    a2.barh([y + h / 2 for y in ys], after, h, color=RED, label="规定“只记录失败”（推算）")
    for y, b, a_, m in zip(ys, before, after, models):
        a2.text(b + 0.006, y - h / 2, f"+{b:.3f}", va="center", fontsize=10, color=TEAL)
        a2.text(a_ + 0.006, y + h / 2, f"+{a_:.3f}（{s['record_only_failures_gain_change'][m]:+.3f}）", va="center", fontsize=10, color=RED)
    a2.set_yticks(list(ys), models, fontsize=11)
    a2.invert_yaxis()
    a2.set_xlim(0, 0.42)
    a2.set_xlabel("记忆带来的增益（有记忆 − 基线）")
    a2.set_title("给强模型定死规则，增益反而缩水", fontsize=13)
    a2.legend(loc="lower right", fontsize=9.5, framealpha=0.95)
    a2.grid(axis="x", alpha=0.25)
    fig.text(0.5, 0.005, SOURCE_NOTE + " 图 5；右图红条 = 图 3 的默认增益 + 图 5 给出的变化量，由本站推算。",
             ha="center", fontsize=9.5, color=GRAY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    save_plot(fig, "agent-memory-steering.svg", "引导记忆写法的两个实验",
              f"左：Sonnet 4.6 基线 {sn['baseline']:.3f}，有记忆 {sn['memory']:.3f}，再加上“先读记忆、检验假设”的指令后 {sn['memory_refined_instruction']:.3f}。"
              "右：规定只记录失败后，Opus 5 的记忆增益减少 0.234，Opus 4.7 减少 0.150，Sonnet 4.6 只减少 0.020。")


def wiki_scaling_plot(d):
    w = d["stainless_wiki"]
    g = w["graded_criteria_met"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.4, 1]})
    s0, s1 = w["sessions"]["start"], w["sessions"]["end"]
    styles = {"wiki + search": (BLUE, "wiki + 搜索"), "wiki only": (TEAL, "仅 wiki"), "search only": (GRAY, "仅搜索（不建 wiki）")}
    for key, (color, label) in styles.items():
        v0, v1 = g[key]["start"], g[key]["end"]
        a1.plot([s0, s1], [v0, v1], color=color, ls="--", lw=1.6, alpha=0.8)
        a1.scatter([s0, s1], [v0, v1], color=color, s=60, zorder=3, label=label)
        a1.text(s1 * 1.12, v1, f"{v1:.0%}", va="center", fontsize=11, color=color)
        nudge = {"wiki + search": 0.022, "search only": -0.022}.get(key, 0)
        a1.text(s0 / 1.12, v0 + nudge, f"{v0:.0%}", va="center", ha="right", fontsize=11, color=color)
    a1.set_xscale("log", base=2)
    a1.set_xticks([2, 8, 32, 128], ["2 次会话\n约 2M token", "8", "32", "128 次会话\n约 128M token"])
    a1.set_xlim(1.2, 230)
    a1.set_ylim(0, 0.72)
    a1.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    a1.set_ylabel("评分点满足率（25 题）")
    a1.set_title("做梦越多，wiki 越有用；但单靠 wiki 仍不如搜索", fontsize=13)
    a1.legend(loc="lower right", fontsize=10, framealpha=0.95)
    a1.grid(alpha=0.25)
    a1.text(4.5, 0.36, "原文只公布两端数值，\n虚线仅连接起点与终点", fontsize=10, color=GRAY)
    gs, ge = w["wiki_graph"]["start"], w["wiki_graph"]["end"]
    cats = ["页面数", "链接数", "每页链接（推算）"]
    v0 = [gs["pages"], gs["links"], gs["links"] / gs["pages"]]
    v1 = [ge["pages"], ge["links"], ge["links"] / ge["pages"]]
    xs = range(3)
    bw = 0.36
    a2.bar([x - bw / 2 for x in xs], v0, bw, color="#cbd5e1", label=f"{s0} 次会话后")
    a2.bar([x + bw / 2 for x in xs], v1, bw, color=PURPLE, label=f"{s1} 次会话后")
    for x, a_, b_ in zip(xs, v0, v1):
        fmt = (lambda v: f"{v:.1f}") if x == 2 else (lambda v: f"{v:,.0f}")
        a2.text(x - bw / 2, a_ * 1.12, fmt(a_), ha="center", fontsize=10, color=GRAY)
        a2.text(x + bw / 2, b_ * 1.12, fmt(b_), ha="center", fontsize=10, color=PURPLE)
    a2.set_yscale("log")
    a2.set_ylim(3, 60000)
    a2.set_xticks(list(xs), cats, fontsize=11)
    a2.set_title("wiki 的“地图”：页数翻倍，链接涨 17 倍", fontsize=13)
    a2.legend(loc="upper left", fontsize=10, framealpha=0.95)
    a2.grid(axis="y", alpha=0.25)
    fig.text(0.5, 0.005, SOURCE_NOTE + " 图 10；对数坐标。", ha="center", fontsize=9.5, color=GRAY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    save_plot(fig, "agent-memory-wiki-scaling.svg", "wiki 随做梦次数增长的效果",
              f"左：做梦从 {s0} 次会话增加到 {s1} 次，wiki + 搜索从 54% 升到 61%，仅 wiki 从 13% 升到 48%，仅搜索保持 53%。"
              f"右：wiki 从 {gs['pages']} 页、{gs['links']} 条链接长到 {ge['pages']} 页、{ge['links']:,} 条链接。")


def derived_numbers(d):
    """打印正文引用的推算数字，便于核对。"""
    print("\n-- 正文引用的推算数字 --")
    for r in d["cl_bench_database"]["models"]:
        g = r["memory"] - r["baseline"]
        print(f"{r['name']:<11} gain={g:+.3f} closed={(g / (1 - r['baseline'])):.1%} "
              f"error {1 - r['baseline']:.3f}->{1 - r['memory']:.3f}")
    gains = {r["name"]: r["memory"] - r["baseline"] for r in d["cl_bench_database"]["models"]}
    for m, ch in d["steering"]["record_only_failures_gain_change"].items():
        print(f"only-failures {m}: gain {gains[m]:.3f} -> {gains[m] + ch:.3f} (kept {(gains[m] + ch) / gains[m]:.0%})")
    sn = d["steering"]["sonnet_46"]
    print(f"Sonnet 4.6 refined/baseline = {sn['memory_refined_instruction'] / sn['baseline']:.2f}x, "
          f"gain {sn['memory'] - sn['baseline']:.3f} -> {sn['memory_refined_instruction'] - sn['baseline']:.3f}")
    p = d["pokemon_memory"]
    a, b = p["Sonnet 3.7"], p["Fable 5"]
    print(f"pokemon chars ratio {a['characters'] / b['characters']:.1f}x, files {a['files'] / b['files']:.1f}x, "
          f"chars/file {a['characters'] / a['files']:.0f} vs {b['characters'] / b['files']:.0f}")
    w = d["stainless_wiki"]
    gs, ge = w["wiki_graph"]["start"], w["wiki_graph"]["end"]
    print(f"wiki pages x{ge['pages'] / gs['pages']:.2f}, links x{ge['links'] / gs['links']:.1f}, "
          f"links/page {gs['links'] / gs['pages']:.1f} -> {ge['links'] / ge['pages']:.1f}")
    print(f"breakeven questions = {w['dreaming_tokens']['end'] / w['tokens_saved_per_question']:.0f}; "
          f"corpus tokens / dreaming tokens = {w['corpus_tokens'] / w['dreaming_tokens']['end']:.2f}")
    c = d["contract_facts"]
    print(f"contract kept {c['shared_page']['facts_kept'] / c['total_facts']:.1%}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    memory_hierarchy()
    learning_loop()
    pokemon_memory(data)
    mt_moon(data)
    wiki_when(data)
    contract_facts(data)
    wiki_repair(data)
    engineering_analogy()
    write_timing()
    configure_plots()
    cl_bench_plot(data)
    steering_plot(data)
    wiki_scaling_plot(data)
    derived_numbers(data)


if __name__ == "__main__":
    main()
