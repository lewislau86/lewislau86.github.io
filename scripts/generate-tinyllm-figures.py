"""Regenerate the TinyLLM tutorial figures (Python + matplotlib + NumPy).

Run from any directory: python scripts/generate-tinyllm-figures.py
All figures are written to docs/public/tinyllm/figures/. Diagrams are hand-built
SVG (text stays selectable); plots use matplotlib with text embedded as paths.
The first-run loss curve reads scripts/data/tinyllm-first-run-log.json, which is
produced by running the first-run notebook (see the README section on TinyLLM).
"""

from html import escape
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/public/tinyllm/figures"
DATA = ROOT / "scripts/data"
BLUE = "#2563eb"
TEAL = "#0f766e"
ORANGE = "#b45309"
RED = "#b91c1c"
GRAY = "#64748b"
INK = "#172033"
FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'


# ---------- 手绘 SVG 工具（与 Burn 配图脚本保持同一风格） ----------

def svg(name, title, description, height, body, width=960):
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs>{{MARKERS}}</defs>
<rect width="{width}" height="{height}" rx="16" fill="#f8fafc"/>
<g font-family='{FONT}' fill="{INK}" text-anchor="middle">{body}</g></svg>'''
    document = document.replace("{MARKERS}", "".join(
        f'<marker id="arrow-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="{c}"/></marker>'
        for c in (BLUE, TEAL, ORANGE, RED, GRAY, INK, "#7c3aed")))
    ET.fromstring(document)
    (OUT / name).write_text(document + "\n", encoding="utf-8")


def text(x, y, value, size=22, color=INK, weight="normal", anchor="middle"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'


def box(x, y, w, h, fill="#ffffff", stroke="#cbd5e1", dash=False, width=2):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="{width}"{extra}/>'


def arrow(x1, y1, x2, y2, color=GRAY, width=3):
    return f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" stroke-width="{width}" fill="none" marker-end="url(#arrow-{color[1:]})"/>'


def path(d, color=GRAY, width=3, dash=False):
    extra = ' stroke-dasharray="7 5"' if dash else ""
    return f'<path d="{d}" stroke="{color}" stroke-width="{width}" fill="none" marker-end="url(#arrow-{color[1:]})"{extra}/>'


def circle(x, y, r=18, fill="#ffffff", stroke=GRAY):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>'


# ---------- 第 2 章：张量与自动求导 ----------

def tensor_shape():
    """[2, 3, 4] 张量：两张 3×4 的表，高亮 hidden[0, 1, :]。"""
    body = text(480, 44, "形状 [2, 3, 4] = 2 条样本 × 每条 3 个 token × 每个 token 4 个特征", 24, weight="bold")
    cell = 56
    values = np.arange(24).reshape(2, 3, 4)
    for b in range(2):
        ox, oy = 90 + b * 430, 120
        body += text(ox + 2 * cell, oy - 22, f"样本 b = {b}", 21, BLUE if b == 0 else INK, "bold")
        for t in range(3):
            body += text(ox - 34, oy + t * cell + 36, f"t={t}", 18, GRAY)
            for h in range(4):
                hit = b == 0 and t == 1
                fill = "#dbeafe" if hit else "#ffffff"
                stroke = BLUE if hit else "#94a3b8"
                body += f'<rect x="{ox + h * cell}" y="{oy + t * cell}" width="{cell}" height="{cell}" fill="{fill}" stroke="{stroke}" stroke-width="{2.5 if hit else 1.2}"/>'
                body += text(ox + h * cell + cell / 2, oy + t * cell + 36, str(values[b, t, h]), 20)
        for h in range(4):
            body += text(ox + h * cell + cell / 2, oy + 3 * cell + 26, f"h={h}", 16, GRAY)
    body += arrow(330, 250, 330, 330, BLUE)
    body += box(170, 335, 620, 76, "#eff6ff", BLUE)
    body += text(480, 368, "hidden[0, 1, :] = [4, 5, 6, 7]", 22, BLUE, "bold")
    body += text(480, 397, "第 0 条样本、第 1 个 token 的全部 4 个特征（下标从 0 开始）", 18)
    body += text(480, 452, "第 0 轴 batch：选哪张表　·　第 1 轴 seq：选哪一行　·　第 2 轴 hidden：选哪一格", 19, GRAY)
    svg("tensor-shape.svg", "形状为 [2,3,4] 的张量",
        "两张 3 行 4 列的表分别代表两条样本，每行是一个 token 的 4 个特征；第 0 张表第 1 行被高亮，值为 4、5、6、7。", 480, body)


def broadcast():
    """[2,3,4] + [4]：bias 沿前两轴复制后逐格相加。"""
    body = text(480, 44, "广播：形状 [3, 4] + [4]，偏置被“复制”到每一行再逐格相加", 24, weight="bold")
    cell = 54
    rows = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]
    bias = [1, 2, 3, 4]

    def grid(ox, oy, data, fill, stroke="#94a3b8", ghost=None):
        out = ""
        for r, row in enumerate(data):
            for c, v in enumerate(row):
                f = fill if ghost is None or r in ghost else "#f1f5f9"
                out += f'<rect x="{ox + c * cell}" y="{oy + r * cell}" width="{cell}" height="{cell}" fill="{f}" stroke="{stroke}" stroke-width="1.2"/>'
                color = INK if ghost is None or r in ghost else "#94a3b8"
                out += text(ox + c * cell + cell / 2, oy + r * cell + 35, str(v), 20, color)
        return out

    body += text(158, 98, "hidden[0]：[3, 4]", 19)
    body += grid(50, 115, rows, "#ffffff")
    body += text(298, 205, "+", 34)
    body += text(438, 98, "bias：[4] → 看作 [1, 4] → 复制成 [3, 4]", 18, ORANGE)
    body += grid(330, 115, [bias, bias, bias], "#fef3c7", ghost={0})
    body += text(438, 302, "↑ 只有第一行是真实数据，灰色行是广播出来的（不占内存）", 16, ORANGE)
    body += text(590, 205, "=", 34)
    body += grid(640, 115, [[a + b for a, b in zip(r, bias)] for r in rows], "#dcfce7")
    body += text(748, 98, "结果：[3, 4]", 19, TEAL)
    body += box(110, 324, 740, 112, "#ffffff")
    body += text(480, 360, "规则：从最右边一轴开始对齐，两轴长度相等或其中一个为 1 才能配对。", 20)
    body += text(480, 394, "[2, 3, 4] + [4]：4 对 4 可以，左边缺的轴当作 1", 20, TEAL)
    body += text(480, 424, "[2, 3, 4] + [3]：4 对 3，无法配对，报错", 20, RED)
    svg("broadcast.svg", "广播示意",
        "3 行 4 列的隐藏向量加上长度为 4 的偏置：偏置被看作一行并复制到三行，逐格相加得到同形状结果。", 460, body)


def compute_graph():
    """w → ×x → p → −t → ² → L，前向数值在上，反向梯度在下。"""
    body = text(480, 40, "一次前向记录计算图，backward() 沿原路返回并用链式法则相乘", 23, weight="bold")
    nodes = [("w", "参数", BLUE), ("p = w·x", "乘以 x=3", INK), ("d = p − t", "减去 t=1", INK), ("L = d²", "平方", INK)]
    values = ["2", "6", "5", "25"]
    grads = ["∂L/∂w = 30", "∂L/∂p = 10", "∂L/∂d = 10", "∂L/∂L = 1"]
    local = ["× x = ×3", "× 1", "× 2d = ×10"]
    xs = [120, 360, 600, 840]
    for i, ((name, sub, color), x) in enumerate(zip(nodes, xs)):
        body += box(x - 90, 130, 180, 74, "#eff6ff" if i == 0 else "#ffffff", BLUE if i == 0 else "#cbd5e1")
        body += text(x, 165, name, 22, color, "bold")
        body += text(x, 192, sub, 16, GRAY)
        body += text(x, 112, f"值 {values[i]}", 19, TEAL)
        body += text(x, 260, grads[i], 19, ORANGE, "bold")
    for i in range(3):
        a, b = xs[i] + 92, xs[i + 1] - 92
        body += arrow(a, 150, b, 150, TEAL)
        body += arrow(b, 186, a, 186, ORANGE)
        body += text((a + b) / 2, 214, local[i], 16, ORANGE)
    body += text(120, 318, "前向（绿）：从左往右算数值", 18, TEAL, anchor="start")
    body += text(120, 346, "反向（橙）：从 L=1 出发往左，每过一个运算就乘它的局部导数", 18, ORANGE, anchor="start")
    body += box(120, 368, 720, 56, "#fffbeb", ORANGE)
    body += text(480, 404, "∂L/∂w = 1 × 10 × 1 × 3 = 30　　（梯度为正 → 把 w 调小，损失下降）", 20, ORANGE)
    svg("compute-graph.svg", "单参数计算图的前向与反向",
        "w=2 乘以 x=3 得 6，减 1 得 5，平方得损失 25；反向从 1 开始依次乘 10、1、3，得到 w 的梯度 30。", 450, body)


def gradient_step():
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    w = np.linspace(-0.2, 2.4, 300)
    L = (3 * w - 1) ** 2
    ax.plot(w, L, color=BLUE, lw=2.5, label="L(w) = (3w − 1)²")
    ax.plot(w, 25 + 30 * (w - 2), color=ORANGE, lw=1.6, ls="--", label="w=2 处的切线，斜率 = 梯度 30")
    ax.scatter([2, 1.7], [25, 16.81], color=[ORANGE, TEAL], zorder=5, s=60)
    ax.annotate("", xy=(1.7, 16.81), xytext=(2, 25), arrowprops={"arrowstyle": "->", "color": TEAL, "lw": 2})
    ax.text(2.06, 22.5, "w = 2，L = 25", color=ORANGE, fontsize=13)
    ax.text(0.45, 22.5, "走一步：w ← 2 − 0.01 × 30 = 1.7\nL 降到 16.81", color=TEAL, fontsize=13)
    ax.scatter([1 / 3], [0], color=GRAY, s=40, zorder=5)
    ax.text(0.38, 1.5, "最低点 w = 1/3", color=GRAY, fontsize=12)
    ax.set_ylim(-2, 34)
    ax.set_xlabel("参数 w")
    ax.set_ylabel("损失 L")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "gradient-step.svg", "沿负梯度走一步",
              "损失曲线 (3w-1)^2 上，w=2 处切线斜率为 30；以学习率 0.01 更新到 w=1.7，损失从 25 降到 16.81。")


# ---------- 第 10 章：归一化 ----------

def norm_motivation():
    """没有归一化时，残差流尺度随层数漂移；Pre-Norm 让每个子层看到的输入 RMS 保持为 1。"""
    rng = np.random.default_rng(0)
    d, L = 64, 32
    x0 = rng.normal(size=(256, d))
    rms = lambda a: float(np.sqrt((a ** 2).mean()))
    plain_in, prenorm_in, stream = [], [], []
    x_plain, x_pre = x0.copy(), x0.copy()
    for _ in range(L):
        W = rng.normal(scale=1.0 / np.sqrt(d), size=(d, d))
        plain_in.append(rms(x_plain))
        x_plain = x_plain + np.tanh(x_plain @ W) * 1.0 + x_plain @ W * 0.5
        normed = x_pre / np.sqrt((x_pre ** 2).mean(axis=-1, keepdims=True) + 1e-6)
        prenorm_in.append(rms(normed))
        stream.append(rms(x_pre))
        x_pre = x_pre + np.tanh(normed @ W) + normed @ W * 0.5
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    layers = np.arange(1, L + 1)
    ax.semilogy(layers, plain_in, color=RED, lw=2.4, marker="o", ms=3.5, label="不做归一化：第 l 层子层看到的输入 RMS")
    ax.semilogy(layers, stream, color=GRAY, lw=1.8, ls="--", label="Pre-Norm：残差流本身的 RMS（仍会缓慢增长）")
    ax.semilogy(layers, prenorm_in, color=TEAL, lw=2.6, label="Pre-Norm：子层实际看到的输入 RMS（始终≈1）")
    ax.set_xlabel("层号 l")
    ax.set_ylabel("RMS（对数刻度）")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "norm-motivation.svg", "为什么需要归一化",
              "32 层随机残差网络中，不做归一化时子层输入的 RMS 随层数指数增长；Pre-Norm 让每个子层输入的 RMS 保持约为 1，残差流本身缓慢增长。")


def norm_three_ways():
    """同一个向量及其整体平移后，三种归一化的输出对比。"""
    def ln(v):
        return (v - v.mean()) / np.sqrt(v.var())

    def rmsn(v):
        return v / np.sqrt((v ** 2).mean())

    def scalen(v):
        return v / np.linalg.norm(v)

    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = a + 10
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.8), layout="constrained", sharey=False)
    titles = ["输入", "LayerNorm", "RMSNorm", "ScaleNorm（g = 1）"]
    funcs = [lambda v: v, ln, rmsn, scalen]
    idx = np.arange(4)
    for ax, title, fn in zip(axes, titles, funcs):
        ax.bar(idx - 0.2, fn(a), width=0.38, color=BLUE, label="x = [1, 2, 3, 4]")
        ax.bar(idx + 0.2, fn(b), width=0.38, color=ORANGE, label="x + 10")
        ax.set_title(title, fontsize=14)
        ax.set_xticks(idx, [f"x{i + 1}" for i in idx])
        ax.axhline(0, color=GRAY, lw=0.8)
        ax.grid(alpha=0.2, axis="y")
    axes[0].legend(fontsize=10, loc="upper left")
    axes[1].text(0.5, -0.17, "两组完全重合：平移被抵消", transform=axes[1].transAxes, ha="center", fontsize=11, color=TEAL)
    axes[2].text(0.5, -0.17, "平移后各分量差别被压小", transform=axes[2].transAxes, ha="center", fontsize=11, color=ORANGE)
    axes[3].text(0.5, -0.17, "长度都为 1，形状同 RMSNorm", transform=axes[3].transAxes, ha="center", fontsize=11, color=GRAY)
    save_plot(fig, "norm-three-ways.svg", "三种归一化对同一向量的处理",
              "输入 [1,2,3,4] 与整体加 10 后的 [11,12,13,14]：LayerNorm 输出完全相同；RMSNorm 与 ScaleNorm 输出不同，平移后的向量被压成接近常数。")


def norm_geometry():
    """二维中的 RMSNorm：任何非零向量都被拉到半径 √d 的圆上，方向不变。"""
    rng = np.random.default_rng(3)
    pts = rng.normal(size=(18, 2))
    pts = pts / np.linalg.norm(pts, axis=1, keepdims=True) * rng.uniform(0.4, 3.6, size=(18, 1))
    r = np.sqrt(2)
    out = pts / np.sqrt((pts ** 2).mean(axis=1, keepdims=True))
    fig, ax = plt.subplots(figsize=(6.4, 6.0), layout="constrained")
    t = np.linspace(0, 2 * np.pi, 200)
    ax.plot(r * np.cos(t), r * np.sin(t), color=TEAL, lw=2, label="RMS = 1 的点（半径 √2 的圆）")
    for p, q in zip(pts, out):
        ax.annotate("", xy=q, xytext=p, arrowprops={"arrowstyle": "->", "color": "#94a3b8", "lw": 1})
    ax.scatter(pts[:, 0], pts[:, 1], color=ORANGE, s=28, zorder=4, label="归一化前的向量")
    ax.scatter(out[:, 0], out[:, 1], color=TEAL, s=28, zorder=5, label="RMSNorm 之后")
    ax.scatter([0], [0], color=INK, s=12)
    ax.set_aspect("equal")
    lim = 4.2
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("特征 x1")
    ax.set_ylabel("特征 x2")
    ax.legend(loc="lower left", fontsize=10, framealpha=0.95)
    ax.grid(alpha=0.2)
    ax.set_title("d = 2：只改长度，不改方向", fontsize=14)
    save_plot(fig, "norm-geometry.svg", "RMSNorm 的几何意义",
              "二维平面上散落的向量沿各自方向被拉伸或压缩，落到半径为根号 2 的圆上：RMSNorm 只改变长度，不改变方向。")


def pre_post_norm():
    body = text(480, 40, "同样三个零件，只是“归一化放在哪里”不同", 24, weight="bold")
    for k, (title, color, x0) in enumerate([("Pre-Norm（TinyLLM 采用）", TEAL, 60), ("Post-Norm（原始 Transformer）", ORANGE, 510)]):
        cx = x0 + 195
        body += text(cx, 86, title, 21, color, "bold")
        body += text(cx, 122, "x", 22, weight="bold")
        if k == 0:
            body += arrow(cx, 130, cx, 160)
            body += box(cx - 80, 162, 160, 46, "#ecfdf5", TEAL)
            body += text(cx, 192, "Norm", 20, TEAL, "bold")
            body += arrow(cx, 208, cx, 236)
            body += box(cx - 80, 238, 160, 46)
            body += text(cx, 268, "子层 F", 20)
            body += arrow(cx, 284, cx, 318)
            body += circle(cx, 338)
            body += text(cx, 346, "+", 24, weight="bold")
            body += path(f"M{cx} 140 H{cx - 150} V338 H{cx - 20}", TEAL, 4)
            body += text(cx - 160, 250, "直通路径", 17, TEAL, anchor="end")
            body += arrow(cx, 356, cx, 392)
            body += text(cx, 418, "输出 = x + F(Norm(x))", 20, weight="bold")
            body += text(cx, 452, "直通路径上什么也没有，梯度可直达", 17, TEAL)
        else:
            body += arrow(cx, 130, cx, 236)
            body += box(cx - 80, 238, 160, 46)
            body += text(cx, 268, "子层 F", 20)
            body += arrow(cx, 284, cx, 318)
            body += circle(cx, 338)
            body += text(cx, 346, "+", 24, weight="bold")
            body += path(f"M{cx} 160 H{cx - 150} V338 H{cx - 20}", GRAY, 4)
            body += arrow(cx, 356, cx, 374)
            body += box(cx - 80, 376, 160, 46, "#fffbeb", ORANGE)
            body += text(cx, 406, "Norm", 20, ORANGE, "bold")
            body += text(cx, 452, "输出 = Norm(x + F(x))：直通路径也要穿过 Norm", 17, ORANGE)
    body += f'<line x1="480" y1="70" x2="480" y2="470" stroke="#e2e8f0" stroke-width="2"/>'
    svg("pre-post-norm.svg", "Pre-Norm 与 Post-Norm 的数据流",
        "左：Pre-Norm 先归一化再进入子层，残差直通路径不经过归一化；右：Post-Norm 先相加再归一化，直通路径也要经过归一化。", 490, body)


# ---------- 第 1 章：先跑通 ----------

def first_run_loss():
    src = DATA / "tinyllm-first-run-log.json"
    if not src.exists():
        print("skip first-run-loss.svg: run the first-run notebook to create", src)
        return
    log = json.loads(src.read_text(encoding="utf-8"))
    loss = np.array(log["loss"])
    smooth = np.convolve(loss, np.ones(15) / 15, mode="valid")
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.plot(loss, color="#cbd5e1", lw=0.8, label="训练损失（每一步）")
    ax.plot(np.arange(len(smooth)) + 7, smooth, color=BLUE, lw=2.4, label="训练损失（15 步滑动平均）")
    ax.plot(log["val_step"], log["val_loss"], color=RED, lw=2.2, label="验证损失（没训练过的 4 首诗）")
    ax.axhline(log["uniform"], color=ORANGE, ls="--", lw=1.6)
    ax.text(len(loss) * 0.6, log["uniform"] - 0.55, f"完全乱猜：ln(词表大小) ≈ {log['uniform']:.2f}", color=ORANGE, fontsize=12)
    ax.set_xlabel("训练步数")
    ax.set_ylabel("交叉熵损失")
    ax.set_ylim(0, max(max(log["val_loss"]), loss[0]) + 0.6)
    ax.legend(loc="center right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "first-run-loss.svg", "最小 TinyLLM 的训练与验证损失",
              f"训练损失从约 {loss[0]:.1f} 迅速降到约 {smooth[-1]:.2f}；验证损失只在开头略降，随后升到约 {log['val_loss'][-1]:.1f}，高于乱猜水平，说明模型在背诵训练集。")


# ---------- 第 9、7、3、4、14、17 章共用工具 ----------

PURPLE = "#7c3aed"
MONO = '"Cascadia Mono", "SFMono-Regular", Menlo, Consolas, monospace'
SOFT = {BLUE: "#eff6ff", TEAL: "#ecfdf5", ORANGE: "#fffbeb", RED: "#fef2f2", PURPLE: "#f5f3ff", GRAY: "#ffffff"}


def mtext(x, y, value, size=17, color=INK, weight="normal", anchor="middle"):
    """等宽文字；只用于纯 ASCII 内容（等宽字体多数不含中文）。"""
    family = f" font-family='{MONO}'" if value.isascii() else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{family}>{escape(value)}</text>')


def cbox(x, y, w, h, color=GRAY, dash=False, width=2):
    return box(x, y, w, h, SOFT.get(color, "#ffffff"), color, dash, width)


def load(name):
    src = DATA / name
    if not src.exists():
        raise SystemExit(f"missing {src}: run python scripts/tinyllm-figure-data.py first")
    return json.loads(src.read_text(encoding="utf-8"))


# ---------- 第 9 章：初始化与残差 ----------

def init_fan_in():
    d = load("tinyllm-init-fan-in.json")
    fig, ax = plt.subplots(figsize=(10, 5.0), layout="constrained")
    w = d["widths"]
    ax.loglog(w, d["fixed_1"], marker="o", color=RED, lw=2.2, label="固定 std = 1")
    ax.loglog(w, d["fixed_0.02"], marker="o", color=ORANGE, lw=2.2, label="固定 std = 0.02")
    ax.loglog(w, d["he"], marker="o", color=PURPLE, lw=2.2, label="He：std = √(2 / fan_in)")
    ax.loglog(w, d["xavier"], marker="o", color=TEAL, lw=2.8, label="Xavier：std = √(2 / (fan_in + fan_out))")
    ax.axhline(1, color=GRAY, lw=1, ls="--")
    ax.set_xticks(w, [str(v) for v in w])
    ax.set_xlabel("输入宽度 fan_in（输出宽度相同）")
    ax.set_ylabel("输出标准差（输入 std = 1）")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, fontsize=11, frameon=False)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "init-fan-in.svg", "不同初始化下线性层输出的尺度",
              "输入标准差为 1 时，固定 std 的初始化让输出标准差随宽度按根号增长；Xavier 让输出标准差保持在 1 附近，He 保持在约 1.41（为 ReLU 预留的放大）。")


def residual_depth():
    d = load("tinyllm-residual-depth.json")
    layers = np.arange(1, d["depth"] + 1)
    style = {"plain": ("纯堆叠 x = F(x)", RED), "residual": ("残差、无归一化 x = x + F(x)", ORANGE),
             "pre_ln": ("Pre-LN x = x + F(LN(x))", TEAL), "post_ln": ("Post-LN x = LN(x + F(x))", BLUE)}
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.0), layout="constrained")
    for key, (label, color) in style.items():
        axes[0].semilogy(layers, d["rms"][key], color=color, lw=2.2, label=label)
        axes[1].semilogy(layers, d["grad"][key], color=color, lw=2.2, label=label)
    axes[0].set_title("前向：每层输出的 RMS", fontsize=14)
    axes[1].set_title("反向：损失对每层输出的梯度范数", fontsize=14)
    for ax in axes:
        ax.set_xlabel("层号")
        ax.grid(alpha=0.25, which="both")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2, fontsize=11, frameon=False)
    save_plot(fig, "residual-depth.svg", "32 层网络中的信号与梯度",
              "32 层随机初始化网络：纯堆叠时输出 RMS 逐层缩小、梯度越靠近输入越小；无归一化的残差让 RMS 逐层增大、靠近输入的梯度变大；Pre-LN 的增长缓和得多；Post-LN 每层输出 RMS 固定为 1。")


def residual_path():
    body = text(480, 40, "残差块：前向多一条加法，反向多一条直通的梯度路径", 23, weight="bold")
    body += text(80, 125, "x", 26, BLUE, "bold")
    body += path("M100 118 H190", BLUE)
    body += cbox(195, 88, 200, 60, BLUE)
    body += text(295, 125, "子层 F", 20, BLUE, "bold")
    body += path("M395 118 H470", BLUE)
    body += circle(490, 118, 20)
    body += text(490, 126, "+", 26, weight="bold")
    body += path("M510 118 H590", BLUE)
    body += text(600, 126, "y = x + F(x)", 22, BLUE, "bold", anchor="start")
    body += path("M140 118 V210 H490 V140", TEAL, 3.5)
    body += text(315, 232, "直通路径：x 原样加到输出上", 16, TEAL)
    body += cbox(60, 270, 840, 150, ORANGE)
    body += text(480, 305, "反向传播时，从 y 传回来的梯度 g 分成两路再相加：", 18, ORANGE, "bold")
    body += mtext(480, 345, "dL/dx = g + J_F(x)^T · g", 22, INK, "bold")
    body += text(480, 385, "第一项来自直通路径，不经过 F 的任何运算；第二项经过 F 的雅可比，可能被放大或缩小。", 16, INK)
    body += text(480, 455, "直通路径保证梯度至少有一条“原样”的通道；多层叠加后整体仍可能变大或变小，所以还要配合初始化与归一化。", 15, GRAY)
    svg("residual-path.svg", "残差连接的前向与反向",
        "输入 x 经过子层 F 后与 x 本身相加得到 y；反向时梯度 g 一路原样传回 x，另一路经过 F 的雅可比，两路相加。", 480, body)


# ---------- 第 7 章：激活与门控前馈层 ----------

def activation_fit():
    d = load("tinyllm-activation-fit.json")
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    ax.plot(d["x"], d["y"], color=GRAY, lw=4, alpha=0.45, label="目标 sin(x)")
    ax.plot(d["x"], d["linear"]["pred"], color=RED, lw=2.2, ls="--", label=f"Linear → Linear（无激活），MSE {d['linear']['loss']:.3f}")
    ax.plot(d["x"], d["gelu"]["pred"], color=TEAL, lw=2.2, label=f"Linear → GELU → Linear，MSE {d['gelu']['loss']:.1e}")
    ax.set_xlabel("x")
    ax.set_ylabel("输出")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "activation-fit.svg", "有无激活函数时的拟合结果",
              "同样是 1→32→1 的两层网络训练 1500 步：中间没有激活函数时只能拟合出一条直线；加入 GELU 后几乎与 sin 曲线重合。")


def swiglu_vs_ffn():
    body = text(480, 40, "普通 FFN 与 SwiGLU：参数量相同，结构不同", 23, weight="bold")
    # 普通 FFN
    body += text(240, 85, "普通 FFN（中间宽度 4d）", 18, BLUE, "bold")
    body += mtext(240, 106, "x  [B, T, d]", 15, GRAY)
    body += cbox(140, 132, 200, 46, BLUE) + mtext(240, 161, "up: d → 4d", 15, INK, "bold")
    body += arrow(240, 178, 240, 196, BLUE)
    body += cbox(140, 200, 200, 46, BLUE) + text(240, 229, "GELU / ReLU", 15, INK, "bold")
    body += arrow(240, 246, 240, 264, BLUE)
    body += cbox(140, 268, 200, 46, BLUE) + mtext(240, 297, "down: 4d → d", 15, INK, "bold")
    body += mtext(240, 340, "out [B, T, d]", 15, GRAY)
    body += text(240, 380, "权重：d·4d + 4d·d = 8d²", 17, BLUE, "bold")
    body += arrow(240, 113, 240, 128, BLUE)
    # SwiGLU
    body += text(690, 85, "SwiGLU（中间宽度 m ≈ 8d/3）", 18, TEAL, "bold")
    body += mtext(690, 106, "x  [B, T, d]", 15, GRAY)
    body += cbox(530, 132, 145, 46, TEAL) + mtext(602, 161, "gate: d → m", 14, INK, "bold")
    body += cbox(705, 132, 145, 46, TEAL) + mtext(777, 161, "value: d → m", 14, INK, "bold")
    body += path("M690 113 V118 H602 V128", TEAL) + path("M690 118 H777 V128", TEAL)
    body += cbox(530, 200, 145, 46, TEAL) + text(602, 229, "SiLU", 15, INK, "bold")
    body += arrow(602, 178, 602, 196, TEAL)
    body += circle(690, 291, 20, SOFT[TEAL], TEAL) + text(690, 299, "⊙", 22, TEAL, "bold")
    body += path("M602 246 V291 H668", TEAL) + path("M777 178 V291 H712", TEAL)
    body += text(800, 320, "逐元素相乘：门控", 13.5, TEAL)
    body += cbox(590, 330, 200, 40, TEAL) + mtext(690, 356, "down: m → d", 15, INK, "bold")
    body += arrow(690, 311, 690, 326, TEAL)
    body += text(690, 400, "权重：3 · d · m = 3 · d · 8d/3 = 8d²", 17, TEAL, "bold")
    body += f'<line x1="465" y1="70" x2="465" y2="410" stroke="#e2e8f0" stroke-width="2"/>'
    body += text(480, 445, "例：d = 12 时，普通 FFN 用 m = 48 有 1152 个权重；SwiGLU 用 m = 32，也是 1152 个。", 16, GRAY)
    svg("swiglu-vs-ffn.svg", "普通前馈层与 SwiGLU 的结构对比",
        "普通 FFN 先把 d 维升到 4d，过激活函数后降回 d，权重 8d²；SwiGLU 用 gate 与 value 两条投影升到 m 维，gate 经过 SiLU 后与 value 逐元素相乘，再降回 d，中间宽度取 8d/3 时权重也是 8d²。", 470, body)


# ---------- 第 3 章：词元化 ----------

def utf8_lengths():
    samples = [("A", "A"), ("猫", "猫"), ("é", "é（一个码点）"), ("é", "e + 组合重音"), ("👩‍💻", "👩‍💻 组合 emoji")]
    body = text(480, 40, "同一个“字”，码点数和字节数可以完全不同", 23, weight="bold")
    body += text(140, 85, "看起来", 15, GRAY, "bold") + text(390, 85, "Unicode 码点", 15, GRAY, "bold") + text(730, 85, "UTF-8 字节", 15, GRAY, "bold")
    for i, (s, label) in enumerate(samples):
        y = 105 + i * 70
        body += text(140, y + 32, label, 17, INK, "bold")
        cps = [f"U+{ord(c):04X}" for c in s]
        x = 260
        for cp in cps:
            body += cbox(x, y + 8, 82, 36, BLUE) + mtext(x + 41, y + 32, cp, 12.5, BLUE, "bold")
            x += 86
        bts = s.encode("utf-8")
        bx = 560
        for b in bts:
            body += f'<rect x="{bx}" y="{y + 10}" width="27" height="32" rx="4" fill="{SOFT[ORANGE]}" stroke="{ORANGE}" stroke-width="1.5"/>'
            body += mtext(bx + 13.5, y + 31, f"{b:02X}", 11, ORANGE)
            bx += 30
        body += text(bx + 18, y + 32, f"{len(bts)}", 16, ORANGE, "bold", anchor="start")
    body += text(480, 470, "len(text) 数码点，len(text.encode('utf-8')) 数字节；token 数还取决于具体分词器——这是四种不同的“长度”。", 15, GRAY)
    svg("utf8-lengths.svg", "码点与 UTF-8 字节",
        "A 是 1 个码点 1 个字节；猫是 1 个码点 3 个字节；é 是 1 个码点 2 个字节；e 加组合重音是 2 个码点 3 个字节；女人加零宽连接符加电脑的 emoji 是 3 个码点 11 个字节。", 495, body)


def bpe_merges():
    words = [(list("abab"), 3), (list("abac"), 2), (list("ad"), 1)]

    def merge(parts, pair):
        out, i = [], 0
        while i < len(parts):
            if i + 1 < len(parts) and (parts[i], parts[i + 1]) == pair:
                out.append(parts[i] + parts[i + 1])
                i += 2
            else:
                out.append(parts[i])
                i += 1
        return out

    states, notes = [words], ["起点：每个字母是一个单位"]
    for _ in range(2):
        counts = {}
        for parts, f in states[-1]:
            for pair in zip(parts, parts[1:]):
                counts[pair] = counts.get(pair, 0) + f
        best = min(counts, key=lambda p: (-counts[p], p))
        notes.append(f"合并 {best[0]} + {best[1]} → {best[0] + best[1]}（加权出现 {counts[best]} 次）")
        states.append([(merge(p, best), f) for p, f in states[-1]])
    body = text(480, 40, "BPE 训练：统计加权的相邻对，反复合并最常见的一对", 23, weight="bold")
    colors = [GRAY, BLUE, TEAL]
    for k, (state, note) in enumerate(zip(states, notes)):
        y = 80 + k * 125
        body += text(40, y + 20, f"第 {k} 步", 17, colors[k], "bold", anchor="start")
        body += text(130, y + 20, note, 16, colors[k], anchor="start")
        x = 60
        for parts, f in state:
            px = x
            for part in parts:
                w = 34 + 18 * (len(part) - 1)
                body += cbox(px, y + 38, w, 44, colors[k] if len(part) > 1 else GRAY)
                body += mtext(px + w / 2, y + 66, part, 17, INK, "bold")
                px += w + 4
            body += text(px + 8, y + 66, f"× {f}", 15, GRAY, anchor="start")
            x = px + 90
    body += text(480, 470, "训练得到的是一份有顺序的合并规则；编码新文本时按这份顺序合并，不再重新统计。", 15, GRAY)
    svg("bpe-merges.svg", "BPE 的两步合并",
        "语料 abab 出现 3 次、abac 2 次、ad 1 次。第 1 步 a+b 加权出现 8 次，合并为 ab；第 2 步 ab+ab 出现 3 次，合并为 abab。", 495, body)


def label_shift():
    body = text(480, 40, "下一词元训练：输入去掉最后一位，标签去掉第一位，补齐位置不算损失", 21, weight="bold")
    rows = [["<bos>", "猫", "<eos>", "<pad>", "<pad>", "<pad>"], ["<bos>", "我", "在", "学习", "。", "<eos>"]]
    cell, x0 = 92, 250
    for r, seq in enumerate(rows):
        y0 = 80 + r * 200
        body += text(40, y0 + 18, f"样本 {r + 1}", 17, INK, "bold", anchor="start")
        n = len(seq) - 1
        for i in range(n):
            tok = seq[i]
            pad = tok == "<pad>"
            body += f'<rect x="{x0 + i * cell}" y="{y0 + 30}" width="{cell - 6}" height="40" rx="6" fill="{"#f1f5f9" if pad else SOFT[BLUE]}" stroke="{GRAY if pad else BLUE}"/>'
            body += text(x0 + i * cell + cell / 2 - 3, y0 + 56, tok, 15, GRAY if pad else BLUE, "bold")
            body += mtext(x0 + i * cell + cell / 2 - 3, y0 + 92, "0" if pad else "1", 14, GRAY)
            lab = seq[i + 1]
            ignore = lab == "<pad>"
            body += f'<rect x="{x0 + i * cell}" y="{y0 + 104}" width="{cell - 6}" height="40" rx="6" fill="{"#f1f5f9" if ignore else SOFT[TEAL]}" stroke="{GRAY if ignore else TEAL}"/>'
            body += mtext(x0 + i * cell + cell / 2 - 3, y0 + 130, "-100", 14, GRAY, "bold") if ignore else text(x0 + i * cell + cell / 2 - 3, y0 + 130, lab, 15, TEAL, "bold")
        body += text(235, y0 + 56, "input_ids", 14, BLUE, anchor="end")
        body += text(235, y0 + 92, "attention_mask", 14, GRAY, anchor="end")
        body += text(235, y0 + 130, "labels", 14, TEAL, anchor="end")
    body += text(480, 470, "EOS 是要学会的结束目标，保留在标签里；PAD 对应的标签写成 -100，交叉熵用 ignore_index 跳过它。", 15, GRAY)
    svg("label-shift.svg", "输入与标签的错位和掩码",
        "两条样本补齐到同样长度后，input_ids 取前 n-1 位，labels 取后 n-1 位；attention_mask 中 1 表示有效、0 表示补齐；补齐位置的标签写成 -100，不参与损失，EOS 保留为最后一个目标。", 495, body)


# ---------- 第 4 章：词嵌入与输出层 ----------

def embedding_lookup():
    vocab = ["<pad>", "<eos>", "我", "在", "学习", "数学"]
    body = text(480, 40, "查表：token ID 就是嵌入矩阵的行号", 23, weight="bold")
    body += text(110, 95, "输入 ID", 16, GRAY, "bold")
    ids = [2, 3, 4]
    colors = [BLUE, TEAL, ORANGE]
    for i, (tid, c) in enumerate(zip(ids, colors)):
        body += cbox(70 + i * 0, 115 + i * 60, 80, 44, c) + mtext(110, 144 + i * 60, str(tid), 18, c, "bold")
    body += text(470, 95, "嵌入矩阵 E：[V = 6, d = 4]（可训练参数）", 16, GRAY, "bold")
    for r, word in enumerate(vocab):
        y = 112 + r * 46
        hit = r in ids
        c = colors[ids.index(r)] if hit else GRAY
        body += mtext(325, y + 28, str(r), 14, GRAY, anchor="end")
        body += text(363, y + 28, word, 14, c if hit else GRAY, "bold" if hit else "normal")
        for j in range(4):
            body += f'<rect x="{400 + j * 62}" y="{y}" width="58" height="40" rx="4" fill="{SOFT[c] if hit else "#ffffff"}" stroke="{c if hit else "#cbd5e1"}" stroke-width="{2 if hit else 1}"/>'
        if hit:
            k = ids.index(r)
            body += path(f"M152 {137 + k * 60} C220 {137 + k * 60} 240 {y + 20} 300 {y + 20}", c, 2)
            body += path(f"M650 {y + 20} C720 {y + 20} 730 {137 + k * 60} 768 {137 + k * 60}", c, 2)
    body += text(840, 95, "输出向量 [3, 4]", 16, GRAY, "bold")
    for i, c in enumerate(colors):
        for j in range(4):
            body += f'<rect x="{772 + j * 40}" y="{117 + i * 60}" width="36" height="40" rx="4" fill="{SOFT[c]}" stroke="{c}" stroke-width="2"/>'
    body += text(480, 420, "nn.Embedding 只是按行取值，等价于 one-hot 向量乘 E，但不必真的构造 one-hot。", 15, GRAY)
    body += text(480, 448, "ID 的大小没有含义：2 和 3 相邻，不代表“我”和“在”的向量相近。", 15, GRAY)
    svg("embedding-lookup.svg", "词嵌入查表",
        "输入 ID 2、3、4 分别取出 6 行 4 列嵌入矩阵的第 2、3、4 行，得到形状为 3×4 的向量序列。", 470, body)


def tied_output():
    body = text(480, 40, "输入查表与输出打分可以共用同一张表", 23, weight="bold")
    body += cbox(360, 160, 240, 120, PURPLE)
    body += text(480, 205, "E  [V, d]", 22, PURPLE, "bold")
    body += text(480, 240, "同一个 Parameter", 15, PURPLE)
    body += cbox(40, 80, 220, 60, BLUE) + text(150, 116, "输入：取第 i 行", 16, BLUE, "bold")
    body += mtext(150, 166, "ID → E[i]  [d]", 15, BLUE)
    body += path("M262 110 C320 110 330 180 356 190", BLUE)
    body += cbox(700, 80, 220, 60, TEAL) + text(810, 116, "输出：和每一行做点积", 16, TEAL, "bold")
    body += mtext(810, 166, "h · E[j] → logit_j", 15, TEAL)
    body += path("M604 190 C640 180 650 110 696 110", TEAL)
    body += cbox(700, 220, 220, 140, TEAL)
    body += mtext(810, 250, "h  [B, T, d]", 14, INK)
    body += mtext(810, 280, "logits = h @ E^T", 15, TEAL, "bold")
    body += mtext(810, 310, "[B, T, V]", 14, INK)
    body += text(810, 342, "softmax → 下一个 token 的概率", 13.5, GRAY)
    body += cbox(40, 220, 220, 140, BLUE)
    body += mtext(150, 250, "ids  [B, T]", 14, INK)
    body += mtext(150, 280, "x = E[ids]", 15, BLUE, "bold")
    body += mtext(150, 310, "[B, T, d]", 14, INK)
    body += text(150, 342, "再加位置、进 Transformer", 13.5, GRAY)
    body += text(480, 410, "共享后少一份 V×d 的权重；输入端和输出端的梯度都会汇入这同一张表。", 16, GRAY)
    svg("tied-output.svg", "输入嵌入与输出层共享权重",
        "输入端用 token ID 从 E 中取一行得到向量；输出端用隐藏向量 h 与 E 的每一行做点积得到每个候选 token 的 logit。两端使用同一个形状为 V×d 的参数 E。", 440, body)


def kv_cache():
    body = text(480, 40, "KV cache：每生成一步只算新 token 的 K、V，接到缓存后面", 22, weight="bold")
    toks = ["我", "在", "学", "习"]
    for step in range(3):
        y = 80 + step * 125
        n = 2 + step
        body += text(40, y + 24, "prefill" if step == 0 else f"decode 第 {step} 步", 16, INK, "bold", anchor="start")
        for i in range(n):
            new = (step == 0) or i == n - 1
            c = ORANGE if new else GRAY
            body += f'<rect x="{200 + i * 70}" y="{y + 4}" width="62" height="36" rx="5" fill="{SOFT[ORANGE] if new else "#f1f5f9"}" stroke="{c}"/>'
            body += text(231 + i * 70, y + 28, f"K{i + 1}", 14, c, "bold")
            body += f'<rect x="{200 + i * 70}" y="{y + 46}" width="62" height="36" rx="5" fill="{SOFT[ORANGE] if new else "#f1f5f9"}" stroke="{c}"/>'
            body += text(231 + i * 70, y + 70, f"V{i + 1}", 14, c, "bold")
            body += text(231 + i * 70, y + 104, toks[i], 13, GRAY)
        qx = 200 + n * 70 + 40
        body += cbox(qx, y + 24, 70, 40, TEAL) + text(qx + 35, y + 50, f"Q{n}", 15, TEAL, "bold")
        body += path(f"M{qx - 2} {y + 44} H{200 + n * 70 + 4}", TEAL, 2)
        body += text(qx + 90, y + 40, "新 Q 与所有 K 打分，", 14, TEAL, anchor="start")
        body += text(qx + 90, y + 62, "再对所有 V 加权求和", 14, TEAL, anchor="start")
    body += f'<rect x="200" y="452" width="22" height="16" fill="{SOFT[ORANGE]}" stroke="{ORANGE}"/>' + text(230, 466, "本步新算的", 14, GRAY, anchor="start")
    body += '<rect x="340" y="452" width="22" height="16" fill="#f1f5f9" stroke="#64748b"/>' + text(370, 466, "从缓存直接读", 14, GRAY, anchor="start")
    body += text(480, 500, "缓存的是 K、V 张量，注意力权重每一步都要用新的 Q 重新算；缓存大小随上下文长度线性增长。", 15, GRAY)
    svg("kv-cache.svg", "KV cache 随生成步数增长",
        "prefill 时一次算出前两个 token 的 K、V；之后每个 decode 步只为新 token 计算一组 K、V 并接到缓存后面，新 token 的 Q 与全部 K 打分、对全部 V 加权求和。", 520, body)


# ---------- 第 14 章：优化器 ----------

def optimizer_paths():
    d = load("tinyllm-optimizer-paths.json")
    a, b = d["curvature"]
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    xs, ys = np.meshgrid(np.linspace(-5, 1.5, 300), np.linspace(-2, 2, 300))
    ax.contour(xs, ys, 0.5 * (a * xs ** 2 + b * ys ** 2), levels=[0.5, 2, 5, 10, 20, 35], colors="#cbd5e1", linewidths=1)
    palette = [RED, ORANGE, PURPLE, TEAL]
    for (name, trace), color in zip(d["paths"].items(), palette):
        t = np.array(trace)
        ax.plot(t[:, 0], t[:, 1], marker="o", ms=3, lw=1.6, color=color, label=name)
    ax.scatter([d["paths"][next(iter(d["paths"]))][0][0]], [d["paths"][next(iter(d["paths"]))][0][1]], color=INK, zorder=5, s=40)
    ax.scatter([0], [0], marker="*", color=INK, s=140, zorder=5)
    ax.text(-4.5, 1.78, "起点", fontsize=12)
    ax.text(0.08, 0.12, "最低点", fontsize=12)
    ax.set_xlabel("参数 a（坡度平缓的方向）")
    ax.set_ylabel("参数 b（坡度陡 25 倍）")
    ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=10, framealpha=0.95)
    save_plot(fig, "optimizer-paths.svg", "狭长山谷中的四种优化器",
              "在 f = 0.5(a² + 25b²) 上从同一点出发走 40 步：SGD 在陡峭的 b 方向来回振荡、在平缓的 a 方向前进缓慢；Momentum 积累了 a 方向的速度；RMSProp 和 Adam 按各方向的梯度尺度调整步长，更直接地走向最低点。")


def optimizer_curves():
    d = load("tinyllm-optimizer-curves.json")
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    for (name, hist), color in zip(d.items(), [RED, ORANGE, BLUE, TEAL]):
        ax.semilogy(hist, color=color, lw=2.2, ls="--" if name == "AdamW" else "-", label=f"{name}：{hist[0]:.3f} → {hist[-1]:.4f}")
    ax.set_xlabel("训练步数")
    ax.set_ylabel("均方误差（对数刻度）")
    ax.legend(loc="upper right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "optimizer-curves.svg", "四种优化器拟合正弦的损失曲线",
              "同一个两层网络、同一份初始参数拟合正弦 300 步：SGD 下降最慢，Momentum 最终损失最低，Adam 和 AdamW 前期下降最快，两者曲线几乎重合。")


def adamw_vs_l2():
    body = text(480, 40, "L2 正则与 AdamW：衰减项要不要经过自适应缩放", 23, weight="bold")
    for k, (name, color, steps, note) in enumerate([
        ("Adam + L2（把 λw 加进梯度）", ORANGE,
         ["g = ∇L + λ·w", "m, v ← 用 g 更新", "w ← w − η · m / (√v + ε)"],
         "衰减也被除以 √v：梯度大的参数，衰减反而变弱"),
        ("AdamW（衰减单独做）", TEAL,
         ["g = ∇L", "m, v ← 用 g 更新", "w ← w − η · m / (√v + ε) − η·λ·w"],
         "每个参数按同一比例 ηλ 收缩，与梯度大小无关")]):
        x = 40 + k * 460
        body += text(x + 210, 90, name, 18, color, "bold")
        for i, s in enumerate(steps):
            y = 110 + i * 72
            body += cbox(x, y, 420, 50, color)
            body += text(x + 210, y + 32, s, 17, INK, "bold")
            if i:
                body += arrow(x + 210, y - 20, x + 210, y - 4, color)
        body += text(x + 210, 350, note, 15, color)
    body += text(480, 395, "m、v 为偏差校正后的一阶、二阶矩。对普通 SGD 两种写法等价；对 Adam 这类自适应优化器，它们是两种不同的算法。", 15, GRAY)
    svg("adamw-vs-l2.svg", "Adam 加 L2 与 AdamW 的区别",
        "Adam 加 L2 把 λw 加进梯度，衰减项随后被二阶矩缩放；AdamW 用原始梯度更新一、二阶矩，参数更新后再单独减去 ηλw，让所有参数按同一比例衰减。", 425, body)


# ---------- 第 17 章：数值精度 ----------

def float_formats():
    body = text(480, 40, "16 位的两种分法：FP16 多给尾数，BF16 多给指数", 23, weight="bold")
    fmts = [("FP32", 1, 8, 23, "eps ≈ 1.19e-7", "max ≈ 3.4e38"), ("FP16", 1, 5, 10, "eps ≈ 9.8e-4", "max = 65504"), ("BF16", 1, 8, 7, "eps ≈ 7.8e-3", "max ≈ 3.4e38")]
    unit = 17
    for k, (name, s, e, m, eps, mx) in enumerate(fmts):
        y = 85 + k * 105
        body += text(40, y + 30, name, 20, INK, "bold", anchor="start")
        x = 130
        for count, color, label in [(s, GRAY, "符号"), (e, BLUE, f"指数 {e} 位"), (m, ORANGE, f"尾数 {m} 位")]:
            w = count * unit
            body += f'<rect x="{x}" y="{y + 6}" width="{w}" height="38" rx="4" fill="{SOFT.get(color, "#f1f5f9") if color != GRAY else "#e2e8f0"}" stroke="{color}" stroke-width="1.5"/>'
            for i in range(1, count):
                body += f'<line x1="{x + i * unit}" y1="{y + 6}" x2="{x + i * unit}" y2="{y + 44}" stroke="{color}" stroke-opacity="0.25"/>'
            if count > 2:
                body += text(x + w / 2, y + 66, label, 13.5, color)
            x += w
        body += mtext(x + 20, y + 22, eps, 14, ORANGE, anchor="start")
        body += mtext(x + 20, y + 44, mx, 14, BLUE, anchor="start")
    body += text(480, 420, "指数位决定能表示多大、多小（范围），尾数位决定相邻两个数挨得多近（精度）。", 16, GRAY)
    body += text(480, 448, "BF16 与 FP32 的指数位相同，所以范围几乎一样；代价是尾数只有 7 位，刻度比 FP16 粗 8 倍。", 16, GRAY)
    svg("float-formats.svg", "FP32、FP16、BF16 的位布局",
        "FP32 有 1 位符号、8 位指数、23 位尾数；FP16 有 1、5、10 位，最大 65504，eps 约 9.8e-4；BF16 有 1、8、7 位，范围与 FP32 接近，eps 约 7.8e-3。", 470, body)


def float_spacing():
    d = load("tinyllm-float-spacing.json")
    v = np.array(d["values"])
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    for name, color in [("FP32", GRAY), ("FP16", BLUE), ("BF16", ORANGE)]:
        sp = [np.nan if s is None else s for s in d[name]["spacing"]]
        ax.loglog(v, sp, marker="o", ms=3.5, lw=2.2, color=color, label=f"{name}（eps = {d[name]['eps']:.2g}）")
    ax.axvline(65504, color=RED, ls="--", lw=1.4)
    ax.text(65504 * 0.55, 3e-7, "FP16 最大值 65504\n再大就溢出为 inf", color=RED, fontsize=11, ha="right")
    ax.annotate("1000 附近 BF16 的间距是 4：\n1000 和 1001 存成同一个数", xy=(1024, 8), xytext=(8, 40),
                arrowprops={"arrowstyle": "->", "color": ORANGE}, color=ORANGE, fontsize=11)
    ax.set_xlabel("数值大小")
    ax.set_ylabel("相邻可表示数的间距")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "float-spacing.svg", "不同格式的刻度间距",
              "相邻可表示数的间距随数值大小成比例增长：同一数量级上 BF16 的间距是 FP16 的 8 倍，FP32 远小于两者；FP16 在 65504 以上没有有限值。")


def autocast_flow():
    body = text(480, 40, "autocast：按算子选精度，参数仍以 FP32 保存", 23, weight="bold")
    body += cbox(40, 90, 220, 70, GRAY) + text(150, 122, "模型参数", 17, INK, "bold") + mtext(150, 146, "FP32", 15, GRAY)
    body += cbox(330, 75, 300, 270, BLUE, dash=True)
    body += text(480, 100, "with torch.autocast(...)", 15, BLUE, "bold")
    body += cbox(355, 115, 250, 58, ORANGE) + text(480, 140, "matmul / linear / conv", 15, INK, "bold") + text(480, 162, "转成 FP16 / BF16 计算", 13.5, ORANGE)
    body += cbox(355, 190, 250, 58, TEAL) + text(480, 215, "softmax / layer_norm / 损失", 15, INK, "bold") + text(480, 237, "CUDA 上按 FP32 计算", 13.5, TEAL)
    body += cbox(355, 265, 250, 58, GRAY) + text(480, 290, "其他算子", 15, INK, "bold") + text(480, 312, "跟随输入 dtype", 13.5, GRAY)
    body += path("M262 125 H351", GRAY)
    body += cbox(700, 160, 220, 70, PURPLE) + text(810, 192, "loss.backward()", 16, INK, "bold") + text(810, 216, "梯度累加回 FP32 参数", 13.5, PURPLE)
    body += path("M634 220 H696", PURPLE)
    body += cbox(700, 265, 220, 70, RED) + text(810, 297, "只有 FP16 才需要", 15, INK, "bold") + text(810, 320, "GradScaler 防梯度下溢", 13.5, RED)
    body += text(480, 395, "图中名单以 CUDA 为例；CPU、MPS 的名单不同（例如 CPU 上 layer_norm 跟随输入 dtype），随版本也会变化，打印实际 dtype 最可靠。", 15, GRAY)
    svg("autocast-flow.svg", "autocast 混合精度的数据流",
        "参数保存为 FP32；在 autocast 区域内，矩阵乘法等算子转为 FP16 或 BF16 计算，在 CUDA 上 softmax、layer_norm 和损失等按 FP32 计算，其余跟随输入；反向传播的梯度累加回 FP32 参数，使用 FP16 时还需要 GradScaler。", 420, body)


# ---------- 第 1 章：模型知道的 vs 上下文给的 ----------

def knowledge_sources():
    body = text(480, 40, "模型的“知识”在训练时就定格了；Agent 让它每次回答前先去查", 22, weight="bold")
    # 左：训练
    body += cbox(30, 70, 360, 380, GRAY, dash=True)
    body += text(210, 98, "训练（只做一次，代价很大）", 17, INK, "bold")
    body += cbox(70, 120, 280, 60, ORANGE) + text(210, 148, "海量语料", 17, INK, "bold") + text(210, 170, "截止到某一天", 13.5, ORANGE)
    body += arrow(210, 180, 210, 210, ORANGE)
    body += cbox(70, 214, 280, 60, BLUE) + text(210, 242, "反复练习：预测下一个 token", 16, INK, "bold") + text(210, 264, "第 1 章那个训练循环", 13.5, BLUE)
    body += arrow(210, 274, 210, 304, BLUE)
    body += cbox(70, 308, 280, 70, PURPLE) + text(210, 338, "参数（权重）", 17, INK, "bold") + text(210, 362, "语料里的规律被压缩进来，随后冻结", 13.5, PURPLE)
    body += text(210, 425, "之后发生的事、你的私人资料，它都没见过", 14, GRAY)
    # 右：使用
    body += cbox(430, 70, 500, 380, TEAL, dash=True)
    body += text(680, 98, "使用（每次提问都重新来一遍）", 17, INK, "bold")
    body += cbox(455, 120, 140, 60, BLUE) + text(525, 155, "你的问题", 16, INK, "bold")
    body += cbox(615, 120, 290, 60, TEAL) + text(760, 146, "Agent 去查", 16, INK, "bold") + text(760, 168, "搜索 · 读文件 · 调工具 · 翻记忆", 13.5, TEAL)
    body += path("M525 180 V214", BLUE) + path("M760 180 C760 200 720 200 700 212", TEAL)
    body += cbox(455, 216, 450, 60, ORANGE) + text(680, 244, "上下文：问题 + 查到的资料", 16, INK, "bold") + text(680, 266, "模型这一次能“看到”的全部文字", 13.5, ORANGE)
    body += arrow(680, 276, 680, 304, ORANGE)
    body += cbox(455, 308, 450, 70, PURPLE) + text(680, 338, "同一个模型，参数不变", 16, INK, "bold") + text(680, 362, "照旧一个 token 一个 token 往下接", 13.5, PURPLE)
    body += path("M350 343 H451", PURPLE)
    body += text(400, 335, "拿来用", 12.5, PURPLE)
    body += text(680, 425, "资料越准、越相关，接出来的回答越可靠", 14, GRAY)
    body += text(480, 485, "让模型更“懂”有两条路：改参数（重新训练、微调），或改上下文（检索、工具、记忆）。后者立刻生效，代价也小得多。", 15, GRAY)
    svg("knowledge-sources.svg", "模型参数里的知识与上下文中的资料",
        "左：训练时模型在截止某天的语料上反复练习预测下一个 token，规律被压缩进参数后冻结。右：使用时 Agent 先根据问题去搜索、读文件、调用工具或翻记忆，把资料和问题一起放进上下文，同一个参数不变的模型再逐个 token 生成回答。", 510, body)


def agent_loop():
    body = text(480, 40, "Agent 循环：模型写下“下一步做什么”，Agent 去做，再把结果写回上下文", 21, weight="bold")
    body += cbox(330, 80, 300, 100, ORANGE)
    body += text(480, 110, "上下文", 18, INK, "bold")
    body += text(480, 136, "问题 + 之前每一轮的", 14, ORANGE)
    body += text(480, 158, "动作和结果，越积越多", 14, ORANGE)
    body += cbox(660, 230, 270, 90, PURPLE)
    body += text(795, 262, "模型：预测下一个 token", 16, INK, "bold")
    body += text(795, 286, "写出一段文字，例如", 13.5, PURPLE)
    body += mtext(795, 306, "read_file(\"test.log\")", 13, PURPLE)
    body += cbox(330, 370, 300, 90, TEAL)
    body += text(480, 402, "Agent：真的去执行", 16, INK, "bold")
    body += text(480, 426, "读文件 · 搜索 · 运行代码 · 查数据库", 13.5, TEAL)
    body += cbox(30, 230, 270, 90, BLUE)
    body += text(165, 262, "执行结果", 16, INK, "bold")
    body += text(165, 286, "文件内容、搜索结果、报错信息", 13.5, BLUE)
    body += text(165, 306, "原样追加进上下文", 13.5, BLUE)
    body += path("M632 140 C760 140 795 170 795 226", ORANGE)
    body += path("M795 322 C795 400 700 415 634 415", PURPLE)
    body += path("M328 415 C200 415 165 380 165 324", TEAL)
    body += path("M165 228 C165 170 220 140 326 140", BLUE)
    body += text(728, 128, "①", 18, ORANGE, "bold") + text(818, 405, "②", 18, PURPLE, "bold")
    body += text(232, 438, "③", 18, TEAL, "bold") + text(142, 178, "④", 18, BLUE, "bold")
    body += cbox(390, 205, 180, 130, GRAY, dash=True)
    body += text(480, 240, "模型判断", 15, INK, "bold")
    body += text(480, 262, "资料够了吗？", 14, GRAY)
    body += text(480, 292, "够了 → 写最终回答", 14, TEAL)
    body += text(480, 314, "不够 → 再转一圈", 14, ORANGE)
    body += text(480, 495, "模型自始至终只会预测下一个 token；“会查资料、会一步步做事”的能力，来自 Agent 把这个循环跑起来。", 15, GRAY)
    svg("agent-loop.svg", "Agent 循环",
        "上下文交给模型，模型预测出一段描述下一步动作的文字，例如读取某个文件；Agent 真的执行这个动作，把文件内容、搜索结果或报错信息追加进上下文；模型读到新资料后判断是否足够，够了就写最终回答，不够就再转一圈。", 520, body)


def transformer_to_gpt():
    body = text(480, 40, "从翻译模型到 GPT：去掉编码器，只留下“预测下一个 token”", 22, weight="bold")
    # 左：2017 Transformer
    body += cbox(25, 65, 450, 395, BLUE, dash=True)
    body += text(250, 92, "2017 · Transformer：为机器翻译设计", 17, BLUE, "bold")
    src = ["the", "book", "on", "the", "table"]
    tgt = ["桌子", "上", "的", "书"]
    body += text(250, 122, "编码器：一次读完整句原文", 14, GRAY)
    for i, w in enumerate(src):
        body += cbox(48 + i * 84, 132, 74, 40, BLUE) + mtext(85 + i * 84, 158, w, 15, INK, "bold")
    links = [(0, 4), (1, 2), (3, 1)]  # (译文位置 j, 原文位置 i)：桌子←table，上←on，书←book
    for j, i in links:
        body += f'<path d="M{85 + i * 84} 174 C{85 + i * 84} 230 {95 + j * 100} 230 {95 + j * 100} 282" stroke="{ORANGE}" stroke-width="2" fill="none" stroke-opacity="0.8"/>'
    for j, w in enumerate(tgt):
        body += cbox(58 + j * 100, 284, 74, 40, TEAL) + text(95 + j * 100, 310, w, 16, INK, "bold")
    body += text(250, 348, "解码器：一个词一个词地生成译文", 14, GRAY)
    body += text(250, 370, "橙线 = 交叉注意力：生成每个译词时回头看原文任意位置", 13.5, ORANGE)
    body += text(250, 398, "位置编码告诉模型每个词排在第几；注意力让它", 14, INK)
    body += text(250, 418, "不必按原文顺序对齐，“书”可以去看 book", 14, INK)
    body += text(250, 440, "训练数据：成对的“原文 → 译文”", 14, BLUE, "bold")
    # 右：GPT
    body += cbox(500, 65, 435, 395, TEAL, dash=True)
    body += text(717, 92, "2018 起 · GPT：只保留解码器", 17, TEAL, "bold")
    words = ["床", "前", "明", "月", "光"]
    for i, w in enumerate(words[:4]):
        body += cbox(540 + i * 82, 135, 70, 40, GRAY) + text(575 + i * 82, 161, w, 17, INK, "bold")
    body += cbox(540, 195, 312, 70, TEAL)
    body += text(696, 225, "N 层解码器 Block", 16, INK, "bold")
    body += text(696, 249, "只能看自己和前面的字", 13.5, TEAL)
    for i in range(4):
        body += arrow(575 + i * 82, 177, 575 + i * 82, 192, GRAY, 2)
    body += arrow(696, 267, 696, 292, TEAL)
    body += cbox(626, 296, 140, 44, ORANGE) + text(696, 324, "下一个：光", 16, INK, "bold")
    body += text(717, 370, "没有原文、没有译文，只有一段段连续文本；", 14, INK)
    body += text(717, 393, "每个位置都在猜下一个 token", 14, INK)
    body += text(717, 440, "训练数据：任何文字都能用，越多越好", 14, TEAL, "bold")
    body += text(480, 492, "这门课的 TinyLLM 就是右边这种结构：Decoder-only，目标只有一个，预测下一个 token。", 15, GRAY)
    svg("transformer-to-gpt.svg", "从 Transformer 翻译模型到 GPT",
        "左：2017 年的 Transformer 用编码器读完整句英文 the book on the table，解码器逐词生成“桌子上的书”，每生成一个词都通过交叉注意力回头看原文的任意位置，因此词序不同也能对上。右：GPT 去掉编码器，只保留只能看前文的解码器，在连续文本上预测下一个 token。", 515, body)


def gpt_scale():
    rows = [("2018", "GPT-1", "1.17 亿", "约 7000 本书"), ("2019", "GPT-2", "15 亿", "约 40 GB 网页文本"),
            ("2020", "GPT-3", "1750 亿", "约 3000 亿 token"), ("2022", "ChatGPT", "在 GPT-3.5 上", "再做指令微调和人类反馈训练")]
    body = text(480, 40, "同一个目标，不断放大：GPT 系列的规模", 22, weight="bold")
    body += text(150, 82, "年份 · 模型", 14, GRAY, "bold") + text(470, 82, "参数量", 14, GRAY, "bold") + text(830, 82, "训练语料", 14, GRAY, "bold")
    widths = [51, 151, 336, 0]  # 按 log10(参数量) 画，每十倍约 90 像素
    for i, (y, name, params, data) in enumerate(rows):
        yy = 100 + i * 68
        c = [BLUE, BLUE, TEAL, ORANGE][i]
        body += cbox(40, yy, 220, 52, c) + text(150, yy + 33, f"{y} · {name}", 17, INK, "bold")
        if widths[i]:
            body += f'<rect x="300" y="{yy + 12}" width="{widths[i]}" height="28" rx="6" fill="{SOFT[c]}" stroke="{c}"/>'
        body += text(300 + max(widths[i], 0) + 10 if widths[i] else 310, yy + 33, params, 16, c, "bold", anchor="start")
        body += text(830, yy + 33, data, 15, INK)
    body += text(480, 395, "参数条按对数刻度画：GPT-3 的条只比 GPT-1 长几倍，参数量却多了约 1500 倍。目标始终是预测下一个 token。", 14.5, GRAY)
    svg("gpt-scale.svg", "GPT 系列的规模增长",
        "GPT-1 于 2018 年发布，1.17 亿参数，训练语料约 7000 本书；GPT-2 于 2019 年，15 亿参数，约 40GB 网页文本；GPT-3 于 2020 年，1750 亿参数，约 3000 亿 token；2022 年的 ChatGPT 在 GPT-3.5 基础上做了指令微调和人类反馈训练。", 420, body)


def modern_block():
    body = text(480, 40, "2018 年和 2026 年的 Block：零件换了，流水线没变", 22, weight="bold")
    # 左：GPT-1
    body += cbox(25, 65, 300, 400, BLUE, dash=True)
    body += text(175, 92, "GPT-1（2018）", 17, BLUE, "bold")
    body += text(175, 116, "12 个相同的 Block", 14, GRAY)
    for k in range(2):
        y = 135 + k * 140
        body += cbox(55, y, 240, 52, BLUE) + text(175, y + 32, "完整注意力", 16, INK, "bold")
        body += arrow(175, y + 52, 175, y + 70, BLUE)
        body += cbox(55, y + 72, 240, 52, BLUE) + text(175, y + 104, "稠密前馈层", 16, INK, "bold")
    body += text(175, 430, "每层看全部前文，参数全部参与计算", 13.5, GRAY)
    # 右：2026
    body += cbox(350, 65, 585, 400, TEAL, dash=True)
    body += text(642, 92, "2026 年的典型做法（Kimi K3、Qwen3.5 的思路）", 17, TEAL, "bold")
    body += text(642, 116, "每 4 层为一组，反复堆叠", 14, GRAY)
    labels = ["线性注意力", "线性注意力", "线性注意力", "完整注意力"]
    for i, lab in enumerate(labels):
        x = 372 + i * 140
        c = ORANGE if i < 3 else BLUE
        body += cbox(x, 135, 125, 52, c) + text(x + 62, 160, lab, 15, INK, "bold") + text(x + 62, 179, "前文压成固定状态" if i < 3 else "逐个回看全部前文", 11.5, c)
        body += arrow(x + 62, 187, x + 62, 205, GRAY, 2)
        body += cbox(x, 207, 125, 52, PURPLE) + text(x + 62, 238, "MoE 前馈层", 15, INK, "bold")
        if i < 3:
            body += arrow(x + 127, 233, x + 138, 233, GRAY, 2)
    body += cbox(372, 290, 545, 140, PURPLE)
    body += text(644, 314, "MoE：很多个小前馈层（专家），每个 token 只用其中几个", 15, PURPLE, "bold")
    for j in range(14):
        on = j in (2, 7, 11)
        body += f'<rect x="{392 + j * 36}" y="330" width="30" height="34" rx="5" fill="{SOFT[PURPLE] if on else "#ffffff"}" stroke="{PURPLE if on else "#cbd5e1"}" stroke-width="{2.2 if on else 1}"/>'
    body += cbox(392, 376, 135, 38, TEAL) + text(459, 400, "共享专家", 14, INK, "bold")
    body += text(545, 400, "路由器给每个 token 挑少数专家（紫框）；共享专家人人都用", 13, GRAY, anchor="start")
    body += text(480, 492, "目标仍是预测下一个 token。变化都在“省”：注意力少算、前馈层少激活，才撑得起万亿参数和百万上下文。", 15, GRAY)
    svg("modern-block.svg", "GPT-1 与 2026 年模型的 Block 结构对比",
        "左：GPT-1 由 12 个相同的 Block 组成，每个 Block 是完整注意力加稠密前馈层。右：2026 年的典型做法每 4 层为一组，前 3 层用便宜的线性注意力、第 4 层用完整注意力，每层后接 MoE 前馈层；MoE 由很多小专家组成，路由器为每个 token 只挑少数几个，另有所有 token 共用的共享专家。", 515, body)


def autograd_cost():
    d = load("tinyllm-autograd-cost.json")
    rows = d["rows"]
    n = np.array([r["params"] for r in rows], dtype=float)
    bwd = np.array([r["forward_backward_s"] / r["forward_s"] for r in rows])
    fd_rows = [r for r in rows if "finite_diff_s" in r]
    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
    grid = np.logspace(1, 6.5, 50)
    ax.loglog(grid, grid + 1, color=ORANGE, lw=2, ls="--", label="逐个参数做差分：需要 N + 1 次前向")
    ax.loglog([r["params"] for r in fd_rows], [r["finite_diff_s"] / r["forward_s"] for r in fd_rows],
              "o", color=ORANGE, ms=7, label="差分实测（小模型真的跑了一遍）")
    ax.loglog(n, bwd, "o-", color=TEAL, lw=2.4, ms=6, label="一次 forward + backward 实测")
    tiny = 388128
    ax.scatter([tiny], [tiny + 1], color=RED, zorder=5, s=50)
    ax.annotate("第 1 章的 TinyLLM：39 万个参数\n差分要做约 39 万次前向", xy=(tiny, tiny), xytext=(2.5e3, 4e5),
                arrowprops={"arrowstyle": "->", "color": RED}, color=RED, fontsize=11)
    ax.annotate(f"backward 始终只相当于 {bwd.min():.0f}～{bwd.max():.0f} 次前向\n（越大的模型越接近 3 次）", xy=(n[-1], bwd[-1]),
                xytext=(2e4, 40), arrowprops={"arrowstyle": "->", "color": TEAL}, color=TEAL, fontsize=11)
    ax.set_xlabel("参数个数 N")
    ax.set_ylabel("耗时相当于几次前向计算")
    ax.set_ylim(1, 1e7)
    ax.legend(loc="upper left", fontsize=10.5, framealpha=0.95)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "autograd-cost.svg", "求全部梯度的代价：数值差分与反向传播",
              f"参数从 40 个增加到约 210 万个：逐个参数做差分需要 N+1 次前向，随参数量线性增长，第 1 章 39 万参数的模型要约 39 万次；一次前向加反向传播实测始终只相当于 {bwd.min():.0f} 到 {bwd.max():.0f} 次前向，与参数量无关。")


def vjp_matmul():
    body = text(480, 40, "反向传播不构造雅可比矩阵，只做和前向同样大小的矩阵乘法", 21, weight="bold")
    body += cbox(30, 75, 430, 175, BLUE)
    body += text(245, 103, "前向：y = x @ W", 18, BLUE, "bold")
    body += mtext(245, 140, "x [T, d_in]  @  W [d_in, d_out]", 15, INK)
    body += mtext(245, 170, "→  y [T, d_out]  →  ...  →  L（一个数）", 15, INK)
    body += text(245, 215, "计算量：T × d_in × d_out 次乘加", 15, GRAY)
    body += cbox(500, 75, 430, 175, TEAL)
    body += text(715, 103, "反向：已知 g = dL/dy  [T, d_out]", 17, TEAL, "bold")
    body += mtext(715, 140, "dL/dW = x^T @ g   [d_in, d_out]", 15, INK, "bold")
    body += mtext(715, 170, "dL/dx = g @ W^T   [T, d_in]", 15, INK, "bold")
    body += text(715, 215, "两次矩阵乘法，计算量和前向同一量级", 15, GRAY)
    body += path("M462 160 H496", GRAY)
    body += cbox(30, 280, 900, 130, RED)
    body += text(480, 310, "如果先把完整的雅可比矩阵 dy/dW 算出来，再乘 g，会怎样？", 17, RED, "bold")
    body += mtext(480, 345, "dy/dW: [T*d_out, d_in*d_out]", 16, INK)
    body += text(480, 380, "取 T = 1、d_in = d_out = 4096（7B 级模型里一个投影矩阵的大小）：约 687 亿个数，FP32 下约 275 GB", 15.5, INK)
    body += text(480, 450, "PyTorch 的每个算子都直接实现“g 乘雅可比”这一步（向量-雅可比积，VJP），所以从来不需要把雅可比矩阵存下来。", 15, GRAY)
    svg("vjp-matmul.svg", "矩阵乘法的反向传播",
        "前向 y = x @ W；反向已知 g = ∂L/∂y，直接算 dL/dW = xᵀg 和 dL/dx = gWᵀ，两次矩阵乘法的计算量与前向同一量级。若先构造完整雅可比矩阵 dy/dW，在 d_in = d_out = 4096 时就有约 687 亿个数，FP32 下约 275 GB。", 475, body)


# ---------- 第 5 章：自注意力 ----------

def _grid(x0, y0, mat, cell, color, fmt="{:.2f}", masked=None, label=None, row_labels=None, col_labels=None):
    out = ""
    if label:
        out += text(x0 + cell * mat.shape[1] / 2, y0 - 34, label, 15, color, "bold")
    if col_labels:
        for j, c in enumerate(col_labels):
            out += text(x0 + j * cell + cell / 2, y0 - 8, c, 12.5, GRAY)
    for i in range(mat.shape[0]):
        if row_labels:
            out += text(x0 - 8, y0 + i * cell + cell / 2 + 5, row_labels[i], 12.5, GRAY, anchor="end")
        for j in range(mat.shape[1]):
            off = masked is not None and masked[i, j]
            fill = "#f1f5f9" if off else SOFT.get(color, "#ffffff")
            out += f'<rect x="{x0 + j * cell}" y="{y0 + i * cell}" width="{cell - 3}" height="{cell - 3}" rx="5" fill="{fill}" stroke="{GRAY if off else color}" stroke-width="1.3"/>'
            val = "-∞" if (off and fmt == "{:.2f}" and not np.isfinite(mat[i, j])) else ("0" if off else fmt.format(mat[i, j]))
            out += text(x0 + j * cell + (cell - 3) / 2, y0 + i * cell + cell / 2 + 4, val, 14, GRAY if off else INK, "bold" if not off else "normal")
    return out


def attention_steps():
    Q = np.array([[1, 0], [0, 1], [1, 1]], float)
    K = Q.copy()
    V = np.array([[1, 0], [0, 2], [3, 3]], float)
    scores = Q @ K.T / np.sqrt(2)
    fut = np.triu(np.ones((3, 3), bool), 1)
    masked = np.where(fut, -np.inf, scores)
    w = np.exp(masked - masked.max(1, keepdims=True))
    w = w / w.sum(1, keepdims=True)
    out = w @ V
    names = ["我", "在", "学习"]
    body = text(480, 36, "一次因果注意力：打分 → 遮住未来 → softmax → 按权重取 V", 21, weight="bold")
    cell = 52
    body += _grid(70, 110, scores, cell, BLUE, label="① 分数 Q·K^T / √2", row_labels=names, col_labels=names)
    body += arrow(232, 185, 262, 185, GRAY)
    body += _grid(300, 110, masked, cell, ORANGE, masked=fut, label="② 遮住未来", row_labels=names, col_labels=names)
    body += arrow(462, 185, 492, 185, GRAY)
    body += _grid(530, 110, w, cell, TEAL, masked=fut, label="③ softmax 权重", row_labels=names, col_labels=names)
    body += arrow(692, 185, 722, 185, GRAY)
    body += _grid(770, 110, out, cell, PURPLE, label="④ 输出 = 权重 @ V", row_labels=names, col_labels=["d0", "d1"])
    body += text(480, 300, "每一行是一个位置：它给自己和前面每个位置打分，归一化成权重，再按权重把各位置的 V 加起来。", 14.5, GRAY)
    body += text(480, 326, "“学习”这一行：分数 0.71、0.71、1.41 → 权重 0.25、0.25、0.50 → 输出 0.25·v0 + 0.25·v1 + 0.50·v2。", 14.5, GRAY)
    body += text(480, 352, "“我”这一行只看得见自己，权重是 1，输出就是它自己的 V。", 14.5, GRAY)
    svg("attention-steps.svg", "一次因果注意力的四个步骤",
        "三个位置“我、在、学习”：先算 Q 与 K 的点积除以根号 2 得到分数；把对角线以上的未来位置改成负无穷；按行 softmax 得到权重，“学习”这一行是 0.25、0.25、0.50；最后用权重对 V 加权求和得到输出，“我”只看见自己，输出等于自己的 V。", 375, body)


def multihead_shapes():
    body = text(480, 36, "多头注意力的形状变化：拆开、各算各的、再拼回去", 21, weight="bold")
    steps = [("x", "[B, T, D]", GRAY), ("qkv(x) 拆成 Q、K、V", "各 [B, T, D]", BLUE),
             ("view：最后一维切成 H 份", "[B, T, H, D/H]", BLUE), ("transpose(1, 2)：头提到前面", "[B, H, T, D/H]", ORANGE),
             ("每个头各做一次因果注意力", "[B, H, T, D/H]", TEAL), ("transpose 回来再 reshape", "[B, T, D]", PURPLE),
             ("proj：各头结果混合一次", "[B, T, D]", PURPLE)]
    for i, (what, shape, c) in enumerate(steps):
        y = 64 + i * 56
        body += cbox(140, y, 420, 44, c) + text(350, y + 28, what, 15, INK, "bold")
        body += mtext(700, y + 28, shape, 17, c, "bold")
        if i:
            body += arrow(350, y - 12, 350, y - 2, GRAY, 2)
    body += text(480, 470, "D = 8、H = 2 时：每个头只看 4 维，两个头可以各自关注不同的关系，计算量和一个 8 维的头相同。", 14.5, GRAY)
    svg("multihead-shapes.svg", "多头注意力的形状变化",
        "输入 x 的形状是 B、T、D；线性层算出 Q、K、V；把最后一维切成 H 份并转置成 B、H、T、D/H；每个头各做一次因果注意力；再转置、reshape 拼回 B、T、D，最后经过输出投影。", 495, body)


def attention_ablation():
    d = load("tinyllm-attention-ablation.json")
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    for (name, r), color in zip(d.items(), [TEAL, RED]):
        loss = np.array(r["loss"])
        smooth = np.convolve(loss, np.ones(15) / 15, mode="valid")
        ax.plot(np.arange(len(smooth)) + 7, smooth, color=color, lw=2.4, label=f"{name}（最后 50 步平均 {loss[-50:].mean():.2f}）")
    ax.set_xlabel("训练步数")
    ax.set_ylabel("训练损失（15 步滑动平均）")
    ax.legend(loc="upper right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "attention-ablation.svg", "有无注意力的训练损失",
              "同一份唐诗语料、同一个模型、同样 600 步：有注意力时训练损失降到约 0.11；把注意力去掉后，每个位置只能看到自己，损失停在约 1.6。")


# ---------- matplotlib 公共设置 ----------

def configure_plots():
    # Windows 用微软雅黑；其他平台依次尝试 PingFang 与 Noto Sans CJK。
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/System/Library/Fonts/PingFang.ttc"),
                  *Path("/usr/share/fonts").rglob("NotoSansCJK-Regular.ttc")]
    family = "sans-serif"
    for preferred in candidates:
        if preferred.exists():
            font_manager.fontManager.addfont(str(preferred))
            family = font_manager.FontProperties(fname=str(preferred)).get_name()
            break
    plt.rcParams.update({"font.family": family, "font.size": 14, "svg.fonttype": "path", "svg.hashsalt": "tinyllm",
                         "axes.unicode_minus": False, "axes.labelcolor": INK,
                         "text.color": INK, "xtick.color": INK, "ytick.color": INK,
                         "figure.facecolor": "#f8fafc", "axes.facecolor": "#ffffff"})


def save_plot(fig, name, title, description):
    path_ = OUT / name
    fig.savefig(path_, format="svg", metadata={"Date": None, "Creator": "TinyLLM tutorial figure generator"})
    plt.close(fig)
    raw = path_.read_text(encoding="utf-8")
    pos = raw.index(">", raw.index("<svg"))
    raw = raw[:pos] + ' role="img" aria-labelledby="title desc"' + raw[pos:]
    pos = raw.index(">", raw.index("<svg")) + 1
    raw = raw[:pos] + f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>' + raw[pos:]
    path_.write_text(raw, encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    configure_plots()
    tensor_shape()
    broadcast()
    compute_graph()
    gradient_step()
    norm_motivation()
    norm_three_ways()
    norm_geometry()
    pre_post_norm()
    first_run_loss()
    # 第 9、7、3、4、14、17 章；数据图需要先运行 scripts/tinyllm-figure-data.py
    for fn in (init_fan_in, residual_depth, residual_path, activation_fit, swiglu_vs_ffn, utf8_lengths, bpe_merges,
               label_shift, embedding_lookup, tied_output, kv_cache, optimizer_paths, optimizer_curves, adamw_vs_l2,
               float_formats, float_spacing, autocast_flow, knowledge_sources, agent_loop, transformer_to_gpt, gpt_scale, modern_block, autograd_cost, vjp_matmul, attention_steps, multihead_shapes, attention_ablation):
        fn()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
