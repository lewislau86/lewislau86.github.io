"""Regenerate the Burn mathematics figures (Python + matplotlib).

Run from any directory: python scripts/generate-burn-math-figures.py
Only the six named SVG assets are written. Plot text is embedded as paths.
"""

from html import escape
from pathlib import Path
import math
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/burn"
BLUE = "#2563eb"
TEAL = "#0f766e"
ORANGE = "#b45309"
INK = "#172033"
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'


def svg(name, title, description, height, body):
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#64748b"/></marker></defs>
<rect width="960" height="{height}" rx="16" fill="#f8fafc"/>
<g font-family='{FONT}' fill="{INK}" text-anchor="middle">{body}</g></svg>'''
    ET.fromstring(document)
    (OUT / name).write_text(document + "\n", encoding="utf-8")


def text(x, y, value, size=23, color=INK, weight="normal"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'


def box(x, y, w, h, fill="#ffffff", stroke="#cbd5e1"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'


def arrow(x1, y1, x2, y2, color="#64748b"):
    return f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" stroke-width="3" fill="none" marker-end="url(#arrow)"/>'


def matrix(x, y, values, colors=None, cell=62):
    parts = []
    for row, entries in enumerate(values):
        for col, value in enumerate(entries):
            fill = colors[row][col] if colors else "#ffffff"
            parts.append(f'<rect x="{x+col*cell}" y="{y+row*cell}" width="{cell}" height="{cell}" fill="{fill}" stroke="#94a3b8"/>')
            parts.append(text(x + (col + 0.5) * cell, y + (row + 0.65) * cell, str(value), 26))
    return "".join(parts)


def matmul():
    body = text(480, 42, "矩阵乘法：一行与一列，逐项相乘后求和", 27, weight="bold")
    body += text(130, 97, "X · shape [1, 2]", 22, BLUE)
    body += matrix(68, 124, [[1, 2]], [["#dbeafe", "#dbeafe"]])
    body += text(238, 168, "×", 32)
    body += text(360, 97, "W · shape [2, 2]", 22, TEAL)
    body += matrix(298, 124, [[1, -1], [2, 1]], [["#ccfbf1", "#fef3c7"], ["#ccfbf1", "#fef3c7"]])
    body += arrow(453, 166, 506, 166)
    body += text(606, 97, "XW · shape [1, 2]", 22)
    body += matrix(544, 124, [[5, 1]], [["#ccfbf1", "#fef3c7"]])
    body += text(749, 164, "+", 30)
    body += text(844, 97, "b · [2]", 22)
    body += matrix(782, 124, [[0, 1]])
    body += box(60, 286, 400, 88, "#ecfdf5", TEAL)
    body += text(260, 323, "第 1 列：1 × 1 + 2 × 2 = 5", 23, TEAL)
    body += text(260, 353, "两项来自同一行 X 与 W 的第一列", 19)
    body += box(500, 286, 400, 88, "#fffbeb", ORANGE)
    body += text(700, 323, "第 2 列：1 × (−1) + 2 × 1 = 1", 22, ORANGE)
    body += text(700, 353, "加上偏置后得到 Z = [5, 2]", 21)
    body += text(480, 418, "相乘的内部维度必须相等：[M, K] × [K, N] → [M, N]", 23, BLUE)
    svg("math-matmul.svg", "主线模型的矩阵乘法", "输入行 [1,2] 分别与权重的两列做点积得到 [5,1]，加偏置 [0,1] 后为 [5,2]。", 450, body)


def chain_rule():
    body = text(480, 43, "链式法则：局部变化率沿路径相乘", 27, weight="bold")
    for x, label, value in [(60, "输入 x", "3"), (360, "u = 2x", "6"), (660, "y = u²", "36")]:
        body += box(x, 104, 240, 110)
        body += text(x + 120, 145, label, 24)
        body += text(x + 120, 188, value, 30, BLUE, "bold")
    body += arrow(304, 158, 351, 158) + arrow(604, 158, 651, 158)
    body += text(480, 258, "前向：先计算 u，再计算 y", 21)
    body += arrow(762, 324, 482, 324) + arrow(460, 324, 180, 324)
    body += text(750, 303, "起点：1", 22, TEAL)
    body += text(480, 303, "dy/du = 2u = 12", 22, TEAL)
    body += text(180, 303, "du/dx = 2", 22, TEAL)
    body += box(100, 367, 760, 60, "#ecfdf5", TEAL)
    body += text(480, 406, "dy/dx = (dy/du) × (du/dx) = 12 × 2 = 24", 25, TEAL)
    svg("math-chain-rule.svg", "串行计算的链式法则", "x 为 3，u 等于 2x 为 6，y 等于 u 平方为 36。反向把局部导数 12 与 2 相乘得到 24。", 455, body)


def softmax():
    body = text(480, 43, "Softmax：把分数转换成总和为 1 的概率", 26, weight="bold")
    panels = [(35, "原始分数 z", "[5, 2]", "分数可以超过 1"),
              (350, "减去最大值 5", "[0, −3]", "不改变最终概率"),
              (665, "指数再归一化", "[0.9526, 0.0474]", "两项相加为 1")]
    for x, label, value, caption in panels:
        body += box(x, 92, 260, 136)
        body += text(x + 130, 125, label, 22)
        body += text(x + 130, 170, value, 25, BLUE, "bold")
        body += text(x + 130, 207, caption, 18)
    body += arrow(302, 158, 341, 158) + arrow(617, 158, 656, 158)
    body += text(480, 275, "exp(0) = 1，exp(−3) ≈ 0.0498；每项除以 1.0498", 23)
    body += text(74, 334, "类 1", 21)
    body += '<rect x="130" y="310" width="700" height="35" rx="5" fill="#e2e8f0"/>'
    body += '<rect x="130" y="310" width="666.802" height="35" rx="5" fill="#2563eb"/>'
    body += text(880, 334, "95.26%", 21, BLUE)
    body += text(74, 389, "类 2", 21)
    body += '<rect x="130" y="365" width="700" height="35" rx="5" fill="#e2e8f0"/>'
    body += '<rect x="130" y="365" width="33.198" height="35" rx="5" fill="#0f766e"/>'
    body += text(880, 389, "4.74%", 21, TEAL)
    body += text(480, 447, "这里只演示概率变换；主线小模型的原始输出仍是数值 [5, 2]。", 20)
    svg("math-softmax.svg", "稳定的 softmax 计算", "把分数 [5,2] 减去最大值得到 [0,-3]，取指数并除以指数总和，得到约 0.9526 和 0.0474。", 475, body)


def configure_plots():
    preferred = Path("C:/Windows/Fonts/msyh.ttc")
    if preferred.exists():
        font_manager.fontManager.addfont(str(preferred))
        family = font_manager.FontProperties(fname=str(preferred)).get_name()
    else:
        family = "Noto Sans CJK SC"
    plt.rcParams.update({"font.family": family, "font.size": 14, "svg.fonttype": "path", "svg.hashsalt": "burn-math",
                         "axes.unicode_minus": False, "axes.labelcolor": INK,
                         "text.color": INK, "xtick.color": INK, "ytick.color": INK,
                         "figure.facecolor": "#f8fafc", "axes.facecolor": "#ffffff"})


def save_plot(fig, name, title, description):
    path = OUT / name
    fig.savefig(path, format="svg", metadata={"Date": None, "Creator": "Burn tutorial figure generator"})
    plt.close(fig)
    raw = path.read_text(encoding="utf-8")
    pos = raw.index(">", raw.index("<svg"))
    raw = raw[:pos] + ' role="img" aria-labelledby="title desc"' + raw[pos:]
    pos = raw.index(">", raw.index("<svg")) + 1
    raw = raw[:pos] + f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>' + raw[pos:]
    ET.fromstring(raw)
    path.write_text(raw, encoding="utf-8")


def activations():
    x = np.linspace(-3, 3, 401)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), layout="constrained")
    for ax in axes:
        ax.axhline(0, color="#94a3b8", linewidth=1)
        ax.axvline(0, color="#94a3b8", linewidth=1)
        ax.set(xlim=(-3.2, 3.2), ylim=(-3.2, 3.5), xlabel="输入 x", ylabel="输出 y")
        ax.grid(alpha=0.16)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].plot(x, x, color=BLUE, linewidth=3)
    axes[0].set_title("恒等函数：y = x", pad=14)
    axes[0].text(-2.7, 2.3, "斜率始终为 1", fontsize=13)
    axes[1].plot(x, np.maximum(0, x), color=TEAL, linewidth=3)
    axes[1].scatter([0], [0], s=65, facecolor="white", edgecolor=ORANGE, linewidth=2, zorder=4)
    axes[1].annotate("x = 0：折点\n数学上不可导", xy=(0, 0), xytext=(-2.7, 1.9),
                     arrowprops={"arrowstyle": "->", "color": ORANGE}, fontsize=12)
    axes[1].text(1.25, -1.1, "x > 0：斜率 1", fontsize=12, color=TEAL)
    axes[1].text(-2.9, -2.2, "x < 0：斜率 0", fontsize=12, color=TEAL)
    axes[1].set_title("ReLU：y = max(0, x)", pad=14)
    save_plot(fig, "math-activations.svg", "恒等函数与 ReLU", "恒等函数全程斜率为一；ReLU 负半轴为零、正半轴等于输入，零点存在不可导折点。")


def gradient_descent():
    fig, ax = plt.subplots(figsize=(10, 4.7), layout="constrained")
    w = np.linspace(-0.35, 3.5, 400)
    ax.plot(w, (2 * w - 4) ** 2, color=BLUE, linewidth=3)
    ax.scatter([0, 1.6, 2], [16, 0.64, 0], c=[ORANGE, TEAL, "#64748b"], s=70, zorder=4)
    ax.annotate("旧参数 w = 0\nL = 16，梯度 −16", xy=(0, 16), xytext=(0.6, 19),
                arrowprops={"arrowstyle": "->", "color": ORANGE}, color=ORANGE, fontsize=13)
    ax.annotate("新参数 w = 1.6\nL = 0.64", xy=(1.6, 0.64), xytext=(2.1, 7),
                arrowprops={"arrowstyle": "->", "color": TEAL}, color=TEAL, fontsize=13)
    ax.annotate("最小值在 w = 2", xy=(2, 0), xytext=(2.45, 2.2),
                arrowprops={"arrowstyle": "->", "color": "#64748b"}, fontsize=12)
    ax.annotate("", xy=(1.6, 11.5), xytext=(0, 11.5),
                arrowprops={"arrowstyle": "->", "color": TEAL, "lw": 2})
    ax.text(0.1, 12.8, "一次更新：0 − 0.1 × (−16) = 1.6", color=TEAL, fontsize=13)
    ax.set(xlim=(-0.35, 3.5), ylim=(-1.5, 23), xlabel="参数 w", ylabel="损失 L(w)",
           title="梯度下降的一个标量例子：L(w) = (2w − 4)²")
    ax.grid(alpha=0.16)
    ax.spines[["top", "right"]].set_visible(False)
    save_plot(fig, "math-gradient-descent.svg", "梯度下降的一步", "损失为 (2w-4) 的平方。参数从零沿负梯度以学习率 0.1 更新到 1.6，损失由 16 降为 0.64；最小值在 w=2。")


def derivative():
    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
    x = np.linspace(2.35, 3.75, 300)
    ax.plot(x, x*x+x, color=BLUE, linewidth=3, label="曲线：f(x) = x² + x")
    ax.plot(x, 12 + 7 * (x - 3), color=TEAL, linewidth=2.5, label="x = 3 处切线：斜率 7")
    ax.plot(x, 12 + 7.5 * (x - 3), color=ORANGE, linewidth=2, linestyle="--", label="从 3 到 3.5 的割线：斜率 7.5")
    ax.scatter([3, 3.5], [12, 15.75], color=[TEAL, ORANGE], s=65, zorder=4)
    ax.annotate("(3, 12)", xy=(3, 12), xytext=(2.48, 12.5),
                arrowprops={"arrowstyle": "->", "color": TEAL}, color=TEAL, fontsize=13)
    ax.annotate("(3.5, 15.75)", xy=(3.5, 15.75), xytext=(3.15, 18.1),
                arrowprops={"arrowstyle": "->", "color": ORANGE}, color=ORANGE, fontsize=13)
    ax.text(2.43, 7.2, "把第二个点移近 x = 3，割线斜率趋近 7。", fontsize=13)
    ax.set(xlim=(2.35, 3.75), ylim=(6.5, 20), xlabel="输入 x", ylabel="输出 f(x)",
           title="导数是当前点附近的变化率")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.16)
    ax.spines[["top", "right"]].set_visible(False)
    save_plot(fig, "math-derivative.svg", "从割线斜率理解导数", "函数 x 平方加 x 在 x=3 处的切线斜率为七。从 x=3 到 x=3.5 的割线斜率为七点五；当后一点靠近三时割线斜率趋近七。")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    assert math.isclose(1 / (1 + math.exp(-3)), 0.9525741268224334)
    matmul()
    chain_rule()
    softmax()
    configure_plots()
    activations()
    gradient_descent()
    derivative()
    print("Generated 6 Burn math SVG figures.")
