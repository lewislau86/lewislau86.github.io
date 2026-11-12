"""Regenerate figures for 思考与行动之间 (pure Python, no third-party packages).

Run from any directory: python scripts/generate-thinking-acting-figures.py
Hand-built SVG written to docs/public/thinking-and-acting/figures/; text stays selectable.
Style follows scripts/generate-mini-redis-figures.py.
"""

from html import escape
from math import log10
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/thinking-and-acting/figures"
BLUE = "#2563eb"
ORANGE = "#b45309"
GRAY = "#64748b"
INK = "#172033"
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'


def svg(name, title, description, height, body, width=960):
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<rect width="{width}" height="{height}" rx="16" fill="#f8fafc"/>
<g font-family='{FONT}' fill="{INK}" text-anchor="middle">{body}</g></svg>'''
    ET.fromstring(document)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(document + "\n", encoding="utf-8")


def text(x, y, value, size=16, color=INK, weight="normal", anchor="middle"):
    size = max(size, 14)
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}">{escape(value)}</text>')


def seg(x1, y1, x2, y2, color=GRAY, width=1.5, dash=False):
    extra = ' stroke-dasharray="6 5"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"{extra}/>'


# 与 docs/public/thinking-and-acting/code/transformer.py 的 attention_share 保持一致
def attention_share(n, d):
    return n / (n + 6 * d)


def transformer_n_vs_d():
    L, R, T, B = 110, 900, 90, 470          # 绘图区
    xmin, xmax = 1, 6                        # log10(n)：10 … 1,000,000
    X = lambda n: L + (log10(n) - xmin) / (xmax - xmin) * (R - L)
    Y = lambda p: B - p * (B - T)
    body = text(480, 40, "一层 Transformer 里，花在 n² 项（打分与加权求和）上的计算占比", 21, INK, "bold")
    body += text(480, 66, "占比 = n / (n + 6d)；n 为序列长度，d 为模型宽度；不计因果掩码可跳过的一半", 15, GRAY)
    # 网格与坐标轴
    for p in (0, .25, .5, .75, 1):
        body += seg(L, Y(p), R, Y(p), "#e2e8f0", 1)
        body += text(L - 12, Y(p) + 5, f"{int(p * 100)}%", 14, GRAY, anchor="end")
    for e in range(xmin, xmax + 1):
        body += seg(X(10 ** e), T, X(10 ** e), B, "#e2e8f0", 1)
        label = {1: "10", 2: "100", 3: "1K", 4: "10K", 5: "100K", 6: "1M"}[e]
        body += text(X(10 ** e), B + 24, label, 14, GRAY)
    body += seg(L, B, R, B, INK, 1.5) + seg(L, T, L, B, INK, 1.5)
    body += text((L + R) / 2, B + 52, "序列长度 n（对数坐标）", 15, GRAY)
    # 两条曲线
    for d, color, name in ((512, BLUE, "d = 512（2017 base）"), (8192, ORANGE, "d = 8192（今天的大模型）")):
        pts = []
        steps = 200
        for i in range(steps + 1):
            n = 10 ** (xmin + (xmax - xmin) * i / steps)
            pts.append(f"{X(n):.1f},{Y(attention_share(n, d)):.1f}")
        body += f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="3"/>'
        # n = d：表 1 里自注意力与循环层每层计算量相等的位置
        body += seg(X(d), Y(attention_share(d, d)), X(d), B, color, 1.5, dash=True)
        body += text(X(d) + 8, B - 10, "n = d", 14, color, "bold", anchor="start")
    body += text(X(170), Y(.62), "d = 512（2017 base）", 15, BLUE, "bold")
    body += text(X(170), Y(.62) + 20, "n = d 处只占 14%", 14, BLUE)
    body += text(X(2.2e4), Y(.12), "d = 8192（例如 Llama 3.1 70B）", 15, ORANGE, "bold", anchor="start")
    # 关键点
    marks = [
        (30, 512, BLUE, "2017 年翻译句子：约 1%", "start", 10, -16),
        (131072, 8192, ORANGE, "128K 上下文：73%", "end", -12, -10),
        (1048576, 8192, ORANGE, "1M 上下文：95%", "end", -14, 30),
    ]
    for n, d, color, label, anchor, dx, dy in marks:
        x, y = X(n), Y(attention_share(n, d))
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" stroke="#ffffff" stroke-width="2"/>'
        body += text(x + dx, y + dy, label, 15, color, "bold", anchor)
    svg("transformer-n-vs-d.svg",
        "自注意力的 n² 项在一层计算中的占比",
        "横轴是序列长度 n（对数坐标，10 到 100 万），纵轴是一层 Transformer 中 n² 项的计算占比。"
        "d=512 时，30 个 token 的句子只占约 1%，n=d 时约 14%；d=8192 时，128K 上下文占约 73%，1M 上下文占约 95%。",
        540, body)


if __name__ == "__main__":
    transformer_n_vs_d()
    print("wrote", OUT / "transformer-n-vs-d.svg")
