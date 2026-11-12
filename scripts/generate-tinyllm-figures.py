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


# ---------- 第 11 章：归一化 ----------

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

def quickstart_loss():
    src = DATA / "tinyllm-quickstart-log.json"
    if not src.exists():
        print("skip quickstart-loss.svg: run scripts/build-tinyllm-code.py quickstart to create", src)
        return
    log = json.loads(src.read_text(encoding="utf-8"))
    loss = np.array(log["loss"])
    smooth = np.convolve(loss, np.ones(15) / 15, mode="valid")
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.plot(loss, color="#cbd5e1", lw=0.8, label="训练损失（每一步）")
    ax.plot(np.arange(len(smooth)) + 7, smooth, color=BLUE, lw=2.4, label="训练损失（15 步滑动平均）")
    ax.plot(log["val_step"], log["val_loss"], color=RED, lw=2.2, marker="o", ms=4, label="验证损失（没训练过的 5 首诗）")
    ax.axhline(log["uniform"], color=ORANGE, ls="--", lw=1.6)
    ax.text(len(loss) * 0.52, log["uniform"] - 0.45, f"完全乱猜：ln(词表大小) ≈ {log['uniform']:.2f}", color=ORANGE, fontsize=12)
    best = int(np.argmin(log["val_loss"]))
    ax.annotate(f"验证损失最低 {log['val_loss'][best]:.2f}（第 {log['val_step'][best]} 步）\n过了这里，模型开始背训练集",
                xy=(log["val_step"][best], log["val_loss"][best]), xytext=(log["val_step"][best] + 190, log["val_loss"][best] - 1.3),
                color=RED, fontsize=12, arrowprops=dict(arrowstyle="->", color=RED, lw=1.4))
    ax.set_xlabel("训练步数")
    ax.set_ylabel("交叉熵损失")
    ax.set_ylim(0, max(max(log["val_loss"]), loss[0]) + 0.6)
    ax.legend(loc="center right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "quickstart-loss.svg", "快速体验：一千步训练里的训练损失与验证损失",
              f"训练损失从约 {loss[0]:.1f} 一路降到约 {smooth[-1]:.2f}；验证损失在第 {log['val_step'][best]} 步见底（{log['val_loss'][best]:.2f}），"
              f"随后升到 {log['val_loss'][-1]:.2f}，超过乱猜的 {log['uniform']:.2f}。两条曲线一分开，模型就从学诗变成了背诗。")


def quickstart_position_add():
    """快速体验步骤 4：每个位置的输入 = 字向量 + 位置向量（数字取自 quickstart.py 的真实输出，前 4 个数）。"""
    src = DATA / "tinyllm-quickstart-log.json"
    if not src.exists():
        print("skip quickstart_position_add: run scripts/build-tinyllm-code.py quickstart first")
        return
    demo = json.loads(src.read_text(encoding="utf-8"))["position_demo"]
    body = text(480, 36, "进模型的向量 = 字向量 + 位置向量（每格是前 4 个数）", 21, weight="bold")
    rows = [("字向量", "查字表：第几个字", BLUE, demo["tok"]), ("位置向量", "查位置表：第几位", TEAL, demo["pos"]),
            ("输入向量", "两者逐个数相加", INK, demo["sum"])]
    x0, w = 150, 150
    for i, ch in enumerate(demo["names"]):
        cx = x0 + i * (w + 12) + w / 2
        hot = i == 2
        body += text(cx, 78, f"“{ch}”· 第 {i} 位", 15, ORANGE if hot else INK, "bold")
    for r, (name, sub, color, vals) in enumerate(rows):
        y = 96 + r * 92
        body += text(20, y + 30, name, 15, color, "bold", "start")
        body += text(20, y + 52, sub, 11.5, GRAY, anchor="start")
        for i in range(5):
            x = x0 + i * (w + 12)
            body += box(x, y, w, 62, SOFT.get(color, "#ffffff") if color != INK else "#ffffff", ORANGE if i == 2 else color, width=2.4 if i == 2 else 1.4)
            for k, v in enumerate(vals[i]):
                body += mtext(x + 20 + (k % 2) * 62, y + 26 + (k // 2) * 24, f"{v:+.3f}", 12.5, color, anchor="start")
        if r < 2:
            body += text(x0 - 22, y + 82, "+" if r == 0 else "=", 22, GRAY, "bold")
    m = 2
    body += text(480, 392, f"以“明”为例，第 1 个数：({demo['tok'][m][0]:+.3f}) + ({demo['pos'][m][0]:+.3f}) = {demo['sum'][m][0]:+.3f}；96 个数都这样逐个相加", 14, ORANGE, "bold")
    body += text(480, 418, "同一个字换到别的位置，加上的是另一行位置向量，进模型的向量就不一样了", 13.5, GRAY)
    svg("quickstart-position-add.svg", "字向量加位置向量",
        "“床前明月光”五个字，每个字查字表得到字向量，再按它排在第几位查位置表得到位置向量，两者逐个数相加，就是进模型的向量。"
        f"以第 2 位（从 0 数）的“明”为例，第一个数是 ({demo['tok'][m][0]:+.3f}) + ({demo['pos'][m][0]:+.3f}) = {demo['sum'][m][0]:+.3f}。", 440, body)


def quickstart_flow():
    """快速体验的八步串成一条链路：上排前向，下排反向与更新，⑦ 绕回开头，⑧ 训练完沿顶部弧线生成。
    数字取自 quickstart.py 的真实输出（见 docs/tinyllm/quickstart.md）。"""
    body = text(480, 36, "八步在同一条链路上：前向算出损失，反向更新参数，重复之后拿来写诗", 21, weight="bold")
    # 上排：前向（w=130，间隔 22）
    top, h, w = 120, 100, 130
    xs = [35, 187, 339, 491, 643, 795]
    row1 = [
        (GRAY, "文字", "“床前明月光”", ""),
        (BLUE, "① 分词", "每个字一个编号", "(1, 5)"),
        (BLUE, "② 词嵌入", "编号当行号查表", "(1, 5, 96)"),
        (BLUE, "④ 加位置", "每个位置一行向量", "+ (5, 96)"),
        (BLUE, "③ 注意力", "因果掩码只看左边", "3 层 Block"),
        (BLUE, "输出层", "给每个字打分", "(1, 5, 1458)"),
    ]
    body += box(327, 108, 610, 124, "none", GRAY, dash=True)
    for x, (color, title, sub, shape) in zip(xs, row1):
        cx = x + w / 2
        body += cbox(x, top, w, h, color)
        if shape:
            body += text(cx, top + 30, title, 16, INK, "bold")
            body += text(cx, top + 56, sub, 13, color)
            body += mtext(cx, top + 82, shape, 14, color)
        else:
            body += text(cx, top + 42, title, 16, INK, "bold")
            body += text(cx, top + 70, sub, 15, INK)
    for a, b in zip(xs, xs[1:]):
        body += arrow(a + w + 2, top + h / 2, b - 3, top + h / 2, GRAY, 2.5)
    body += text(632, 254, "虚线框里是被训练的参数，共 474,720 个", 13.5, GRAY)

    # 下排：从右往左，损失 → 梯度 → 更新
    y2, w2 = 330, 170
    row2 = [
        (755, ORANGE, "⑤ 损失", "交叉熵 7.83", "乱猜水位 ln 1458 = 7.29"),
        (560, RED, "⑥ 反向传播", "backward() 算梯度", "24 个张量，总范数 3.5"),
        (365, TEAL, "更新参数", "AdamW 挪一小步", "同一批数据：7.83 → 7.07"),
    ]
    for x, color, title, sub, note in row2:
        cx = x + w2 / 2
        body += cbox(x, y2, w2, h, color)
        body += text(cx, y2 + 30, title, 16, INK, "bold")
        body += text(cx, y2 + 56, sub, 13.5, color)
        body += text(cx, y2 + 80, note, 13, color)
    body += path(f"M860 {top + h + 2}L860 {y2 - 3}", ORANGE, 2.5)
    body += text(848, 290, "和正确答案比", 13, ORANGE, anchor="end")
    body += arrow(753, y2 + h / 2, 733, y2 + h / 2, RED, 2.5)
    body += arrow(558, y2 + h / 2, 538, y2 + h / 2, TEAL, 2.5)
    body += path(f"M450 {y2 - 2}L450 238", TEAL, 2.5, dash=True)
    body += text(462, 300, "改参数", 13, TEAL, anchor="start")

    # ⑦：换一批数据绕回开头
    body += path(f"M363 {y2 + h / 2}L130 {y2 + h / 2}C100 {y2 + h / 2} 100 {y2 + h / 2 - 20} 100 {y2 + h / 2 - 40}L100 {top + h + 3}", TEAL, 2.5)
    body += text(235, y2 + h / 2 - 32, "⑦ 换一批诗句再走一遍", 14, TEAL, "bold")
    body += text(235, y2 + h / 2 + 24, "共 1000 步", 13.5, TEAL)

    # ⑧：训练完，沿顶部弧线把抽到的字接回文字末尾
    body += path(f"M860 {top - 2}C860 52 100 52 100 {top - 3}", PURPLE, 2.5, dash=True)
    body += text(480, 94, "⑧ 训练完：按最后一个位置的分数抽一个字，接到文字末尾，重复 40 次", 14, PURPLE, "bold")

    body += text(480, 478, "⑦ 跑完：训练损失 7.29 → 0.28；验证损失第 100 步最低 6.22，之后升到 8.75——模型从“学”变成了“背”。", 14.5, INK)
    body += text(480, 506, "圆圈编号是本页的步骤号；④ 画在 ③ 前面，是因为数据先加上位置、再进注意力。", 13.5, GRAY)
    svg("quickstart-flow.svg", "快速体验的八步流程",
        "上排是前向：文字“床前明月光”经①分词变成 5 个编号，②查词嵌入表得到 (1,5,96) 的向量，④加上位置向量，③经过 3 层带因果掩码的注意力 Block，"
        "输出层给词表里 1458 个字各打一个分。下排从右往左：⑤用交叉熵和正确答案比，随机参数下是 7.83，乱猜水位 7.29；"
        "⑥反向传播给 24 个参数张量算出梯度；AdamW 更新参数后同一批数据的损失降到 7.07。⑦换一批数据绕回开头，共重复 1000 步，"
        "训练损失降到 0.28，验证损失在第 100 步最低 6.22 后升到 8.75。⑧训练完后，按最后一个位置的分数抽一个字接回文字末尾，重复 40 次写出诗句。",
        530, body)


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


# ---------- 第 10、8、4、5、16、19 章共用工具 ----------

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


# ---------- 第 10 章：初始化与残差 ----------

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


# ---------- 第 8 章：激活与门控前馈层 ----------

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


# ---------- 第 4 章：词元化 ----------

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


# ---------- 第 5 章：词嵌入与输出层 ----------

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


# ---------- 第 16 章：优化器 ----------

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


# ---------- 第 19 章：数值精度 ----------

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


# ---------- 第 3 章：架构演进 ----------

def architecture_timeline():
    body = text(480, 38, "三代架构：目标没变，零件一直在换", 22, weight="bold")
    gens = [
        (20, 250, "第一代 · 2017", "编码器-解码器", BLUE, "为翻译设计：读原文，写译文", [
            ("2017", "Transformer", "注意力取代循环网络"),
            ("", "", "位置编码标出词序"),
            ("", "", "需要“原文 → 译文”成对数据")]),
        (285, 330, "第二代 · 2018～2023", "只有解码器（稠密）", TEAL, "任何文本都能学：预测下一个 token", [
            ("2018", "GPT-1", "去掉编码器"),
            ("2019", "GPT-2", "归一化挪到子层前（Pre-Norm）"),
            ("2020", "GPT-3", "1750 亿参数，看几个例子就会做新任务"),
            ("2021", "RoPE", "旋转位置编码"),
            ("2023", "LLaMA / Llama 2", "RMSNorm、SwiGLU、RoPE；GQA")]),
        (630, 310, "第三代 · 2024～2026", "稀疏 + 混合注意力", ORANGE, "同一个目标，做大且省", [
            ("2024", "DeepSeek-V2/V3", "MLA 压缩 KV；细粒度 MoE"),
            ("2025", "Qwen3-Next、Kimi Linear", "线性注意力 : 完整注意力 = 3 : 1"),
            ("2026", "Kimi K3", "2.8 万亿参数，896 个专家选 16 个，"),
            ("", "", "100 万 token 上下文")]),
    ]
    for x, w, head, sub, c, goal, rows in gens:
        body += cbox(x, 62, w, 370, c)
        body += text(x + w / 2, 90, head, 17, c, "bold") + text(x + w / 2, 114, sub, 15, INK, "bold")
        body += text(x + w / 2, 140, goal, 12.5, GRAY)
        y = 176
        for yr, name, note in rows:
            if name:
                body += text(x + 16, y, yr, 13, c, "bold", "start") + text(x + 58, y, name, 14, INK, "bold", "start")
                y += 20
            body += text(x + 58, y, note, 12.5, INK, anchor="start")
            y += 26
    body += arrow(272, 220, 283, 220, GRAY, 2) + arrow(617, 220, 628, 220, GRAY, 2)
    body += text(480, 462, "TinyLLM 的主线就是第二代的“现代稠密解码器”；第三代的 MoE、KV 压缩和混合注意力在后面的专题里讲。", 14, GRAY)
    svg("architecture-timeline.svg", "大模型架构的三代演进",
        "第一代（2017）：为翻译设计的编码器-解码器 Transformer，用注意力取代循环网络、用位置编码标出词序，需要成对数据。第二代（2018～2023）：只有解码器，预测下一个 token；GPT-1 去掉编码器，GPT-2 把归一化挪到子层前，GPT-3 扩大到 1750 亿参数，2021 年出现 RoPE，2023 年 LLaMA 与 Llama 2 采用 RMSNorm、SwiGLU、RoPE 和 GQA。第三代（2024～2026）：稀疏加混合注意力；DeepSeek-V2/V3 用 MLA 压缩 KV 并采用细粒度 MoE，Qwen3-Next 与 Kimi Linear 把线性注意力和完整注意力按 3:1 混合，Kimi K3 有 2.8 万亿参数、896 个专家每次选 16 个、100 万 token 上下文。", 485, body)


def architecture_cost():
    d = load("tinyllm-architecture-cost.json")
    T = np.array(d["T"], float)
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    w = 0.36
    pos = np.arange(len(T))
    b1 = ax.bar(pos - w / 2, d["full"], w, color=BLUE, label="每层都是完整注意力")
    b2 = ax.bar(pos + w / 2, d["hybrid"], w, color=ORANGE, label="3 层线性注意力 + 1 层完整注意力")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.15, f"{b.get_height():.2f}", ha="center", fontsize=11)
    ax.set_yscale("log")
    ax.set_xticks(pos, [f"{int(t):,}" for t in T])
    ax.set_xlabel("上下文长度（token）")
    ax.set_ylabel("生成时要保存的缓存（GB，对数刻度）")
    c = d["config"]
    ax.set_title(f"{c['layers']} 层、每层 {c['kv_heads']} 个 KV 头、每头 {c['head_dim']} 维、BF16 的估算", fontsize=13)
    ax.set_ylim(0.05, 600)
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25, axis="y")
    save_plot(fig, "architecture-cost.svg", "完整注意力与混合注意力的缓存大小",
              f"按 32 层、每层 8 个 KV 头、每头 128 维、BF16 估算：每层都用完整注意力时，缓存从 4096 个 token 的 {d['full'][0]:.2f} GB 涨到 100 万个 token 的 {d['full'][-1]:.0f} GB；3 层线性注意力加 1 层完整注意力时只有约四分之一，100 万个 token 约 {d['hybrid'][-1]:.0f} GB。")


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


# ---------- 第 6 章：自注意力 ----------

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


# ---------- 第 9 章：Transformer Block ----------

def block_anatomy():
    d = load("tinyllm-block-depth.json")["params"]
    body = text(480, 38, "同样两个子层，两种装法", 22, weight="bold")
    # 左：直接堆叠
    cx = 220
    body += text(cx, 80, "直接堆叠", 19, RED, "bold")
    body += mtext(cx, 112, "x  [B, T, d]", 16)
    body += arrow(cx, 120, cx, 146)
    body += cbox(cx - 120, 148, 240, 58, BLUE) + text(cx, 172, "注意力", 18, BLUE, "bold") + text(cx, 195, "token 之间交换信息", 14, GRAY)
    body += arrow(cx, 206, cx, 236)
    body += cbox(cx - 120, 238, 240, 58, TEAL) + text(cx, 262, "SwiGLU 前馈层", 18, TEAL, "bold") + text(cx, 285, "每个 token 自己加工", 14, GRAY)
    body += arrow(cx, 296, cx, 322)
    body += mtext(cx, 342, "out  [B, T, d]", 16)
    body += text(cx, 392, "x 被整个替换掉：", 15, RED)
    body += text(cx, 416, "下一层只能看到这一层的输出", 15, RED)
    # 右：Pre-Norm 残差
    sx, bx = 560, 760          # 残差流的 x 坐标、子层的中心
    body += text(680, 80, "Pre-Norm 残差 Block（TinyLLM 采用）", 19, TEAL, "bold")
    body += mtext(sx, 112, "x  [B, T, d]", 16)
    body += f'<path d="M{sx} 122 V500" stroke="{INK}" stroke-width="6" fill="none" opacity="0.18"/>'
    body += text(sx - 16, 320, "残差流", 15, GRAY, anchor="end")
    for k, (y, name, color, role, n) in enumerate([(150, "注意力", BLUE, "token 之间交换信息", d["attn"]),
                                                   (330, "SwiGLU", TEAL, "每个 token 自己加工", d["ffn"])]):
        body += path(f"M{sx} {y + 6} H{bx - 112}", GRAY, 2)
        body += cbox(bx - 110, y - 16, 110, 40, PURPLE) + text(bx - 55, y + 10, "RMSNorm", 15, PURPLE, "bold")
        body += arrow(bx, y + 24, bx, y + 44, GRAY, 2)
        body += cbox(bx - 125, y + 46, 250, 56, color) + text(bx, y + 70, f"{name} · {n:,} 个参数", 16, color, "bold") + text(bx, y + 92, role, 13.5, GRAY)
        body += path(f"M{bx} {y + 102} V{y + 128} H{sx + 20}", color, 2.5)
        body += circle(sx, y + 128, 16) + text(sx, y + 135, "+", 22, weight="bold")
    body += arrow(sx, 474, sx, 500, GRAY)
    body += mtext(sx, 522, "out  [B, T, d]", 16)
    body += text(650, 500, "子层只读一份归一化后的副本，结果加回 x", 14, TEAL, anchor="start")
    body += text(650, 522, f"d = {d['d']}；两个 RMSNorm 共 {d['norm']} 个参数", 14, GRAY, anchor="start")
    body += f'<line x1="440" y1="66" x2="440" y2="440" stroke="#e2e8f0" stroke-width="2"/>'
    svg("block-anatomy.svg", "Transformer Block 的两种装法",
        f"左：直接堆叠，x 先过注意力再过 SwiGLU，输出整个替换 x。右：Pre-Norm 残差 Block，x 沿残差流一路向下，两次分出副本经 RMSNorm 进入注意力或 SwiGLU，结果加回残差流；d=64 时注意力 {d['attn']:,} 个参数，SwiGLU {d['ffn']:,} 个，两个 RMSNorm {d['norm']} 个。", 545, body)


def block_depth():
    d = load("tinyllm-block-depth.json")
    runs, sig = list(d["runs"].values()), d["signal"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.2), layout="constrained")
    (a_tr, a_va), (a_gr, a_sg) = axes
    styles = {"直接堆叠": RED, "只加残差": ORANGE, "只加 Pre-Norm": PURPLE, "Pre-Norm 残差": TEAL}
    mean = lambda v: sum(v) / len(v)

    def err(vals):
        m = np.array([mean(v) for v in vals])
        return m, [m - np.array([min(v) for v in vals]), np.array([max(v) for v in vals]) - m]

    for kind, color in styles.items():
        rs = [r for r in runs if r["kind"] == kind]
        L = np.array([r["layers"] for r in rs], float)
        for ax, key in ((a_tr, "train"), (a_va, "val")):
            m, e = err([r[key] for r in rs])
            ax.errorbar(L, m, yerr=e, fmt="o-", color=color, lw=2.2, capsize=4, label=kind)
        g = np.array([max(r["grad0"][1], 1e-12) for r in rs])
        lo = np.array([max(r["grad0"][0], 1e-12) for r in rs]); hi = np.array([max(r["grad0"][-1], 1e-12) for r in rs])
        a_gr.errorbar(L, g, yerr=[g - lo, hi - g], fmt="o-", color=color, lw=2.2, capsize=4, label=kind)
        for l, r in zip(L, rs):
            if r["grad0"][-1] == 0:
                a_gr.annotate("= 0", (l, 1e-12), textcoords="offset points", xytext=(0, 8), ha="center", color=color, fontsize=11)
        s_ = np.exp(np.mean(np.log(np.maximum(np.array(sig[kind]), 1e-30)), axis=0))
        a_sg.semilogy(range(len(s_)), s_, "o-", color=color, lw=2, label=kind)
    for ax, title in ((a_tr, "训练损失（训练 100 步，3 个种子）"), (a_va, "验证损失（4 首没训练过的诗）")):
        ax.axhline(d["uniform"], color=GRAY, ls=":", lw=1.2)
        ax.text(8.2, d["uniform"] + 0.12, f"完全乱猜 {d['uniform']:.2f}", ha="right", color=GRAY, fontsize=10.5)
        ax.set(xlabel="Block 层数", ylabel="损失（平均，竖线为范围）", xticks=[1, 4, 8])
        ax.set_title(title, fontsize=13)
    a_tr.set_ylim(0, 7.8)
    a_va.set_ylim(5.5, 7.8)
    a_gr.set_yscale("log")
    a_gr.set(xlabel="Block 层数", ylabel="第 1 个 Block 的梯度（第一步）", xticks=[1, 4, 8], ylim=(1e-13, 100))
    a_gr.set_title("第一步时，梯度能否传回第 1 层", fontsize=13)
    a_sg.set(xlabel="穿过的 Block 数（训练前）", ylabel="token 向量的 RMS", ylim=(1e-31, 10))
    a_sg.text(4.3, 1e-28, "画在底部的点已下溢为 0", fontsize=10, color=RED)
    a_sg.set_title("训练前，信号穿过 8 个 Block", fontsize=13)
    for ax in axes.flat:
        ax.grid(alpha=0.25)
        ax.legend(fontsize=9.5, framealpha=0.95, loc="center left" if ax is a_tr else "best")
    r = d["runs"]
    save_plot(fig, "block-depth.svg", "四种 Block 写法的叠深对照",
              f"同一组 batch、3 个随机种子、各训练 100 步、PyTorch 默认初始化。训练损失：直接堆叠 1 层 {mean(r['直接堆叠 1']['train']):.2f}，4、8 层停在乱猜的 {d['uniform']:.2f}；只加残差 4.3 到 4.7；只加 Pre-Norm 1 层 {mean(r['只加 Pre-Norm 1']['train']):.2f}，4、8 层停在 5.4 左右；残差加 Pre-Norm 从 {mean(r['Pre-Norm 残差 1']['train']):.2f} 降到 {mean(r['Pre-Norm 残差 8']['train']):.2f}。验证损失全部在 6.2 到 7.4 之间，没有明显好于乱猜。第一步时第 1 个 Block 的梯度：直接堆叠 4 层以上为 0，其余三种都能传回。训练前信号：直接堆叠每层至少缩小上千倍并下溢为 0，其余三种保持在 0.1 以上。")


# ---------- 第 7 章：位置表示 ----------

def position_methods():
    body = text(480, 36, "把位置放进模型的三种做法", 21, weight="bold")
    cols = [(170, "可学习绝对位置", BLUE, ["位置 0、1、2… 各查一行", "可训练的向量表", "加到词向量上，只加一次"], "表有几行，就只能处理几个位置"),
            (480, "正弦位置编码", TEAL, ["位置 m 的向量由 sin/cos", "按固定公式算出", "加到词向量上，只加一次"], "不用训练，任意位置都能算"),
            (790, "RoPE 旋转位置", ORANGE, ["不加任何向量", "在每一层注意力里", "把 q、k 按位置转一个角度"], "点积只依赖两者相隔几个位置")]
    for x, title, c, lines, note in cols:
        body += cbox(x - 135, 64, 270, 46, c, width=2.5) + text(x, 94, title, 18, c, "bold")
        body += box(x - 135, 124, 270, 112)
        for i, line in enumerate(lines):
            body += text(x, 154 + i * 30, line, 15)
        body += text(x, 266, note, 14.5, GRAY)
    # 简图：输入相加 vs 注意力内部旋转
    for x, c in ((170, BLUE), (480, TEAL)):
        body += cbox(x - 110, 296, 100, 40, GRAY) + text(x - 60, 321, "词向量", 14)
        body += cbox(x + 10, 296, 100, 40, c) + text(x + 60, 321, "位置向量", 14)
        body += circle(x, 376, 15) + text(x, 382, "+", 20, weight="bold")
        body += path(f"M{x - 60} 336 L{x - 12} 366", GRAY, 2) + path(f"M{x + 60} 336 L{x + 12} 366", GRAY, 2)
        body += arrow(x, 391, x, 418, GRAY, 2) + text(x, 440, "进入第 1 层", 14, GRAY)
    x = 790
    body += cbox(x - 125, 296, 250, 40, GRAY) + mtext(x, 321, "q = W_q·h,  k = W_k·h", 15)
    body += arrow(x, 336, x, 362, GRAY, 2)
    body += cbox(x - 125, 364, 250, 40, ORANGE) + text(x, 389, "q 转 m·θ，k 转 n·θ", 15, ORANGE, "bold")
    body += arrow(x, 404, x, 418, GRAY, 2) + text(x, 440, "每一层、每个头都做", 14, GRAY)
    svg("position-methods.svg", "把位置放进模型的三种做法",
        "可学习绝对位置为每个位置查一行可训练向量，加到词向量上，只能处理表里有的位置；正弦位置编码用固定公式算出位置向量再相加，不用训练；RoPE 不加向量，而是在每一层注意力里把 q 和 k 按位置旋转，点积只依赖两者的相对距离。", 465, body)


def _rope_np(x, positions, base=10000.0):
    d = x.shape[-1]
    theta = base ** (-np.arange(0, d, 2) / d)
    ang = np.asarray(positions, float)[:, None] * theta
    x1, x2 = x[..., 0::2], x[..., 1::2]
    out = np.empty_like(x)
    out[..., 0::2] = x1 * np.cos(ang) - x2 * np.sin(ang)
    out[..., 1::2] = x1 * np.sin(ang) + x2 * np.cos(ang)
    return out


def sinusoidal_heatmap():
    T, d = 64, 32
    pos = np.arange(T)[:, None]
    freq = 10000.0 ** (-np.arange(0, d, 2) / d)
    pe = np.zeros((T, d))
    pe[:, 0::2], pe[:, 1::2] = np.sin(pos * freq), np.cos(pos * freq)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained", gridspec_kw={"width_ratios": [1.25, 1]})
    im = ax.imshow(pe.T, aspect="auto", cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xlabel("位置 m")
    ax.set_ylabel("维度 i")
    ax.set_title("正弦位置编码（64 个位置 × 32 维）", fontsize=14)
    fig.colorbar(im, ax=ax, shrink=0.85)
    for i, c in ((0, RED), (8, ORANGE), (20, TEAL)):
        ax2.plot(np.arange(T), pe[:, i], color=c, lw=2.2, label=f"维度 {i}（每 {2 * np.pi / freq[i // 2]:.0f} 个位置转一圈）")
    ax2.set_xlabel("位置 m")
    ax2.set_ylim(-1.25, 1.6)
    ax2.legend(loc="upper right", fontsize=10.5, framealpha=0.95)
    ax2.set_title("同一个位置，不同维度转得快慢不同", fontsize=14)
    ax2.grid(alpha=0.25)
    save_plot(fig, "sinusoidal-heatmap.svg", "正弦位置编码",
              "左图是 64 个位置、32 维的正弦位置编码，低维度变化快、高维度变化慢；右图画出三个维度随位置的变化：维度 0 约 6 个位置一圈，维度 8 约 63 个位置一圈，维度 20 变化很慢。")


def rope_rotation():
    rng = np.random.default_rng(0)
    q, k = np.array([1.2, 0.0]), 1.2 * np.array([np.cos(1.92), np.sin(1.92)])
    theta = 0.5
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), layout="constrained")

    def rot(v, a):
        return np.array([v[0] * np.cos(a) - v[1] * np.sin(a), v[0] * np.sin(a) + v[1] * np.cos(a)])

    for ax, (m, n) in zip(axes[:2], ((2, 0), (6, 4))):
        qm, kn = rot(q, m * theta), rot(k, n * theta)
        ax.add_patch(plt.Circle((0, 0), 1.27, fill=False, color="#cbd5e1", lw=1, ls="--"))
        a0 = np.arctan2(qm[1], qm[0])
        a1 = a0 + (np.arctan2(kn[1], kn[0]) - a0 + np.pi) % (2 * np.pi) - np.pi   # 走较短的那一侧
        arc = np.linspace(a0, a1, 30)
        ax.plot(0.45 * np.cos(arc), 0.45 * np.sin(arc), color=GRAY, lw=1.6)
        mid = (a0 + a1) / 2
        ax.text(0.68 * np.cos(mid), 0.68 * np.sin(mid), "夹角\n不变", color=GRAY, ha="center", va="center", fontsize=11)
        for v, c, lab in ((qm, BLUE, f"位置 {m} 的 q\n转了 {m}θ"), (kn, ORANGE, f"位置 {n} 的 k\n转了 {n}θ")):
            ax.annotate("", xy=v, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=c, lw=2.6))
            u = v / np.linalg.norm(v)
            ax.text(*(u * 1.62), lab, color=c, ha="center", va="center", fontsize=11.5)
        ax.plot(0, 0, "o", color=INK, ms=3)
        ax.set_title(f"m = {m}，n = {n}：q·k = {qm @ kn:.3f}", fontsize=14)
        ax.set_xlim(-2.1, 2.1), ax.set_ylim(-2.1, 2.1), ax.set_aspect("equal"), ax.axis("off")
    # 右：真实 64 维向量，分数只依赖 m − n
    d = 64
    qv, kv = rng.normal(size=d), rng.normal(size=d)
    offs = np.arange(0, 40)
    ax = axes[2]
    for start, c, mk in ((0, BLUE, "o"), (20, ORANGE, "x"), (60, TEAL, "+")):
        s = [(_rope_np(qv[None], [start + o]) @ _rope_np(kv[None], [start]).T).item() / np.sqrt(d) for o in offs]
        ax.plot(offs, s, color=c, lw=1.6, marker=mk, ms=5, label=f"k 在位置 {start}")
    ax.set_xlabel("相隔的位置数 m − n")
    ax.set_ylabel("q·k / √d")
    ax.set_title("64 维：三条曲线完全重合", fontsize=14)
    ax.legend(fontsize=10.5, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "rope-rotation.svg", "RoPE：按位置旋转 q 和 k",
              "左边两幅是同一对二维向量：位置 2 和 0、位置 6 和 4 时 q、k 都被转了不同角度，但两者夹角相同，点积也相同；右图是 64 维随机向量，把 k 放在位置 0、20、60，分数随相隔距离变化的三条曲线完全重合。")


def position_ablation():
    d = load("tinyllm-position-ablation.json")
    ex = d["extrapolate"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12, 4.3), layout="constrained", gridspec_kw={"width_ratios": [1.2, 1]})
    for (name, r), color in zip(d["runs"].items(), [RED, BLUE, ORANGE]):
        loss = np.array(r["loss"])
        smooth = np.convolve(loss, np.ones(15) / 15, mode="valid")
        ax.plot(np.arange(len(smooth)) + 7, smooth, color=color, lw=2.2, label=f"{name}（最后 50 步 {loss[-50:].mean():.2f}）")
    ax.set_xlabel("训练步数")
    ax.set_ylabel("训练损失（15 步滑动平均）")
    ax.set_title("实验一：背唐诗（训练损失，单个种子）", fontsize=13)
    ax.legend(loc="upper right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    labels = ["没有位置\n长度 24", "可学习绝对\n长度 24", "RoPE\n长度 24", "RoPE\n长度 48", "RoPE\n长度 96"]
    lists = [ex["task"]["none"], ex["task"]["learned"], ex["task"]["rope"], ex["task_rope_long"]["48"], ex["task_rope_long"]["96"]]
    vals = [sum(v) / len(v) for v in lists]
    errs = [[v - min(l) for v, l in zip(vals, lists)], [max(l) - v for v, l in zip(vals, lists)]]
    colors = [RED, BLUE, ORANGE, "#f59e0b", "#fcd34d"]
    bars = ax2.bar(range(5), vals, color=colors, width=0.62, yerr=errs, capsize=4, ecolor=INK)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=12)
    ax2.axhline(1 / 32, color=GRAY, lw=1, ls="--")
    ax2.text(4.4, 1 / 32 + 0.02, "瞎猜 1/32", ha="right", fontsize=10.5, color=GRAY)
    ax2.set_xticks(range(5), labels, fontsize=10.5)
    ax2.set_ylim(0, 1.12)
    ax2.set_ylabel("准确率")
    ax2.set_title("实验二：往前数第 3 个符号（测试集，3 个种子）", fontsize=13)
    ax2.grid(alpha=0.25, axis="y")
    save_plot(fig, "position-ablation.svg", "位置表示的两个对照实验",
              f"左图：唐诗语料上三种做法按同一组 batch 训练 400 步，训练损失几乎一样。右图：输出往前数第 3 个符号的任务，在新生成的测试序列上、3 个种子平均，没有位置时准确率 {vals[0]:.2f}，可学习绝对位置和 RoPE 都是 1.00；RoPE 在长度 48 上 {vals[3]:.2f}，长度 96 上 {vals[4]:.2f}。")


# ---------- 第 12 章：完整 TinyLLM ----------

def tinyllm_model_shapes():
    log = json.loads((DATA / "tinyllm-model-log.json").read_text(encoding="utf-8"))
    sh = log["shapes"]
    B, T, d, V, L, H, hid = sh["batch"], sh["tokens"], sh["d_model"], sh["vocab"], sh["n_layers"], sh["n_heads"], sh["ffn_hidden"]
    attn, ffn, norms = 4 * d * d, 3 * d * hid, 2 * d
    blk = attn + ffn + norms
    emb, total = V * d, V * d + L * blk + d
    body = text(480, 38, f"完整 TinyLLM：一段 {T} 个 token 的输入走一遍（d={d}，{L} 层，词表 {V}）", 21, weight="bold")
    cx = 250
    body += mtext(cx, 80, f"token ID  [{B}, {T}]", 16)
    body += arrow(cx, 88, cx, 110)
    body += cbox(cx - 150, 112, 300, 46, BLUE) + text(cx, 141, f"词嵌入表 E：{V} × {d}", 17, BLUE, "bold")
    body += arrow(cx, 158, cx, 180)
    body += mtext(cx, 198, f"[{B}, {T}, {d}]", 16)
    # Block 框
    body += box(cx - 190, 212, 380, 236, "#ffffff", TEAL, True, 2.5)
    body += text(cx + 178, 236, f"× {L} 层", 17, TEAL, "bold", anchor="end")
    body += text(cx - 178, 236, "Pre-Norm Block", 15, TEAL, anchor="start")
    for k, (y, label, sub, color) in enumerate([(254, "RMSNorm → 因果注意力", f"{H} 头 × {d // H} 维，Q/K 加 RoPE", BLUE),
                                                (346, "RMSNorm → SwiGLU", f"{d} → {hid} → {d}", TEAL)]):
        body += cbox(cx - 160, y, 320, 58, color) + text(cx, y + 25, label, 17, color, "bold") + text(cx, y + 47, sub, 14, GRAY)
        body += circle(cx, y + 76, 13) + text(cx, y + 82, "+", 19, weight="bold")
    body += text(cx + 172, 340, "残差相加", 13, GRAY, anchor="end")
    body += arrow(cx, 448, cx, 470)
    body += mtext(cx, 488, f"[{B}, {T}, {d}]", 16)
    body += cbox(cx - 150, 500, 300, 40, PURPLE) + text(cx, 526, "最终 RMSNorm", 17, PURPLE, "bold")
    body += arrow(cx, 540, cx, 560)
    body += cbox(cx - 150, 562, 300, 44, ORANGE) + text(cx, 590, "乘 Eᵀ：输出层与嵌入共享", 17, ORANGE, "bold")
    body += arrow(cx, 606, cx, 626)
    body += mtext(cx, 646, f"logits  [{B}, {T}, {V}]", 16)
    body += path(f"M{cx + 150} 135 H{cx + 205} V584 H{cx + 158}", ORANGE, 2.5, True)
    body += text(cx + 214, 360, "同一块", 14, ORANGE, anchor="start") + text(cx + 214, 380, "权重", 14, ORANGE, anchor="start")
    # 右侧：参数都在哪
    x0, y0, wmax = 560, 110, 330
    body += text(x0 + wmax / 2, 84, f"{total:,} 个参数都在哪", 18, weight="bold")
    rows = [("嵌入表（兼输出层）", emb, BLUE), (f"{L} 个 Block 合计", L * blk, TEAL),
            ("每个 Block：注意力 4d²", attn, BLUE), ("每个 Block：SwiGLU 3·d·8d/3", ffn, TEAL),
            ("每个 Block：两个 RMSNorm", norms, PURPLE), ("最终 RMSNorm", d, PURPLE)]
    for i, (name, n, color) in enumerate(rows):
        y = y0 + i * 78 + (14 if i >= 2 else 0)
        w = max(3, wmax * n / total)
        body += text(x0, y, name, 15, anchor="start")
        body += f'<rect x="{x0}" y="{y + 10}" width="{w:.1f}" height="22" rx="4" fill="{color}" opacity="0.85"/>'
        body += text(x0 + w + 8, y + 27, f"{n:,}（{n / total:.1%}）", 14, GRAY, anchor="start")
    body += f'<line x1="{x0}" y1="{y0 + 2 * 78 - 8}" x2="{x0 + wmax}" y2="{y0 + 2 * 78 - 8}" stroke="#e2e8f0" stroke-width="2"/>'
    body += text(x0, 640, "条长按占全部参数的比例画", 13, GRAY, anchor="start")
    svg("tinyllm-model-shapes.svg", "完整 TinyLLM 的数据流、形状与参数分布",
        f"左：{T} 个 token 的 ID 查嵌入表变成 [{B}, {T}, {d}]，穿过 {L} 个 Pre-Norm Block（注意力 {H} 头、SwiGLU 中间宽度 {hid}）形状不变，"
        f"最终 RMSNorm 后乘嵌入表的转置得到 [{B}, {T}, {V}] 的 logits。右：共 {total:,} 个参数，嵌入表 {emb:,} 个约占 {emb / total:.0%}，"
        f"{L} 个 Block 合计 {L * blk:,} 个；每个 Block 里 SwiGLU 约是注意力的两倍。", 672, body)


def tinyllm_model_loss():
    log = json.loads((DATA / "tinyllm-model-log.json").read_text(encoding="utf-8"))
    loss = np.array(log["loss"])
    smooth = np.convolve(loss, np.ones(15) / 15, mode="valid")
    uniform = float(np.log(log["baseline"]["vocab"]))
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.plot(loss, color="#cbd5e1", lw=0.8, label="训练损失（每一步）")
    ax.plot(np.arange(len(smooth)) + 7, smooth, color=BLUE, lw=2.4, label="训练损失（15 步滑动平均）")
    ax.plot(log["val_step"], log["val_loss"], color=RED, lw=2.2, marker="o", ms=4, label="验证损失（291 首没训练过的诗，全部算一遍）")
    ax.axhline(uniform, color=ORANGE, ls="--", lw=1.6)
    ax.text(len(loss) * 0.55, uniform + 0.12, f"均匀乱猜：ln {log['baseline']['vocab']} ≈ {uniform:.2f}", color=ORANGE, fontsize=12)
    ax.annotate(f"第 {log['val_step'][-1]} 步：验证 {log['val_loss'][-1]:.2f}，仍在下降",
                xy=(log["val_step"][-1], log["val_loss"][-1]), xytext=(log["val_step"][-1] - 150, log["val_loss"][-1] + 1.4),
                color=RED, fontsize=12, arrowprops=dict(arrowstyle="->", color=RED, lw=1.4))
    ax.set_xlabel("训练步数（每步 32 段 × 64 个 token）")
    ax.set_ylabel("交叉熵（nats / token）")
    ax.set_ylim(4.5, 9.4)
    ax.legend(loc="lower left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "tinyllm-model-loss.svg", "完整 TinyLLM 基线的训练与验证损失",
              f"训练损失和验证损失一起从约 {log['val_loss'][0]:.2f} 降到约 {log['val_loss'][-1]:.2f}，两条线贴在一起，"
              f"第 {log['val_step'][-1]} 步时验证损失仍在下降：这个预算下模型还没学够，也还没开始背训练集。")


# ---------- 第 27 章：自回归生成 ----------

def sampling_truncate():
    """两组六候选概率与 generation.py 第 2 节的 peaked / flat 完全一致（softmax 后的值）。"""
    d = load("tinyllm-sampling.json")["truncate"]
    sharp = [0.7290, 0.2682, 0.0018, 0.0007, 0.0002, 0.0001]
    flat = [0.2109, 0.1908, 0.1727, 0.1562, 0.1414, 0.1279]
    base, scale, step, bw = 330, 210, 56, 42
    body = text(480, 34, "六候选、两种分布：top-k 留几个是常数，top-p 留几个跟着分布走", 21, weight="bold")
    for col, (name, probs, knob) in enumerate([("尖峰分布（句末标点）", sharp, d["peaked"]),
                                               ("平坦分布（逗号之后）", flat, d["flat"])]):
        ox = 70 + col * 460
        body += text(ox + 190, 66, name, 17, INK, "bold")
        for i, p in enumerate(probs):
            h = p * scale
            color = BLUE if i < knob["k"] else GRAY
            fill = "#bfdbfe" if i < knob["p"] else "#e2e8f0"
            body += f'<rect x="{ox + 30 + i * step}" y="{base - h:.1f}" width="{bw}" height="{max(h, 1.5):.1f}" rx="3" fill="{fill}" stroke="{color}" stroke-width="2"/>'
            body += mtext(ox + 51 + i * step, base + 20, f"{p:.2f}", 12, GRAY)
        body += f'<line x1="{ox + 18}" y1="{base}" x2="{ox + 360}" y2="{base}" stroke="#94a3b8" stroke-width="2"/>'
        top = base - max(probs) * scale
        body += f'<rect x="{ox + 26}" y="{top:.1f}" width="{knob["k"] * step - 14}" height="{base - top:.1f}" fill="none" stroke="{BLUE}" stroke-width="2.5" stroke-dasharray="7 5"/>'
        body += f'<rect x="{ox + 26}" y="{top:.1f}" width="{knob["p"] * step - 14}" height="{base - top:.1f}" fill="none" stroke="{TEAL}" stroke-width="0" stroke-dasharray="2 3"/>'
        body += text(ox + 96, top - 10, f"top-k = 3 留 {knob['k']} 个", 15, BLUE, "bold")
        body += text(ox + 190, base + 66, f"top-p = 0.9 留 {knob['p']} 个 · top-k = 3 留 {knob['k']} 个", 15, INK, "bold")
        body += text(ox + 190, base + 92, "框内是留下的候选，重新归一化后再抽样", 13, GRAY)
    p_sharp2, p_flat3 = sum(sharp[:2]), sum(flat[:3])
    body += text(480, 470, f"尖峰时前两个候选占 {p_sharp2 * 100:.1f}%，top-p 只要 2 个就够；平坦时六个各占一成多，top-p 要 6 个。", 14.5, GRAY)
    body += text(480, 496, f"同样留 3 个：左边多留的那个概率只有 0.002，右边却砍掉了 {1 - p_flat3:.0%} 的概率质量。", 14.5, GRAY)
    svg("sampling-truncate.svg", "top-k 与 top-p 在尖峰和平坦分布上的区别",
        f"左：尖峰分布，前两个候选占 {p_sharp2 * 100:.1f}%，top-p(0.9) 只要 2 个，top-k=3 却留了 3 个，第三个概率只有 0.002。"
        f"右：平坦分布，六个候选各占一成多，top-p(0.9) 要 6 个，top-k=3 只留 3 个，砍掉了 {1 - p_flat3:.0%} 的概率质量。"
        "两图合起来说明 top-p 的集合大小随分布变化，top-k 不变。", 516, body)


def sampling_difficulty():
    d = load("tinyllm-sampling.json")["difficulty"]
    labels = [f"{r['prompt'][:5]}\n{r['char']}" for r in d]
    ent = np.array([r["entropy"] for r in d])
    nuc = np.array([r["nucleus"] for r in d])
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    x = np.arange(len(d))
    ax.bar(x, ent, color=BLUE, width=0.6, label="熵（nat）")
    for xi, v in zip(x, ent):
        ax.text(xi, v + 0.12, f"{v:.2f}", ha="center", fontsize=10, color=BLUE)
    ax.set_ylabel("下一个字的熵（nat）", color=BLUE)
    ax.tick_params(axis="y", colors=BLUE)
    ax.set_xticks(x, labels, fontsize=10)
    ax.set_ylim(0, max(ent) * 1.35)
    ax2 = ax.twinx()
    ax2.plot(x, nuc, color=ORANGE, lw=2.4, marker="o", ms=7, label="top-p(0.9) 需要的候选数")
    for xi, v in zip(x, nuc):
        ax2.text(xi, v * 1.18, f"{v}", ha="center", fontsize=10, color=ORANGE)
    ax2.set_yscale("log")
    ax2.set_ylabel("top-p(0.9) 需要的候选数（对数）", color=ORANGE)
    ax2.tick_params(axis="y", colors=ORANGE)
    ax2.set_ylim(0.7, max(nuc) * 3)
    ax.axvline(3.5, color=GRAY, lw=1.2, ls="--")
    ax.text(3.6, max(ent) * 1.18, "换一句提示词", fontsize=11, color=GRAY, ha="left")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.2)
    save_plot(fig, "sampling-difficulty.svg", "同一个模型，不同位置的熵与 top-p 候选数",
              "横轴是两首诗逐字喂进模型后的位置。柱子是下一个字的熵，橙线是 top-p(0.9) 需要几个候选。"
              "两条曲线同起同落：句末标点“晓”“人”之后熵低于 1，只要 1 到 2 个候选；逗号之后熵升到 4 以上，要四百多个候选。"
              "固定的 top-k 不可能在这整条曲线上都合适。")


def guided_decoding():
    body = text(480, 36, "约束解码的一步：把不合法的 token 打分设成 −∞，再归一化、抽样", 21, weight="bold")
    # 左：整张词表
    body += text(170, 78, "词表 2048 个 token 的打分", 16, INK, "bold")
    body += box(50, 92, 240, 300, "#ffffff", "#cbd5e1")
    rows = [("单字 token（1310 个）", BLUE, 150), ("标点（2 个）", TEAL, 26), ("字节碎片与特殊 token", GRAY, 70)]
    y = 104
    for label, color, h in rows:
        body += f'<rect x="62" y="{y}" width="216" height="{h}" rx="6" fill="{SOFT[color]}" stroke="{color}" stroke-width="2"/>'
        body += text(170, y + h / 2 + 6, label, 14, color, "bold")
        y += h + 12
    body += text(170, 412, "softmax 之后", 14, GRAY)
    # 中：掩码
    body += text(480, 78, "这一步允许的集合", 16, INK, "bold")
    body += box(370, 92, 220, 300, "#ffffff", RED, True)
    body += f'<rect x="382" y="104" width="196" height="150" rx="6" fill="{SOFT[BLUE]}" stroke="{BLUE}" stroke-width="2"/>'
    body += text(480, 172, "五言模板：单字", 15, BLUE, "bold")
    body += text(480, 196, "第 7 个字符", 14, GRAY)
    body += f'<rect x="382" y="266" width="196" height="114" rx="6" fill="#f1f5f9" stroke="#94a3b8" stroke-width="2" stroke-dasharray="7 5"/>'
    body += mtext(480, 316, "-inf", 22, RED, "bold")
    body += text(480, 344, "句末位置换成标点集合", 13, GRAY)
    body += arrow(346, 242, 366, 242, RED)
    body += text(356, 228, "掩码", 13, RED)
    # 右：结果
    body += text(790, 78, "抽样结果", 16, INK, "bold")
    body += box(690, 92, 200, 138, "#ffffff", TEAL)
    body += text(790, 126, "之 看 结 庐 乌 ，", 20, TEAL, "bold")
    body += text(790, 158, "才 子 各 相 关 ，", 20, TEAL, "bold")
    body += text(790, 190, "龙 儿 好 复 深 。", 20, TEAL, "bold")
    body += text(790, 214, "格式 12/12 合法", 13, GRAY)
    body += box(690, 244, 200, 126, "#ffffff", ORANGE)
    body += text(790, 276, "不加掩码时", 15, ORANGE, "bold")
    body += text(790, 304, "之 看 结 庐 阜 。", 19, INK)
    body += text(790, 334, "格式 0/12 合法", 13, GRAY)
    body += arrow(594, 200, 686, 160, TEAL)
    body += arrow(594, 320, 686, 300, ORANGE)
    body += text(480, 436, "掩码只保证格式合法，不改变模型对内容的判断：右边两首都不通顺，但下面那首连句数、字数都不对。", 14.5, GRAY)
    body += text(480, 462, "每步的代价是一次 2048 维赋值；把它写进有限状态机或文法，就能约束 JSON、正则这类更复杂的格式。", 14.5, GRAY)
    svg("guided-decoding.svg", "约束解码如何把不合法的 token 排除掉",
        "左：模型对整张 2048 个 token 的词表给出打分。中：五言模板只允许 1310 个单字 token；句末位置只允许两个标点。"
        "其余位置被打分 −∞，softmax 后概率为 0。右：同一批请求，加掩码的 12 首全部符合四句五言，不加掩码的一首都不符合。"
        "掩码保证格式，不保证内容。", 486, body)


# ---------- 第 28 章：推理效率 ----------

def _fmt_bytes(n):
    for unit, size in (("GiB", 2 ** 30), ("MiB", 2 ** 20), ("KiB", 2 ** 10)):
        if n >= size:
            return f"{n / size:.2f} {unit}" if unit != "KiB" else f"{n / size:.0f} KiB"
    return f"{n} B"


def kv_cache_size():
    d = load("tinyllm-inference-efficiency.json")
    tiny = {int(k): v for k, v in d["cache_bytes"]["tiny"].items()}
    llama = {int(k): v for k, v in d["cache_bytes"]["llama8b"].items()}
    m = d["model"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), layout="constrained", gridspec_kw={"width_ratios": [1.5, 1]})
    xs = np.array(sorted(tiny))
    ax.plot(xs, [tiny[k] / 2 ** 20 for k in xs], color=BLUE, lw=2.6, marker="o", ms=5,
            label=f"TinyLLM（{m['layers']} 层，{m['kv_heads']} 个 KV 头，FP16）")
    xs2 = np.array(sorted(llama))
    ax.plot(xs2, [llama[k] / 2 ** 30 * 1024 for k in xs2], color=ORANGE, lw=2.6, marker="s", ms=5,
            label="Llama 3 8B（32 层，8 个 KV 头，FP16）")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log", base=2)
    ax.set_xlabel("上下文长度（token）")
    ax.set_ylabel("单条请求的 KV cache（MiB）")
    ax.grid(alpha=0.25, which="both")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    for k in (1024, 8192):
        v = llama[k] / 2 ** 30
        ax.annotate(f"{k} 个 token → {v:.1f} GiB", xy=(k, v * 1024), xytext=(k * 0.9, v * 1024 * 1.9),
                    fontsize=10.5, color=ORANGE, ha="center",
                    arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.2))
    ax.set_title("缓存随 token 数线性增长", fontsize=13)

    weights, total = 16, 80
    ax2.bar([0], [weights], color=GRAY, width=0.55, label="权重（FP16 约 16 GiB）")
    ax2.bar([0], [total - weights], bottom=[weights], color=ORANGE, width=0.55, label="留给 KV cache 与运行时")
    n_seq = int((total - weights) * 2 ** 30 // (llama[8192]))
    ax2.text(0, weights / 2, f"{weights} GiB", ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    ax2.text(0, weights + (total - weights) / 2, f"{total - weights} GiB\n≈ {n_seq} 条 8K 序列", ha="center",
             va="center", color="white", fontsize=12, fontweight="bold")
    ax2.set_xticks([], [])
    ax2.set_ylabel("一张 80 GiB 卡上的显存（GiB）")
    ax2.set_title("Llama 3 8B 的权重与缓存", fontsize=13)
    ax2.legend(loc="upper right", fontsize=10, framealpha=0.95)
    ax2.grid(alpha=0.2, axis="y")
    save_plot(fig, "kv-cache-size.svg", "KV cache 的大小：随上下文线性增长，大模型上先于权重撑满显存",
              f"左：单条请求的 KV cache 随 token 数线性增长。TinyLLM（4 层、4 个 KV 头、FP16）1024 个 token 只要 2 MiB；"
              f"Llama 3 8B 每个 token 128 KiB，8192 个 token 就要 1 GiB，32768 个 token 4 GiB。"
              f"右：80 GiB 的卡上权重占 16 GiB，剩下的约 64 GiB 只够 {n_seq} 条 8K 序列同时在线——"
              "能同时服务多少用户，往往先卡在缓存而不是权重。")


def latency_metrics():
    d = load("tinyllm-inference-efficiency.json")
    ttft = float(np.median(d["metrics"]["ttft"]))
    tpot = float(np.median(d["tpot_ms"]))
    gaps = [tpot] * 5
    body = text(480, 36, "一次请求的延迟：TTFT、ITL、TPOT、E2EL 各覆盖哪一段", 21, weight="bold")
    x0, y = 90, 120
    pre_w, gap_w = 130, 62
    body += text(x0 + pre_w / 2, y - 16, "prefill", 15, BLUE, "bold")
    body += f'<rect x="{x0}" y="{y}" width="{pre_w}" height="58" rx="8" fill="{SOFT[BLUE]}" stroke="{BLUE}" stroke-width="2.5"/>'
    body += text(x0 + pre_w / 2, y + 36, "一次前向", 14, BLUE)
    for i, g in enumerate(gaps):
        gx = x0 + pre_w + i * gap_w
        body += f'<rect x="{gx}" y="{y}" width="{gap_w - 8}" height="58" rx="6" fill="{SOFT[TEAL]}" stroke="{TEAL}" stroke-width="2"/>'
        body += text(gx + (gap_w - 8) / 2, y + 36, "decode", 12.5, TEAL)
    end_x = x0 + pre_w + len(gaps) * gap_w - 8
    body += f'<line x1="{x0}" y1="{y + 84}" x2="{end_x}" y2="{y + 84}" stroke="{ORANGE}" stroke-width="2.5"/>'
    body += f'<line x1="{x0}" y1="{y + 76}" x2="{x0}" y2="{y + 92}" stroke="{ORANGE}" stroke-width="2.5"/>'
    body += f'<line x1="{end_x}" y1="{y + 76}" x2="{end_x}" y2="{y + 92}" stroke="{ORANGE}" stroke-width="2.5"/>'
    body += text((x0 + end_x) / 2, y + 112, f"E2EL ≈ {round(np.median(d['metrics']['e2e']))} ms（本例 16 个字）", 16, ORANGE, "bold")
    body += f'<line x1="{x0}" y1="{y - 42}" x2="{x0 + pre_w}" y2="{y - 42}" stroke="{RED}" stroke-width="2.5"/>'
    body += f'<line x1="{x0}" y1="{y - 50}" x2="{x0}" y2="{y - 34}" stroke="{RED}" stroke-width="2.5"/>'
    body += f'<line x1="{x0 + pre_w}" y1="{y - 50}" x2="{x0 + pre_w}" y2="{y - 34}" stroke="{RED}" stroke-width="2.5"/>'
    body += text(x0 + pre_w / 2, y - 56, f"TTFT ≈ {ttft:.1f} ms", 15, RED, "bold")
    body += f'<line x1="{x0 + pre_w + 4}" y1="{y + 128}" x2="{x0 + pre_w + gap_w - 12}" y2="{y + 128}" stroke="{TEAL}" stroke-width="2.5"/>'
    body += text(x0 + pre_w + gap_w / 2 + 24, y + 152, f"ITL ≈ {tpot:.1f} ms（相邻两个字之间）", 14, TEAL, anchor="start")
    body += text(480, 316, f"TPOT = (E2EL − TTFT) / (n − 1) ≈ {tpot:.1f} ms；单条请求上平均 ITL 就等于 TPOT，多条请求上两个平均口径不同。", 14.5, GRAY)
    body += text(480, 344, "TTFT 由 prefill 决定，ITL / TPOT 由每一步 decode 决定——优化一个不一定改善另一个，所以三个数要一起报。", 14.5, GRAY)
    body += text(480, 368, "为了画得下，decode 只画了 5 段；实际 16 个字有 15 段 ITL。", 13, GRAY)
    svg("latency-metrics.svg", "延迟指标的时间线：TTFT、ITL、TPOT、E2EL",
        f"请求发出后先做 prefill（红色括号是 TTFT，本例约 {ttft:.1f} ms），之后每生成一个字做一次 decode（浅绿块，块与块之间的间隔是 ITL，约 {tpot:.1f} ms）。"
        f"decode 段的总时间除以生成的字数减一得到 TPOT；从发出请求到最后一个字是 E2EL（橙色括号）。"
        "三个数分别对应不同阶段，只看其中一个会误判。", 380, body)


# ---------- 第 13 章：TinyLLM 在 GPU 上完整实现 ----------

def gpu_step_anatomy():
    """一个训练步在 CPU/GPU 上依次发生什么，圆圈数字标出后面各章要做的优化点（与 gpu-training.md 的表一一对应）。"""
    body = text(480, 38, "GPU 上的一个训练步：本章先跑通，圆圈处是后面要优化的地方", 21, weight="bold")
    body += box(30, 64, 900, 74, "#ffffff", "#e2e8f0") + text(62, 106, "CPU", 17, GRAY, "bold")
    body += box(30, 152, 900, 222, "#ffffff", "#e2e8f0") + text(62, 282, "GPU", 17, GRAY, "bold")
    body += cbox(135, 80, 170, 44, ORANGE) + text(220, 108, "按计划切 batch", 16, ORANGE, "bold")
    body += arrow(220, 124, 220, 170, ORANGE, 2.5)
    body += text(232, 150, "拷到显存", 14, ORANGE, anchor="start")
    gpu = [(100, 172, 240, "前向：嵌入 → Block×L → logits", BLUE, "BF16 autocast · SDPA 注意力"),
           (360, 172, 120, "交叉熵", BLUE, "损失 ÷ accum"),
           (500, 172, 170, "反向：求梯度", TEAL, "梯度累加到 .grad"),
           (690, 172, 220, "裁剪 → AdamW 更新", PURPLE, "fused 内核 · 学习率调度")]
    for x, y, w, label, color, sub in gpu:
        body += cbox(x, y, w, 70, color) + text(x + w / 2, y + 30, label, 15, color, "bold") + text(x + w / 2, y + 54, sub, 13, GRAY)
    body += arrow(340, 207, 358, 207) + arrow(480, 207, 498, 207) + arrow(670, 207, 688, 207)
    body += path("M585 242 V276 H220 V246", GRAY, 2, True)
    body += text(400, 296, "重复 accum 次（梯度累积）再更新一次", 14, GRAY)
    body += path("M800 242 V340 H95 V102 H131", GRAY, 2, True)
    body += text(470, 362, "下一步：loss.item() 记录日志时，CPU 要等 GPU 算完", 14, GRAY)
    marks = [(220, 72, "①"), (206, 150, "②"), (110, 168, "③"), (330, 168, "④"), (660, 168, "⑤"), (900, 168, "⑥"), (800, 312, "⑦")]
    for x, y, m in marks:
        body += circle(x, y, 14, "#fef2f2", RED) + text(x, y + 6, m, 17, RED, "bold")
    legend = ["① 数据：多进程预取、锁页内存、异步拷贝", "② 拷贝：整条 token 流常驻显存，省掉每步拷贝",
              "③ 注意力：SDPA 选 FlashAttention 内核", "④ 编译：torch.compile 融合逐元素小算子",
              "⑤ 显存：激活重计算，换更大的 batch", "⑥ 优化器：fused AdamW（本章已开）",
              "⑦ 同步：日志每 N 步取一次，少让 CPU 等"]
    for i, t in enumerate(legend):
        body += text(60 + (i % 2) * 450, 412 + (i // 2) * 28, t, 14.5, INK, anchor="start")
    svg("gpu-step-anatomy.svg", "GPU 上一个训练步的流程与优化点",
        "CPU 按计划切出 batch 拷到显存；GPU 上依次做 BF16 前向、交叉熵、反向求梯度，重复 accum 次后裁剪梯度并用 AdamW 更新。"
        "七个红色圆圈标出优化点：数据预取、减少拷贝、FlashAttention 内核、torch.compile 算子融合、激活重计算、融合优化器、减少 CPU 与 GPU 的同步。", 520, body)


# ---------- 第 14 章：语料与数据管线 ----------

def _pipeline_log():
    src = DATA / "tinyllm-data-pipeline-log.json"
    if not src.exists():
        print("skip data-pipeline figures: run scripts/build-tinyllm-code.py data-pipeline to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def data_pipeline_funnel():
    """原始样本走过清洗、繁转简、去重、划分，每一步还剩多少（数字来自 data-pipeline.py）。"""
    log = _pipeline_log()
    if log is None:
        return
    stages = log["funnel"]
    notes = {"正文非空": "空记录", "没有缺字和校勘记号": "含 □ 或 [ ]", "只含常用汉字和，。": "生僻字、？！《》等",
             "五言绝句或律诗": "七言、长篇、杂言", "繁转简后精确去重": "正文完全相同", "近重复去重": "重合度 ≥ 0.5"}
    sections = {"没有缺字和校勘记号": "§2 清洗", "繁转简后精确去重": "§3 去重"}
    body = text(480, 38, f"{stages[0][1]:,} 条原始记录，一步步走到训练集", 21, weight="bold")
    x0, wmax, top, row = 270, 470, 70, 50
    total = stages[0][1]
    for i, (name, n) in enumerate(stages):
        y = top + i * row
        color = TEAL if i >= 5 else BLUE
        w = max(4, wmax * n / total)
        body += text(x0 - 14, y + 26, name, 15, anchor="end")
        body += f'<rect x="{x0 + (wmax - w) / 2:.1f}" y="{y + 6}" width="{w:.1f}" height="28" rx="5" fill="{color}" opacity="0.85"/>'
        body += text(x0 + wmax / 2, y + 26, f"{n:,}", 15, "#ffffff" if w > 60 else INK, "bold")
        if i:
            drop = stages[i - 1][1] - n
            label = f"−{drop}：{notes[name]}" if drop else f"−0：{notes[name]}"
            body += text(x0 + wmax + 16, y + 26, label, 13.5, GRAY, anchor="start")
        if name in sections:
            body += text(36, y + 26, sections[name], 13, ORANGE, "bold", anchor="start")
    # 划分：一条堆叠条
    y = top + len(stages) * row + 14
    sp = log["split"]
    n = sum(sp.values())
    body += text(36, y + 26, "§4 划分", 13, ORANGE, "bold", anchor="start")
    body += text(x0 - 14, y + 26, "按正文哈希划分", 15, anchor="end")
    w_all = wmax * n / total
    x = x0 + (wmax - w_all) / 2
    for key, color, label in (("train", BLUE, "训练"), ("val", RED, "验证"), ("test", PURPLE, "测试")):
        w = w_all * sp[key] / n
        body += f'<rect x="{x:.1f}" y="{y + 6}" width="{w:.1f}" height="28" fill="{color}" opacity="0.85"/>'
        x += w
    body += text(x0 + wmax + 16, y + 26, f"训练 {sp['train']} · 验证 {sp['val']} · 测试 {sp['test']}", 13.5, GRAY, anchor="start")
    y += 64
    chips = ["§5 泄漏检查", "§7 拼成 token 流", "§8 切成 batch", "第 12 章的训练循环"]
    cx = 120
    for k, chip in enumerate(chips):
        body += cbox(cx, y, 160, 38, TEAL if k < 3 else GRAY) + text(cx + 80, y + 25, chip, 14.5, TEAL if k < 3 else GRAY, "bold")
        if k < 3:
            body += arrow(cx + 162, y + 19, cx + 196, y + 19, TEAL, 2.5)
        cx += 200
    svg("data-pipeline-funnel.svg", "从原始记录到训练集的数据管线",
        f"{total:,} 条《全唐诗》原始记录依次经过：正文非空、去掉含缺字或校勘记号的、只留常用汉字和逗号句号，剩 {stages[3][1]:,} 条；"
        f"只留五言绝句和律诗后剩 {stages[4][1]} 首；繁转简后去掉完全相同的剩 {stages[5][1]} 首，再去掉近重复剩 {stages[6][1]} 首；"
        f"按正文哈希划分为训练 {sp['train']}、验证 {sp['val']}、测试 {sp['test']}。之后是泄漏检查、拼成 token 流、切成 batch。",
        y + 62, body)


def data_pipeline_near_dup():
    """“和最像的那首”的重合度分布：样本内部（去重用）和统一语料验证集对训练集（泄漏检查）。"""
    log = _pipeline_log()
    if log is None:
        return
    bins = np.linspace(0, 1, 21)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained", sharey=True)
    for ax, scores, title, color in (
            (axes[0], log["best_scores"], f"原始样本：每首诗和前面最像的那首（{len(log['best_scores'])} 首）", BLUE),
            (axes[1], log["val_scores"], f"统一语料：每首验证诗和训练集里最像的那首（{log['val_total']} 首）", TEAL)):
        scores = np.array(scores)
        ax.hist(scores[scores < 0.5], bins=bins, color=color, alpha=0.85, label="保留：不同的诗")
        ax.hist(scores[scores >= 0.5], bins=bins, color=RED, alpha=0.85, label=f"重合度 ≥ 0.5：{int((scores >= 0.5).sum())} 首")
        ax.axvline(0.5, color=ORANGE, ls="--", lw=1.6)
        ax.set_yscale("log")
        ax.set_title(title, fontsize=12.5)
        ax.set_xlabel("重合度（共有的字二元组 ÷ 较短那首的二元组数）")
        ax.legend(fontsize=11, loc="upper center")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("诗的首数（对数刻度）")
    axes[0].text(0.52, 60, "阈值 0.5", color=ORANGE, fontsize=12)
    save_plot(fig, "data-pipeline-near-dup.svg", "近重复的重合度分布",
              "左：原始样本里每首诗和它前面最像的一首的重合度，绝大多数在 0.2 以下，另有一小簇在 0.7 到 1.0 之间，中间几乎是空的，阈值 0.5 落在空档里。"
              f"右：统一语料 {log['val_total']} 首验证诗和训练集里最像的一首的重合度，同样是双峰，有 {log['leak_hits']} 首在 0.5 以上，是漏网的近重复。")


def data_pipeline_leak():
    """小训练集上三个评估集的损失：训练集、干净验证、近亲验证（3 个种子的平均与范围）。"""
    log = _pipeline_log()
    if log is None:
        return
    curves = log["leak_curves"]
    every = log["leak_every"]
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    styles = {"训练集": (BLUE, "训练集（模型在背的那 300 多首）"), "干净验证": (TEAL, "干净验证：和训练集毫无重合的 200 首"),
              "近亲验证": (RED, f"近亲验证：在训练集里有近重复的 {log['leak_hits']} 首")}
    for name, (color, label) in styles.items():
        runs = np.array([curves[s][name] for s in curves])
        x = np.arange(runs.shape[1]) * every
        ax.fill_between(x, runs.min(0), runs.max(0), color=color, alpha=0.18, lw=0)
        ax.plot(x, runs.mean(0), color=color, lw=2.4, marker="o", ms=3.5, label=label)
    clean = np.array([curves[s]["干净验证"] for s in curves]).mean(0)
    best = int(np.argmin(clean))
    ax.annotate(f"干净验证最低 {clean[best]:.2f}（第 {best * every} 步）\n之后模型开始背诗", xy=(best * every, clean[best]),
                xytext=(best * every + 15, clean[best] + 1.75), color=TEAL, fontsize=12, arrowprops=dict(arrowstyle="->", color=TEAL, lw=1.4))
    dup = np.array([curves[s]["近亲验证"] for s in curves]).mean(0)
    ax.annotate(f"近亲验证一路降到 {dup[-1]:.2f}：\n看起来“学会了”，其实是背过了", xy=(len(dup) * every - every, dup[-1]),
                xytext=(len(dup) * every - 120, dup[-1] - 1.6), color=RED, fontsize=12, arrowprops=dict(arrowstyle="->", color=RED, lw=1.4))
    ax.set_xlabel("训练步数（每步 16 段 × 64 个 token）")
    ax.set_ylabel("交叉熵（nats / token）")
    ax.set_ylim(0, 10)
    ax.legend(loc="lower left", fontsize=11, framealpha=0.95)
    ax.grid(alpha=0.25)
    save_plot(fig, "data-pipeline-leak.svg", "泄漏实验：干净验证与近亲验证的损失",
              f"训练集损失一路降到约 {np.array([curves[s]['训练集'] for s in curves]).mean(0)[-1]:.2f}；干净验证在第 {best * every} 步左右见底（{clean[best]:.2f}）后回升到 {clean[-1]:.2f}，"
              f"近亲验证却跟着训练集一路下降到 {dup[-1]:.2f}。阴影是 3 个种子的范围，很窄。")


def data_pipeline_packing():
    """三种组 batch 的办法：逐首补齐、按长度分桶、拼接成流（长度取自训练集前几首诗的真实 token 数）。"""
    log = _pipeline_log()
    if log is None:
        return
    lengths = log["lengths"]
    at = 384                                                   # 训练集第 385～392 首：随手取的一段，绝句、律诗都有
    sample = lengths[at:at + 8]
    u = 6                                                      # 每个 token 画多宽
    body = text(480, 36, "三种组 batch 的办法：灰色是浪费的 <pad>，红框是跨过诗边界的窗口", 21, weight="bold")

    def rows(x0, y0, lens, title, waste, color):
        out = text(x0, y0, title, 16, color, "bold", anchor="start")
        out += text(x0, y0 + 22, f"整个训练集 32 首一批统计：{waste:.1%} 的位置是 <pad>", 13.5, GRAY, anchor="start")
        for b, group in enumerate(lens):
            m = max(group)
            for r, n in enumerate(group):
                y = y0 + 36 + b * (len(group) * 16 + 14) + r * 16
                out += f'<rect x="{x0}" y="{y}" width="{n * u}" height="12" rx="2" fill="{color}" opacity="0.8"/>'
                if m > n:
                    out += f'<rect x="{x0 + n * u}" y="{y}" width="{(m - n) * u}" height="12" rx="2" fill="#cbd5e1"/>'
        return out

    random_groups = [sample[:4], sample[4:8]]
    sorted_groups = [sorted(sample)[:4], sorted(sample)[4:]]
    body += rows(40, 80, random_groups, "① 逐首补齐（按原顺序 4 首一批）", log["padding"]["random"], BLUE)
    body += rows(510, 80, sorted_groups, "② 按长度分桶（先排序再分批）", log["padding"]["bucket"], TEAL)
    # ③ 拼接成流
    y = 300
    body += text(40, y, "③ 拼接成流（第 12 章）：首尾相接，每首后面一个 <eos>，再切成等长窗口", 16, ORANGE, "bold", anchor="start")
    x, unit = 40, 3.2
    colors = [ORANGE, "#d97706"]
    y += 18
    stream = lengths[at:at + 9]
    for i, n in enumerate(stream):
        w = n * unit
        if x + w > 920:
            break
        body += f'<rect x="{x:.1f}" y="{y}" width="{w - unit:.1f}" height="20" fill="{colors[i % 2]}" opacity="0.75"/>'
        body += f'<rect x="{x + w - unit:.1f}" y="{y}" width="{unit:.1f}" height="20" fill="{INK}"/>'
        x += w
    end = x
    for k, s in enumerate((10, 70, 135, 190)):
        wx = 40 + s * unit
        if wx + 64 * unit > end:
            break
        yy = y + 30 + k * 18
        body += f'<rect x="{wx:.1f}" y="{yy}" width="{64 * unit:.1f}" height="12" rx="3" fill="none" stroke="{RED}" stroke-width="2"/>'
    body += text(40, y + 118, "黑色细条是 <eos>。每个红框是一个 64-token 窗口，大多横跨两首诗：", 14, GRAY, anchor="start")
    body += text(40, y + 140, "没有一个空位，但第 12 章的 batch 计划里 66% 的预测位置能“看到”上一首诗；想隔开就用文档掩码（§7）。", 14, GRAY, anchor="start")
    svg("data-pipeline-packing.svg", "三种组 batch 的办法",
        f"逐首补齐：每批按最长那首补齐，全训练集 32 首一批时 {log['padding']['random']:.1%} 的位置是 <pad>；"
        f"按长度分桶：长度相近的放一批，浪费降到 {log['padding']['bucket']:.1%}；"
        "拼接成流：所有诗首尾相接、用 <eos> 隔开，切成等长窗口，没有空位，但窗口会横跨两首诗。", y + 160, body)


def data_pipeline_coverage():
    """第 12 章的随机起点 vs 按轮打乱：训练流里每个 token 被当作预测目标的次数。"""
    log = _pipeline_log()
    if log is None:
        return
    cov = log["coverage"]
    keys = [str(k) for k in range(7)]
    labels = ["0", "1", "2", "3", "4", "5", "≥6"]
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    x = np.arange(len(keys))
    for off, name, color, label in ((-0.2, "random", BLUE, "随机起点（第 12 章）"), (0.2, "epoch", TEAL, "按轮打乱")):
        counts = np.array([cov[name].get(k, 0) for k in keys], dtype=float)
        share = counts / counts.sum()
        ax.bar(x + off, share * 100, width=0.4, color=color, alpha=0.85, label=label)
        for xi, v in zip(x + off, share):
            if v > 0.005:
                ax.text(xi, v * 100 + 1, f"{v:.0%}", ha="center", fontsize=11, color=color)
    ax.set_xticks(x, labels)
    ax.set_xlabel(f"训练流里一个 token 被当作预测目标的次数（300 步 × 32 个窗口 ≈ {cov['epochs']:.2f} 遍）")
    ax.set_ylabel("占训练流的百分比")
    ax.set_ylim(0, 82)
    ax.legend(fontsize=11)
    ax.grid(alpha=0.25, axis="y")
    total_r = sum(cov["random"].values())
    save_plot(fig, "data-pipeline-coverage.svg", "随机起点与按轮打乱的覆盖次数",
              f"同样 {cov['epochs']:.2f} 遍的预算：随机起点下 {cov['random']['0'] / total_r:.1%} 的 token 一次也没被当作目标，"
              "另有一部分被用了 6 次以上；按轮打乱时几乎每个 token 都恰好用了 2 次或 3 次。")


# ---------- 第 15 章：语言模型目标函数 ----------

def _loss_log():
    src = DATA / "tinyllm-language-model-loss.json"
    if not src.exists():
        print("skip language-model-loss figures: run scripts/build-tinyllm-code.py language-model-loss to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def lm_loss_poem():
    """一首验证诗逐字的 -log p：标点几乎为 0，句首最难（数字来自 language-model-loss.py）。"""
    log = _loss_log()
    if log is None:
        return
    chars = log["chars"]
    labels = [t for t, _ in chars]
    vals = np.array([v for _, v in chars])
    colors = []
    prev = "<eos>"
    for t, _ in chars:
        if t in ("，", "。"):
            colors.append(TEAL)
        elif t == "<eos>":
            colors.append(GRAY)
        elif prev in ("，", "。", "<eos>"):
            colors.append(ORANGE)
        else:
            colors.append(BLUE)
        prev = t
    fig, ax = plt.subplots(figsize=(11, 4.4), layout="constrained")
    ax.bar(np.arange(len(vals)), np.maximum(vals, 0.12), color=colors, width=0.78)   # 接近 0 的柱子留一条细线，看得见
    ax.set_xticks(np.arange(len(vals)), labels, fontsize=10.5)
    ax.set_xlim(-0.7, len(vals) - 0.3)
    ax.text(len(vals) - 0.5, 13.0, f"全诗合计 {vals.sum():.1f} nats；48 个 token，平均每个 {vals.sum() / 48:.2f}", color=RED, fontsize=12, ha="right")
    ax.set_ylabel("−ln p(正确答案)（nats）")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=ORANGE, label="句首的字"), Patch(color=BLUE, label="句中的字"),
                       Patch(color=TEAL, label="标点"), Patch(color=GRAY, label="<eos>")],
              loc="upper center", ncol=4, fontsize=11, framealpha=0.95, bbox_to_anchor=(0.5, 1.13))
    ax.set_ylim(0, 13.8)
    ax.grid(alpha=0.25, axis="y")
    save_plot(fig, "lm-loss-poem.svg", "一首验证诗逐字的损失",
              f"第一首验证诗“{log['poem'][:5]}……”的 {len(vals)} 个字（含结束符），每根柱子是模型给正确的字打的 −ln p；"
              f"逗号、句号和结束符几乎是 0，字都在 4 到 10 之间，句首的字普遍更高；全诗合计 {vals.sum():.1f} nats。")


def lm_loss_units():
    """同一个验证损失的几种读法：nats、比特、每字比特、困惑度。"""
    log = _loss_log()
    if log is None:
        return
    u = log["units"]
    nats, per_char, V = u["nats"], u["per_char"], u["vocab"]
    bits = nats / np.log(2)
    bpc = per_char / np.log(2)
    body = text(480, 38, f"一个数，四种读法：第 12 章基线的验证损失 {nats:.3f}", 21, weight="bold")
    body += cbox(340, 70, 280, 74, BLUE) + text(480, 102, f"{nats:.3f} nats / token", 22, BLUE, "bold")
    body += text(480, 128, f"{u['tokens']:,} 道题的 −ln p 取平均", 14, GRAY)
    items = [
        (40, ORANGE, f"{bits:.2f} 比特 / token", "÷ ln 2：换成以 2 为底", "每个 token 平均要几个“是/否”问题"),
        (360, TEAL, f"困惑度 {np.exp(nats):.0f}", f"e^{nats:.3f}", f"像在 {np.exp(nats):.0f} 个候选里均匀乱猜"),
        (680, PURPLE, f"{bpc:.2f} 比特 / 字", "× 每字 0.954 个 token，再 ÷ ln 2", "换了分词器也能比较"),
    ]
    for x, color, head, how, mean in items:
        body += arrow(480, 146, x + 120, 214, color, 2.5)
        body += cbox(x, 218, 240, 96, color) + text(x + 120, 252, head, 19, color, "bold")
        body += text(x + 120, 278, how, 13.5, GRAY) + text(x + 120, 300, mean, 13.5, INK)
    body += box(40, 342, 880, 64, "#ffffff", "#e2e8f0")
    body += text(480, 368, f"对照：均匀乱猜 {V} 个 token 是 ln {V} = {np.log(V):.3f} nats，困惑度 {V}；完美预测是 0 nats，困惑度 1", 15, INK)
    body += text(480, 392, f"困惑度是“正确答案概率”的几何平均的倒数：几何平均 {np.exp(-nats):.4f}，算术平均却有 0.18", 14, GRAY)
    svg("lm-loss-units.svg", "验证损失的几种读法",
        f"{nats:.3f} nats/token 除以 ln2 是 {bits:.2f} 比特/token；取 e 的指数是困惑度 {np.exp(nats):.0f}，相当于在 {np.exp(nats):.0f} 个候选里均匀乱猜；"
        f"乘以每字的 token 数再除以 ln2 是 {bpc:.2f} 比特/字。对照：均匀乱猜 {V} 个 token 的损失是 {np.log(V):.3f}。", 430, body)


def lm_loss_breakdown():
    """四类题目：占题目的比例 vs 占总损失的比例。"""
    log = _loss_log()
    if log is None:
        return
    rows = log["breakdown"]
    colors = [TEAL, GRAY, ORANGE, BLUE]
    fig, ax = plt.subplots(figsize=(10, 3.4), layout="constrained")
    for y, idx, title in ((1, 1, "占题目的比例"), (0, 3, "占总损失的比例")):
        left = 0.0
        for (name, share, mean, lshare), color in zip(rows, colors):
            v = share if idx == 1 else lshare
            ax.barh(y, v * 100, left=left * 100, color=color, height=0.55, label=f"{name}（平均 {mean:.2f}）" if y == 1 else None)
            if v > 0.06:
                ax.text((left + v / 2) * 100, y, f"{v:.0%}", ha="center", va="center", color="white", fontsize=12, fontweight="bold")
            left += v
    ax.set_yticks([0, 1], ["占总损失", "占题目数"])
    ax.set_xlim(0, 100)
    ax.set_xlabel("百分比")
    ax.legend(loc="upper center", ncol=4, fontsize=11, bbox_to_anchor=(0.5, 1.32), framealpha=0.95)
    save_plot(fig, "lm-loss-breakdown.svg", "四类题目占题目数与占总损失的比例",
              f"标点占题目的 {rows[0][1]:.0%}，却只占总损失的 {rows[0][3]:.1%}；句首的字占题目的 {rows[2][1]:.0%}、占损失的 {rows[2][3]:.0%}；"
              f"句中的字占题目的 {rows[3][1]:.0%}、占损失的 {rows[3][3]:.0%}。平均损失主要由“字”决定。")


def lm_loss_calibration():
    """可靠性图：模型最有把握的答案的概率 vs 实际猜中的比例。"""
    log = _loss_log()
    if log is None:
        return
    rows = np.array(log["calibration"])                      # lo, n, conf, acc
    fig, ax = plt.subplots(figsize=(7.2, 5.4), layout="constrained")
    ax.plot([0, 1], [0, 1], color=GRAY, ls="--", lw=1.4, label="完美校准：说多少就中多少")
    sizes = 30 + 220 * np.sqrt(rows[:, 1] / rows[:, 1].max())
    ax.scatter(rows[:, 2], rows[:, 3], s=sizes, color=BLUE, alpha=0.85, zorder=3, label="基线模型（点越大，题越多）")
    ax.plot(rows[:, 2], rows[:, 3], color=BLUE, lw=1.6, alpha=0.6)
    for lo, n, c, a in rows:
        ax.annotate(f"{int(n)}", (c, a), textcoords="offset points", xytext=(8, -14), fontsize=10, color=GRAY)
    mid = rows[5]
    ax.annotate(f"说 {mid[2]:.2f}，只中 {mid[3]:.2f}", (mid[2], mid[3]), xytext=(0.55, 0.12), color=RED, fontsize=12,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.3))
    ax.set_xlabel("模型对最有把握的那个答案给的概率（分组平均）")
    ax.set_ylabel("实际猜中的比例")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(alpha=0.25)
    save_plot(fig, "lm-loss-calibration.svg", "基线模型的可靠性图",
              f"两端贴着对角线：把握不到 0.1 的九千多道题和把握 0.9 以上的两千道题（多是标点）都很准；中间几组落在对角线下方，"
              f"例如平均把握 {mid[2]:.2f} 的一组只猜中 {mid[3]:.2f}，模型在这些题上过于自信。按题数加权的平均偏差 {log['ece']:.3f}。")


def lm_loss_denominator():
    """梯度累积时分母放在哪：各自平均再平均 vs 各自求和再除总数（真题数来自 language-model-loss.py）。"""
    log = _loss_log()
    if log is None:
        return
    acc = log["accumulation"][1]
    counts, weights = acc["counts"], acc["weights"]
    total = sum(counts)
    body = text(480, 38, f"同样 8 首诗、{total} 道真题，分成 4 个 micro-batch 累积梯度：分母放在哪？", 20, weight="bold")
    x0, unit = 60, 3.2
    for i, c in enumerate(counts):
        y = 76 + i * 44
        body += text(x0, y + 22, f"micro-batch {i + 1}", 14, GRAY, anchor="start")
        body += f'<rect x="{x0 + 110}" y="{y + 6}" width="{c * unit:.1f}" height="24" rx="4" fill="{BLUE}" opacity="0.8"/>'
        body += text(x0 + 118 + c * unit, y + 24, f"{c} 道", 14, INK, anchor="start")
    # 右侧两种做法
    rx = 560
    body += cbox(rx, 70, 370, 92, RED) + text(rx + 185, 98, "有偏：各自平均，再除以 4", 17, RED, "bold")
    body += text(rx + 185, 122, "每道题的权重 = 1 ÷ (4 × 本组题数)", 14, INK)
    body += text(rx + 185, 146, "权重是一起算时的 " + " / ".join(f"{w:.2f}" for w in weights) + " 倍", 13.5, GRAY)
    body += cbox(rx, 176, 370, 92, TEAL) + text(rx + 185, 204, "正确：各自求和，最后除以总题数", 17, TEAL, "bold")
    body += text(rx + 185, 228, f"每道题的权重 = 1 ÷ {total}", 14, INK)
    body += text(rx + 185, 252, "和 8 首一起算的梯度完全相同", 13.5, GRAY)
    body += box(40, 286, 880, 60, "#ffffff", "#e2e8f0")
    body += text(480, 312, f"按长度排序后分组，短诗那两组的题被放大到 {max(weights):.2f} 倍，长诗那两组缩到 {min(weights):.2f} 倍；", 15, INK)
    body += text(480, 334, f"梯度方向和一起算时的余弦相似度只有 {acc['cos']:.3f}。题数相同的分组（原顺序）就没有这个问题。", 15, INK)
    svg("lm-loss-denominator.svg", "梯度累积时分母放在哪",
        f"8 首诗按长度排序后分成 4 个 micro-batch，真题数分别为 {', '.join(map(str, counts))}。各自平均再除以 4 时，"
        f"短诗组每道题的权重放大到 {max(weights):.2f} 倍，长诗组缩小到 {min(weights):.2f} 倍，梯度方向的余弦相似度只有 {acc['cos']:.3f}；"
        f"各自求和、最后除以总题数 {total}，结果和一起算完全相同。", 366, body)


# ---------- 第 17 章：学习率策略 ----------

def _lr_log():
    src = DATA / "tinyllm-learning-rate-log.json"
    if not src.exists():
        print("skip learning-rate figures: run scripts/build-tinyllm-code.py learning-rate to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def lr_schedules():
    """四种调度的形状（峰值 1e-2，数字来自 learning-rate.py）。"""
    log = _lr_log()
    if log is None:
        return
    styles = {"固定": (GRAY, "--"), "warmup+余弦": (BLUE, "-"), "WSD": (RED, "-"), "warmup+线性": (TEAL, "-")}
    fig, ax = plt.subplots(figsize=(10, 4.0), layout="constrained")
    for name, ys in log["schedules"].items():
        color, ls = styles[name]
        ax.plot(np.arange(len(ys)), np.array(ys) * 1e3, color=color, ls=ls, lw=2.4, label=name)
    steps = log["steps"]
    ax.axvspan(0, 30, color=ORANGE, alpha=0.08)
    ax.text(15, 10.6, "warmup\n30 步", ha="center", color=ORANGE, fontsize=11)
    ax.axvspan(steps * 0.8, steps, color=RED, alpha=0.06)
    ax.text(steps * 0.9, 10.6, "WSD 的\n衰减段", ha="center", color=RED, fontsize=11)
    ax.set_xlabel("优化器步数")
    ax.set_ylabel("学习率（×0.001）")
    ax.set_ylim(0, 12)
    ax.set_xlim(0, steps)
    ax.legend(loc="lower left", fontsize=11, ncol=2)
    ax.grid(alpha=0.25)
    save_plot(fig, "lr-schedules.svg", "四种学习率调度的形状",
              f"峰值都是 1e-2、共 {steps} 步：固定学习率是一条水平线；另外三种都先用 30 步从接近 0 线性升到峰值；"
              "余弦随后平滑降到峰值的 10%，线性一路降到 0，WSD 保持峰值直到最后 20% 的步数才线性降到 0。")


def lr_compare():
    """左：固定学习率扫描（单种子）；右：各调度 3 个种子的平均与范围。"""
    log = _lr_log()
    if log is None:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.3), layout="constrained", gridspec_kw={"width_ratios": [1, 1.5]})
    lrs = list(log["sweep"])
    vals = [log["sweep"][k] for k in lrs]
    xs = [float(k) for k in lrs]
    a1.plot(xs, vals, color=GRAY, marker="o", ms=8, lw=2)
    for x, v in zip(xs, vals):
        a1.annotate(f"{v:.3f}", (x, v), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=11)
    a1.set_xscale("log")
    a1.set_xticks(xs, ["1e-3", "3e-3", "1e-2"])
    a1.set_xlabel("固定学习率")
    a1.set_ylabel("最终验证损失")
    a1.set_title("固定学习率：太小太大都不好（单种子）", fontsize=12.5)
    a1.set_ylim(min(vals) - 0.1, max(vals) + 0.15)
    a1.set_xlim(7e-4, 1.4e-2)
    a1.grid(alpha=0.25)
    rows = list(log["summary"].items())
    colors = [GRAY, BLUE, BLUE, RED, ORANGE]
    for i, ((name, finals), color) in enumerate(zip(rows, colors)):
        m = sum(finals) / 3
        a2.plot([min(finals), max(finals)], [i, i], color=color, lw=6, alpha=0.35, solid_capstyle="round")
        a2.scatter(finals, [i] * 3, color=color, s=22, zorder=3)
        a2.scatter([m], [i], color=color, s=90, marker="D", zorder=4)
        a2.text(max(finals) + 0.012, i, f"{m:.3f}", va="center", fontsize=11, color=color)
    a2.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=11)
    a2.invert_yaxis()
    a2.axvline(sum(rows[0][1]) / 3, color=GRAY, ls="--", lw=1.2)
    a2.set_xlabel("最终验证损失（3 个种子；菱形是平均，横条是范围）")
    a2.set_title("调度对照：衰减要配更高的峰值", fontsize=12.5)
    a2.set_xlim(4.7, 5.08)
    a2.grid(alpha=0.25, axis="x")
    save_plot(fig, "lr-compare.svg", "固定学习率扫描与调度对照",
              "左：固定学习率 1e-3、3e-3、1e-2 各训练一次，3e-3 最好，两边都更差。右：每种设置 3 个种子。"
              f"在 3e-3 上加 warmup+余弦反而更差（{sum(rows[1][1]) / 3:.3f}）；峰值提到 1e-2 后余弦追平固定 3e-3（{sum(rows[2][1]) / 3:.3f} 对 {sum(rows[0][1]) / 3:.3f}），"
              f"WSD 最好（{sum(rows[3][1]) / 3:.3f}），去掉 warmup 的 WSD 变差（{sum(rows[4][1]) / 3:.3f}）。")


def lr_curves():
    """种子 0 的验证损失曲线，下方是对应的学习率：WSD 在衰减段“下台阶”。"""
    log = _lr_log()
    if log is None:
        return
    c = log["curves"]
    sched = log["schedules"]
    picks = [("固定 3e-3", "constant|3e-03|0", GRAY, None), ("warmup+余弦，峰值 1e-2", "cosine|1e-02|0", BLUE, "warmup+余弦"),
             ("WSD，峰值 1e-2", "wsd|1e-02|0", RED, "WSD")]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.6), layout="constrained", sharex=True, gridspec_kw={"height_ratios": [2.3, 1]})
    steps = log["steps"]
    for label, key, color, sname in picks:
        a1.plot(c[key]["val_step"], c[key]["val"], color=color, lw=2.4, marker="o", ms=4.5, label=label)
        lr = np.full(steps, 3e-3) if sname is None else np.array(sched[sname])
        a2.plot(np.arange(steps), lr * 1e3, color=color, lw=2.2)
    w = c["wsd|1e-02|0"]
    a1.annotate(f"衰减段：{w['val'][-3]:.2f} → {w['val'][-1]:.2f}", xy=(w["val_step"][-1], w["val"][-1]),
                xytext=(w["val_step"][-1] - 120, w["val"][-1] - 0.17), color=RED, fontsize=12,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.3))
    a1.set_ylabel("验证损失（种子 0）")
    a1.set_ylim(4.5, 6.2)
    a1.legend(fontsize=11, loc="upper right")
    a1.grid(alpha=0.25)
    a1.axvspan(steps * 0.8, steps, color=RED, alpha=0.06)
    a2.axvspan(steps * 0.8, steps, color=RED, alpha=0.06)
    a2.set_ylabel("学习率（×0.001）")
    a2.set_xlabel("优化器步数")
    a2.set_ylim(0, 11)
    a2.grid(alpha=0.25)
    save_plot(fig, "lr-curves.svg", "三种设置的验证损失曲线与学习率",
              f"上：种子 0 的验证损失，每 30 步一次。WSD 在峰值 1e-2 保持时和余弦差不多，进入最后 20% 的衰减段后从 {w['val'][-3]:.2f} 降到 {w['val'][-1]:.2f}，"
              "一下拉开差距；固定 3e-3 一直平稳下降。下：对应的学习率。")


def lr_warmup():
    """WSD 峰值 1e-2，有无 warmup 的训练损失（3 个种子平均，滑动平均）。"""
    log = _lr_log()
    if log is None:
        return
    c = log["curves"]
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    k = 9
    for label, kind, color in (("有 warmup（30 步）", "wsd", RED), ("无 warmup（第 1 步就用满 1e-2）", "wsd-no-warmup", ORANGE)):
        runs = np.array([c[f"{kind}|1e-02|{s}"]["train"] for s in range(3)]).mean(0)
        smooth = np.convolve(runs, np.ones(k) / k, mode="valid")
        ax.plot(np.arange(len(smooth)) + k // 2, smooth, color=color, lw=2.4, label=label)
        finals = [c[f"{kind}|1e-02|{s}"]["val"][-1] for s in range(3)]
        ax.scatter([len(runs) + 6], [sum(finals) / 3], color=color, marker="D", s=70, zorder=4, clip_on=False)
        ax.text(len(runs) + 12, sum(finals) / 3, f"验证 {sum(finals) / 3:.3f}", color=color, va="center", fontsize=11)
    ax.annotate("前一百步左右：没有 warmup 的反而更低", xy=(60, 5.38), xytext=(75, 6.6), fontsize=12, color=ORANGE,
                arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.3))
    ax.set_xlabel("优化器步数")
    ax.set_ylabel("训练损失（3 个种子平均，9 步滑动平均）")
    ax.set_xlim(0, log["steps"] + 45)
    ax.set_ylim(4.4, 7.6)
    ax.legend(fontsize=11, loc="upper right")
    ax.grid(alpha=0.25)
    save_plot(fig, "lr-warmup.svg", "有无 warmup 的训练损失",
              "峰值 1e-2 的 WSD：去掉 warmup 后，前一百步左右的训练损失反而更低；大约第 120 步两条线交叉，之后有 warmup 的一路领先，最终验证损失也更低（右侧菱形是 3 个种子的平均）。")


# ---------- 第 18 章：正则化与泛化 ----------

def _reg_log():
    src = DATA / "tinyllm-regularization-log.json"
    if not src.exists():
        print("skip regularization figures: run scripts/build-tinyllm-code.py regularization to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def reg_overfit():
    """300 首、不加正则化（种子 0）：训练损失一路降，验证损失第 100 步见底后回升。"""
    log = _reg_log()
    if log is None:
        return
    r = log["runs"]["无正则化|0"]
    steps, tr, va = r["step"], r["train"], r["val"]
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.plot(steps, tr, color=BLUE, lw=2.4, marker="o", ms=3.5, label="训练集（300 首，eval 模式）")
    ax.plot(steps, va, color=RED, lw=2.4, marker="o", ms=3.5, label="验证集（291 首，训练时没见过）")
    ax.fill_between(steps, tr, va, color=RED, alpha=0.07, lw=0)
    b = steps.index(r["best_step"])
    ax.scatter([steps[b]], [va[b]], s=110, facecolor="none", edgecolor=RED, lw=2, zorder=5)
    ax.annotate(f"验证损失最低：第 {steps[b]} 步 {va[b]:.3f}", xy=(steps[b], va[b]), xytext=(steps[b] + 15, va[b] + 0.75),
                color=RED, fontsize=12, arrowprops=dict(arrowstyle="->", color=RED, lw=1.3))
    ax.annotate("", xy=(steps[-1] + 6, tr[-1]), xytext=(steps[-1] + 6, va[-1]),
                arrowprops=dict(arrowstyle="<->", color=GRAY, lw=1.3))
    ax.text(steps[-1] + 10, (tr[-1] + va[-1]) / 2, f"差\n{va[-1] - tr[-1]:.2f}", color=GRAY, fontsize=12, va="center")
    ax.set_xlabel("训练步数（每步 16 段 × 64 个 token）")
    ax.set_ylabel("交叉熵（nats / token）")
    ax.set_xlim(0, steps[-1] + 30)
    ax.legend(loc="lower left", fontsize=11)
    ax.grid(alpha=0.25)
    save_plot(fig, "reg-overfit.svg", "300 首诗上的过拟合",
              f"不加正则化、在 300 首诗上训练（种子 0）：训练损失从 {tr[0]:.2f} 一路降到 {tr[-1]:.2f}；验证损失在第 {steps[b]} 步见底（{va[b]:.3f}），"
              f"之后一路回升到 {va[-1]:.2f}，两者的差从 {va[0] - tr[0]:.2f} 拉大到 {va[-1] - tr[-1]:.2f}。")


def reg_data_size():
    """同一个模型、同样 300 步，训练集 300/600/1200/5419 首（种子 0）的验证损失。"""
    log = _reg_log()
    if log is None:
        return
    runs = log["runs"]
    full = log["full"]
    picks = [("300 首", "无正则化|0", RED), ("600 首", "600 首|0", ORANGE), ("1200 首", "1200 首|0", TEAL),
             (f"全部 {full} 首", f"{full} 首|0", BLUE)]
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    notes = []
    for label, key, color in picks:
        r = runs[key]
        ax.plot(r["step"], r["val"], color=color, lw=2.4, marker="o", ms=3.5, label=label)
        b = r["step"].index(r["best_step"])
        ax.scatter([r["step"][b]], [r["val"][b]], s=110, facecolor="none", edgecolor=color, lw=2, zorder=5)
        notes.append(f"{label}最低 {r['val'][b]:.2f}（第 {r['best_step']} 步）")
    ax.set_xlabel("训练步数")
    ax.set_ylabel("验证损失（种子 0；圆圈是最低点）")
    ax.legend(loc="lower left", fontsize=11, title="训练集", title_fontsize=11)
    ax.grid(alpha=0.25)
    save_plot(fig, "reg-data-size.svg", "训练集大小与验证损失",
              "同一个模型、同样 300 步，只改训练集大小（种子 0）：" + "；".join(notes) +
              "。数据越多，验证损失越低、见底越晚；全部数据在 300 步内一直在下降。")


def reg_weight_decay():
    """左：不同 weight decay 的验证损失（种子 0）；右：矩阵权重的 L2 范数。"""
    log = _reg_log()
    if log is None:
        return
    runs = log["runs"]
    picks = [("0", "无正则化|0", GRAY), ("0.1", "weight_decay 0.1|0", BLUE), ("1", "weight_decay 1|0", TEAL),
             ("3", "weight_decay 3|0", RED), ("10", "weight_decay 10|0", PURPLE)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), layout="constrained", gridspec_kw={"width_ratios": [1.35, 1]})
    for label, key, color in picks:
        r = runs[key]
        a1.plot(r["step"], r["val"], color=color, lw=2.3, marker="o", ms=3, label=f"weight_decay={label}")
        a2.plot(r["step"], r["norm"], color=color, lw=2.3, label=label)
        a2.text(r["step"][-1] + 6, r["norm"][-1], f"{r['norm'][-1]:.1f}", color=color, fontsize=11, va="center")
    a1.set_xlabel("训练步数")
    a1.set_ylabel("验证损失（种子 0）")
    a1.set_title("太小没作用，太大学不动", fontsize=12.5)
    a1.legend(fontsize=10, loc="upper center")
    a1.grid(alpha=0.25)
    a2.set_xlabel("训练步数")
    a2.set_ylabel("矩阵权重的 L2 范数")
    a2.set_title("weight decay 把权重往 0 拉", fontsize=12.5)
    a2.set_xlim(0, runs["无正则化|0"]["step"][-1] + 40)
    a2.grid(alpha=0.25)
    norms = "、".join(f"{label} → {runs[key]['norm'][-1]:.1f}" for label, key, _ in picks)
    save_plot(fig, "reg-weight-decay.svg", "weight decay 的强度：验证损失与权重范数",
              "左：300 首诗、种子 0。weight_decay=0 和 0.1 的验证损失几乎重合，第 100 步后一路回升；1 推迟并压低了回升；3 的验证损失一直在降，最好；"
              f"10 压得太狠，最低点反而比 3 高。右：第 300 步矩阵权重的 L2 范数（{norms}）。")


def reg_dropout():
    """无正则化与 dropout 0.1、0.3（种子 0）：实线验证、虚线训练（eval 模式）。"""
    log = _reg_log()
    if log is None:
        return
    runs = log["runs"]
    picks = [("不加 dropout", "无正则化|0", GRAY), ("dropout 0.1", "dropout 0.1|0", BLUE), ("dropout 0.3", "dropout 0.3|0", RED)]
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    for label, key, color in picks:
        r = runs[key]
        ax.plot(r["step"], r["val"], color=color, lw=2.4, marker="o", ms=3.5, label=f"{label}：验证")
        ax.plot(r["step"], r["train"], color=color, lw=1.8, ls="--", label=f"{label}：训练（eval 模式）")
        b = r["step"].index(r["best_step"])
        ax.scatter([r["step"][b]], [r["val"][b]], s=110, facecolor="none", edgecolor=color, lw=2, zorder=5)
    r0, r3 = runs["无正则化|0"], runs["dropout 0.3|0"]
    ax.set_xlabel("训练步数")
    ax.set_ylabel("交叉熵（种子 0；圆圈是验证最低点）")
    ax.legend(fontsize=10.5, loc="lower left", ncol=3)
    ax.set_ylim(2.2, 6.6)
    ax.grid(alpha=0.25)
    save_plot(fig, "reg-dropout.svg", "dropout 对训练与验证损失的影响",
              f"300 首诗、种子 0。不加 dropout 时验证损失第 {r0['best_step']} 步见底（{r0['best_val']:.3f}）；dropout 0.3 让训练损失降得更慢，"
              f"验证损失推迟到第 {r3['best_step']} 步才见底，最低点 {r3['best_val']:.3f} 更低，之后的回升也平缓得多。")


def reg_compare():
    """左：300 首上各种设置的测试损失（3 个种子，另有两个单种子的数据量参照）；右：全部数据上。"""
    log = _reg_log()
    if log is None:
        return
    s, full = log["summary"], log["full_summary"]
    rows = [("无正则化", s["300 首"], GRAY), ("weight_decay 0.1", s["weight_decay 0.1"], BLUE),
            ("label smoothing 0.1", s["label smoothing 0.1"], ORANGE), ("dropout 0.3", s["dropout 0.3"], PURPLE),
            ("weight_decay 3", s["weight_decay 3"], RED), ("换成 600 首（单种子）", s["600 首"], TEAL),
            ("换成 1200 首（单种子）", s["1200 首"], TEAL)]
    frows = [("无正则化", full["无正则化"], GRAY), ("dropout 0.1", full["dropout 0.1"], PURPLE), ("weight_decay 3", full["weight_decay 3"], RED)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.6), layout="constrained", gridspec_kw={"width_ratios": [1.5, 1]})
    for ax, data in ((a1, rows), (a2, frows)):
        for i, (name, vals, color) in enumerate(data):
            m = sum(vals) / len(vals)
            if len(vals) > 1:
                ax.plot([min(vals), max(vals)], [i, i], color=color, lw=6, alpha=0.35, solid_capstyle="round")
                ax.scatter(vals, [i] * len(vals), color=color, s=22, zorder=3)
                ax.scatter([m], [i], color=color, s=90, marker="D", zorder=4)
            else:
                ax.scatter([m], [i], facecolor="white", edgecolor=color, s=90, marker="D", lw=2, zorder=4)
            ax.text(max(vals) + 0.022, i, f"{m:.3f}", va="center", fontsize=11, color=color)
        ax.set_yticks(range(len(data)), [d[0] for d in data], fontsize=11)
        ax.invert_yaxis()
        ax.axvline(sum(data[0][1]) / len(data[0][1]), color=GRAY, ls="--", lw=1.2)
        ax.grid(alpha=0.25, axis="x")
    a1.set_title("只有 300 首诗（训练集过 20 遍）", fontsize=12.5)
    a1.set_xlabel("测试损失（验证损失最低那一步的参数）")
    a2.set_title(f"全部 {log['full']} 首（只过约 1 遍）", fontsize=12.5)
    a2.set_xlabel("测试损失")
    lo, hi = a2.get_xlim()
    a2.set_xlim(lo, hi + 0.04)
    lo, hi = a1.get_xlim()
    a1.set_xlim(lo, hi + 0.05)
    mean = lambda v: sum(v) / len(v)
    save_plot(fig, "reg-compare.svg", "正则化对照：300 首与全部数据",
              f"左：300 首诗上，3 个种子的测试损失（菱形是平均，横条是范围）。无正则化 {mean(s['300 首']):.3f}；weight_decay 0.1 与 label smoothing 几乎没变化（都是 {mean(s['weight_decay 0.1']):.3f}）；"
              f"dropout 0.3 降到 {mean(s['dropout 0.3']):.3f}；weight_decay 3 最好，{mean(s['weight_decay 3']):.3f}，和训练集换成 600 首（{s['600 首'][0]:.3f}，单种子）相当；换成 1200 首是 {s['1200 首'][0]:.3f}。"
              f"右：全部数据上，无正则化 {mean(full['无正则化']):.3f} 最好，dropout 0.1 变差到 {mean(full['dropout 0.1']):.3f}，weight_decay 3 变差到 {mean(full['weight_decay 3']):.3f}。")


def reg_dropout_positions():
    """dropout 放在哪三个位置，以及 train / eval 两种模式。"""
    body = text(480, 40, "TinyLLM 里的三处 dropout，以及它在训练和评估时的不同行为", 22, weight="bold")
    sx = 150                                   # 残差流的 x
    body += text(sx, 84, "token ID", 17)
    body += arrow(sx, 92, sx, 112)
    body += cbox(sx - 90, 114, 180, 40, BLUE) + text(sx, 140, "词嵌入", 17, BLUE, "bold")
    body += arrow(sx, 154, sx, 172)
    body += cbox(sx - 90, 174, 180, 36, RED, dash=True) + text(sx, 198, "③ Dropout", 16, RED, "bold")
    plus2 = 562
    body += f'<path d="M{sx} 210 V{plus2 - 15}" stroke="{INK}" stroke-width="6" fill="none" opacity="0.18"/>'
    body += text(sx - 14, 300, "残差流", 14, GRAY, anchor="end")
    bx = 380
    for y, name, color, inner in [(232, "注意力", BLUE, True), (422, "SwiGLU", TEAL, False)]:
        body += path(f"M{sx} {y + 10} H{bx - 92}", GRAY, 2)
        body += cbox(bx - 90, y - 8, 180, 34, PURPLE) + text(bx, y + 15, "RMSNorm", 15, PURPLE, "bold")
        body += arrow(bx, y + 26, bx, y + 40, GRAY, 2)
        body += cbox(bx - 110, y + 42, 220, 44, color) + text(bx, y + 70, name, 17, color, "bold")
        if inner:
            body += text(bx + 118, y + 60, "① 注意力权重", 14, RED, "bold", "start")
            body += text(bx + 118, y + 80, "softmax 之后随机丢掉一部分", 13, GRAY, anchor="start")
        body += arrow(bx, y + 86, bx, y + 98, GRAY, 2)
        body += cbox(bx - 90, y + 100, 180, 32, RED, dash=True) + text(bx, y + 122, "② Dropout", 15, RED, "bold")
        body += path(f"M{bx} {y + 132} V{y + 140} H{sx + 20}", color, 2.5)
        body += circle(sx, y + 140, 15) + text(sx, y + 147, "+", 21, weight="bold")
    body += arrow(sx, plus2 + 15, sx, plus2 + 40, GRAY)
    body += text(sx, plus2 + 62, "最终 RMSNorm → logits", 15)
    body += f'<line x1="610" y1="70" x2="610" y2="620" stroke="#e2e8f0" stroke-width="2"/>'
    # 右：两种模式
    rx = 640
    body += text(785, 92, "model.train()：每次前向重新抽一个掩码", 16, RED, "bold")
    vals = ["x₁", "x₂", "x₃", "x₄", "x₅"]
    keep = [True, False, True, True, False]
    for i, (v, k) in enumerate(zip(vals, keep)):
        x = rx + 12 + i * 56
        body += box(x, 112, 48, 38, "#ffffff", "#94a3b8") + text(x + 24, 138, v, 17)
        body += arrow(x + 24, 152, x + 24, 176, GRAY, 1.6)
        body += box(x, 178, 48, 38, "#fef2f2" if not k else "#ffffff", RED if not k else "#94a3b8") + text(x + 24, 204, "×1.43" if k else "0", 15, INK if k else RED)
    body += text(785, 244, "以概率 p 置零，留下的乘 1/(1−p)", 15)
    body += text(785, 268, "p = 0.3 时 1/(1−p) ≈ 1.43，平均值不变", 15, GRAY)
    body += text(785, 330, "model.eval()：原样通过", 16, TEAL, "bold")
    for i, v in enumerate(vals):
        x = rx + 12 + i * 56
        body += box(x, 350, 48, 38, "#ffffff", "#94a3b8") + text(x + 24, 376, v, 17)
        body += arrow(x + 24, 390, x + 24, 414, GRAY, 1.6)
        body += box(x, 416, 48, 38, "#ecfdf5", TEAL) + text(x + 24, 442, v, 17)
    body += text(785, 484, "评估、生成都要先调 model.eval()，", 15)
    body += text(785, 508, "否则每次结果都不一样，而且偏差", 15)
    svg("reg-dropout-positions.svg", "dropout 的位置和两种模式",
        "左：TinyLLM 的三处 dropout。① 注意力权重在 softmax 之后随机丢掉一部分；② 注意力和 SwiGLU 的输出在加回残差流之前各过一次 dropout；"
        "③ 词嵌入之后过一次。右：model.train() 时每个数以概率 p 置零，留下的乘 1/(1−p)，p=0.3 时约乘 1.43；model.eval() 时原样通过。", 650, body)


# ---------- 第 20 章：梯度稳定与累积 ----------

def _grad_log():
    src = DATA / "tinyllm-gradient-stability-log.json"
    if not src.exists():
        print("skip gradient-stability figures: run scripts/build-tinyllm-code.py gradient-stability to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def grad_norm_trace():
    """基线（裁到 1.0）3 个种子的裁剪前全局梯度范数。"""
    log = _grad_log()
    if log is None:
        return
    runs = log["runs"]
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    for seed, color, lw, alpha in ((1, GRAY, 1.2, 0.55), (2, GRAY, 1.2, 0.55), (0, BLUE, 1.8, 1.0)):
        n = np.array(runs[f"裁到 1.0|{seed}"]["grad_norm"])
        x = np.arange(1, len(n) + 1)
        ax.plot(x, n, color=color, lw=lw, alpha=alpha, label={0: "种子 0", 1: "种子 1、2"}.get(seed))
        if seed == 0:
            hit = n > 1.0
            ax.scatter(x[hit], n[hit], color=RED, s=16, zorder=4, label=f"种子 0 被裁剪的步（{hit.sum()}/{len(n)}）")
    ax.axhline(1.0, color=RED, ls="--", lw=1.4)
    ax.text(3, 1.05, "阈值 1.0", color=RED, fontsize=11, va="bottom")
    ax.set_xlabel("优化器步数")
    ax.set_ylabel("裁剪前的全局梯度范数")
    ax.set_xlim(0, len(n) + 1)
    ax.legend(fontsize=10.5, loc="upper left", ncol=3)
    ax.grid(alpha=0.25)
    n0 = runs["裁到 1.0|0"]["grad_norm"]
    save_plot(fig, "grad-norm-trace.svg", "基线训练中的全局梯度范数",
              f"代理模型、AdamW、学习率 3e-3、裁到 1.0。种子 0 的梯度范数从第 1 步的 {n0[0]:.2f} 很快降到 0.5 左右，后半程又逐渐变大、抖动加剧；"
              f"240 步里有 {sum(v > 1.0 for v in n0)} 步超过阈值 1.0 被裁剪，多数集中在后半程。另外两个种子走势相同。")


def grad_clip_geometry():
    """按全局范数裁剪与按值裁剪的二维示意。"""
    body = text(480, 40, "同一个梯度，两种裁剪方式（二维示意）", 22, weight="bold")
    for k, (cx, title, color) in enumerate([(250, "按全局范数裁剪：整体缩小，方向不变", BLUE), (710, "按值裁剪：逐个数截断，方向改变", ORANGE)]):
        ox, oy, u = cx - 150, 400, 60          # 原点与单位长度
        body += text(cx, 82, title, 17, color, "bold")
        body += f'<line x1="{ox - 20}" y1="{oy}" x2="{ox + 300}" y2="{oy}" stroke="#cbd5e1" stroke-width="1.5"/>'
        body += f'<line x1="{ox}" y1="{oy + 20}" x2="{ox}" y2="{oy - 280}" stroke="#cbd5e1" stroke-width="1.5"/>'
        if k == 0:
            body += f'<path d="M{ox + 2 * u} {oy} A{2 * u} {2 * u} 0 0 0 {ox} {oy - 2 * u}" fill="none" stroke="{color}" stroke-width="1.6" stroke-dasharray="6 5"/>'
            body += text(ox + 2 * u + 8, oy - 12, "半径 = 阈值", 13, color, anchor="start")
            gx, gy = 4 * u, 3 * u                       # 原梯度 (4, 3)，范数 5
            cx2, cy2 = gx * 2 / 5, gy * 2 / 5            # 裁到范数 2
        else:
            body += f'<rect x="{ox}" y="{oy - 1.2 * u}" width="{1.2 * u}" height="{1.2 * u}" fill="{SOFT[ORANGE]}" stroke="{color}" stroke-width="1.6" stroke-dasharray="6 5"/>'
            body += text(ox + 1.2 * u + 8, oy - 1.2 * u + 4, "每个数限制在 ±阈值", 13, color, anchor="start")
            gx, gy = 4 * u, 1 * u                       # 原梯度 (4, 1)
            cx2, cy2 = 1.2 * u, 1 * u                    # 第一维截断到 1.2，第二维不变
        body += arrow(ox, oy, ox + gx, oy - gy, GRAY, 3)
        body += text(ox + gx + 6, oy - gy - 6, "原梯度", 14, GRAY, anchor="start")
        body += arrow(ox, oy, ox + cx2, oy - cy2, color, 4)
        body += text(ox + cx2 + 4, oy - cy2 + 24, "裁剪后", 14, color, "bold", "start")
    body += text(250, 440, "所有分量乘同一个系数 min(1, 阈值/‖g‖)", 15)
    body += text(710, 440, "大的分量被压扁，小的不动，方向偏向小分量", 15)
    svg("grad-clip-geometry.svg", "按全局范数裁剪与按值裁剪",
        "左：按全局范数裁剪，梯度向量整体缩短到阈值半径的圆上，方向不变。右：按值裁剪，每个分量被限制在正负阈值之内，"
        "大的分量被压扁，小的不变，裁剪后的方向偏离原梯度。", 470, body)


def grad_spike():
    """第 120 步梯度放大 1000 倍：训练损失与每步更新量（种子 0）。"""
    log = _grad_log()
    if log is None:
        return
    runs, s0 = log["runs"], log["spike_step"]
    picks = [("没有尖峰（不裁剪）", "不裁剪|0", GRAY), ("尖峰 ×1000，不裁剪", "尖峰 ×1000，不裁剪|0", RED),
             ("尖峰 ×1000，不裁剪，β2=0.95", "尖峰 ×1000，不裁剪，β2=0.95|0", ORANGE), ("尖峰 ×1000，裁到 1.0", "尖峰 ×1000，裁到 1.0|0", BLUE)]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.2), layout="constrained", sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
    k = 9
    for label, key, color in picks:
        r = runs[key]
        loss = np.convolve(r["loss"], np.ones(k) / k, mode="valid")
        a1.plot(np.arange(len(loss)) + k // 2 + 1, loss, color=color, lw=2.0, label=f"{label}（验证 {r['val']:.3f}）",
                ls="--" if "裁到" in label else "-")
        a2.plot(np.arange(1, len(r["update"]) + 1), r["update"], color=color, lw=1.6, ls="--" if "裁到" in label else "-")
    for ax in (a1, a2):
        ax.axvline(s0 + 1, color=RED, lw=1, alpha=0.5)
        ax.grid(alpha=0.25)
    a1.text(s0 - 2, 6.6, f"第 {s0 + 1} 步：梯度放大 1000 倍", color=RED, fontsize=11, ha="right")
    a1.set_ylabel("训练损失（9 步滑动平均）")
    a1.set_ylim(4.4, 7.2)
    a1.legend(fontsize=10, loc="upper right")
    a2.set_yscale("log")
    a2.set_ylabel("每步更新量 ‖Δθ‖")
    a2.set_xlabel("优化器步数")
    sp = runs["尖峰 ×1000，不裁剪|0"]["update"]
    save_plot(fig, "grad-spike.svg", "一次梯度尖峰对 AdamW 的影响",
              f"种子 0，第 {s0 + 1} 步把梯度放大 1000 倍。不裁剪时，尖峰后约 10 步的更新量先变大（平均 {sum(sp[s0 + 1:s0 + 11]) / 10:.2f}，正常约 0.30），"
              f"损失回升；之后更新量掉到 {sum(sp[200:]) / 40:.3f} 左右，训练几乎停住，验证损失停在 {runs['尖峰 ×1000，不裁剪|0']['val']:.3f}。"
              f"β2=0.95 恢复得快一些（{runs['尖峰 ×1000，不裁剪，β2=0.95|0']['val']:.3f}）。裁到 1.0 时尖峰几乎没有影响（{runs['尖峰 ×1000，裁到 1.0|0']['val']:.3f}），和没有尖峰的曲线重合。")


def grad_compare():
    """3 个种子的对照：裁剪阈值，以及梯度尖峰。"""
    log = _grad_log()
    if log is None:
        return
    s = log["summary"]
    rows = [("不裁剪", s["不裁剪"], GRAY), ("裁到 1.0（第 12 章）", s["裁到 1.0"], BLUE), ("裁到 0.01", s["裁到 0.01"], TEAL),
            ("尖峰 ×1000，不裁剪", s["尖峰 ×1000，不裁剪"], RED), ("尖峰 ×1000，裁到 1.0", s["尖峰 ×1000，裁到 1.0"], BLUE)]
    fig, ax = plt.subplots(figsize=(10, 3.8), layout="constrained")
    for i, (name, vals, color) in enumerate(rows):
        m = sum(vals) / len(vals)
        ax.plot([min(vals), max(vals)], [i, i], color=color, lw=6, alpha=0.35, solid_capstyle="round")
        ax.scatter(vals, [i] * len(vals), color=color, s=22, zorder=3)
        ax.scatter([m], [i], color=color, s=90, marker="D", zorder=4)
        ax.text(max(vals) + 0.015, i, f"{m:.3f}", va="center", fontsize=11, color=color)
    ax.axhline(2.5, color="#cbd5e1", lw=1)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel("最终验证损失（3 个种子；菱形是平均，横条是范围）")
    ax.grid(alpha=0.25, axis="x")
    lo, hi = ax.get_xlim()
    ax.set_xlim(lo, hi + 0.06)
    mean = lambda v: sum(v) / len(v)
    save_plot(fig, "grad-compare.svg", "裁剪阈值与梯度尖峰的对照",
              f"上面三行：不裁剪 {mean(s['不裁剪']):.3f}、裁到 1.0 {mean(s['裁到 1.0']):.3f}、裁到 0.01 {mean(s['裁到 0.01']):.3f}，范围互相重叠，阈值改一百倍几乎没有影响。"
              f"下面两行：第 {log['spike_step'] + 1} 步梯度放大 1000 倍，不裁剪变差到 {mean(s['尖峰 ×1000，不裁剪']):.3f}，裁到 1.0 是 {mean(s['尖峰 ×1000，裁到 1.0']):.3f}，和没有尖峰时一样。")


def grad_accum_loop():
    """一个优化器步里各个调用的顺序（含梯度累积与 FP16）。"""
    body = text(480, 40, "一个优化器步：先累积，再缩回、裁剪、更新", 22, weight="bold")
    y = 78
    body += cbox(330, y, 300, 40, GRAY) + mtext(480, y + 26, "optimizer.zero_grad()", 16)
    body += text(660, y + 26, "每个优化器步一次", 14, GRAY, anchor="start")
    body += arrow(480, y + 40, 480, y + 66, GRAY)
    # 累积循环
    body += f'<rect x="200" y="{y + 68}" width="560" height="196" rx="14" fill="{SOFT[BLUE]}" stroke="{BLUE}" stroke-width="2" stroke-dasharray="7 5"/>'
    body += text(220, y + 92, "重复 accum 次（每个 micro-batch）", 15, BLUE, "bold", "start")
    body += cbox(330, y + 104, 300, 38, BLUE) + text(480, y + 129, "前向：算这个 micro-batch 的损失", 15)
    body += arrow(480, y + 142, 480, y + 158, GRAY, 2)
    body += cbox(330, y + 160, 300, 38, BLUE) + mtext(480, y + 185, "(loss / accum).backward()", 15)
    body += text(640, y + 185, "FP16：scaler.scale(…)", 13, ORANGE, anchor="start")
    body += arrow(480, y + 198, 480, y + 214, GRAY, 2)
    body += text(480, y + 236, "梯度在 .grad 里累加；这里不裁剪、不更新、不清零", 15, RED)
    body += arrow(480, y + 264, 480, y + 290, GRAY)
    steps = [("scaler.unscale_(optimizer)", "只有 FP16：先缩回真实大小，再检查 inf/nan", ORANGE, True),
             ("clip_grad_norm_(params, 1.0)", "对累积完的梯度裁一次", INK, False),
             ("optimizer.step()", "FP16 用 scaler.step(optimizer)，有 inf/nan 就跳过", INK, False),
             ("scheduler.step()", "每个优化器步一次，不是每个 micro-batch", INK, False)]
    yy = y + 292
    for i, (code, note, color, dash) in enumerate(steps):
        body += cbox(300, yy, 360, 38, ORANGE if dash else GRAY, dash=dash) + mtext(480, yy + 25, code, 15, color)
        body += text(680, yy + 25, note, 13.5, ORANGE if dash else GRAY, anchor="start")
        if i < len(steps) - 1:
            body += arrow(480, yy + 38, 480, yy + 54, GRAY, 2)
        yy += 56
    svg("grad-accum-loop.svg", "一个优化器步里的调用顺序",
        "一个优化器步从 zero_grad 开始；然后对每个 micro-batch 做前向和 (loss / accum).backward()，梯度在 .grad 里累加，期间不裁剪、不更新、不清零；"
        "累积完以后，FP16 先 unscale_ 缩回真实大小，再对累积完的梯度裁剪一次，然后 optimizer.step()（FP16 用 scaler.step，遇到 inf/nan 跳过），最后 scheduler.step()。", yy + 10, body, width=1000)


def grad_fp16_hist():
    """训练好的模型上一个 batch 的梯度绝对值分布，对照 FP16 能表示的范围。"""
    log = _grad_log()
    if log is None:
        return
    h = np.array(log["hist"])
    edges = np.linspace(-12, 0, len(h) + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    w = edges[1] - edges[0]
    shift = np.log10(2.0 ** 16)
    lo_n, lo_s = np.log10(log["fp16"]["smallest_normal"]), np.log10(log["fp16"]["smallest_subnormal"])
    hi = np.log10(65504)
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    ax.axvspan(-12.5, lo_s, color=RED, alpha=0.08)
    ax.axvspan(lo_s, lo_n, color=ORANGE, alpha=0.10)
    ax.axvspan(hi, 10, color=RED, alpha=0.08)
    ax.bar(centers, h / h.sum() * 100, width=w * 0.95, color=GRAY, alpha=0.75, label="原始梯度")
    ax.bar(centers + shift, h / h.sum() * 100, width=w * 0.95, color=BLUE, alpha=0.55, label="乘以 2^16 之后")
    top = (h / h.sum() * 100).max() * 1.25
    ax.text(lo_s - 0.15, top * 0.85, "变成 0", color=RED, fontsize=11, ha="right")
    ax.text((lo_s + lo_n) / 2, top * 0.85, "次正规数\n（有效位变少）", color=ORANGE, fontsize=10.5, ha="center")
    ax.text(hi + 0.15, top * 0.85, "溢出\n成 inf", color=RED, fontsize=11, ha="left")
    ax.set_xlim(-12.5, 6.5)
    ax.set_ylim(0, top)
    ax.set_xlabel("梯度绝对值（log10）")
    ax.set_ylabel("占全部参数的比例（%）")
    ax.legend(fontsize=11, loc="upper left")
    ax.grid(alpha=0.25)
    below = h[centers < lo_n].sum() / h.sum()
    save_plot(fig, "grad-fp16-hist.svg", "梯度大小与 FP16 能表示的范围",
              f"灰色是训练好的代理模型在一个 batch 上的参数梯度（FP32），约 {below:.0%} 落在 FP16 的最小正规数 6.1e-5 以下，极少数小于 6e-8 会直接变成 0；"
              "蓝色是放大 2^16 倍之后，整体右移约 4.8 个数量级，几乎全部进入正规数范围，离上限 65504 还有距离。")


# ---------- 第 21 章：训练循环与检查点 ----------

def _loop_log():
    src = DATA / "tinyllm-training-loop-log.json"
    if not src.exists():
        print("skip training-loop figures: run scripts/build-tinyllm-code.py training-loop to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def loop_structure():
    """训练循环的骨架：epoch 外层、batch 内层、每步的六个调用，以及日志、评估、保存的节奏。"""
    body = text(500, 40, "可以随时中断、随时恢复的训练循环", 22, weight="bold")
    body += cbox(60, 70, 880, 54, PURPLE) + text(500, 94, "progress = {step, epoch, batch_in_epoch}", 16, PURPLE, "bold")
    body += text(500, 115, "新训练从 0 开始；恢复时从检查点读出来", 13.5, GRAY)
    body += arrow(500, 124, 500, 146, GRAY)
    body += f'<rect x="60" y="148" width="880" height="452" rx="16" fill="#ffffff" stroke="{TEAL}" stroke-width="2" stroke-dasharray="7 5"/>'
    body += text(80, 174, "while step < until：每个 epoch", 15, TEAL, "bold", "start")
    body += cbox(90, 186, 820, 38, TEAL) + mtext(500, 211, "sampler.set_epoch(epoch, start=batch_in_epoch * BATCH)", 15, TEAL)
    body += f'<rect x="90" y="238" width="820" height="304" rx="14" fill="{SOFT[BLUE]}" stroke="{BLUE}" stroke-width="2" stroke-dasharray="7 5"/>'
    body += text(108, 262, "for x, y in loader：每个 batch", 15, BLUE, "bold", "start")
    calls = ["zero_grad", "前向", "backward", "裁剪", "optimizer.step", "scheduler.step"]
    w, gap, x0 = 118, 14, 112
    for i, c in enumerate(calls):
        x = x0 + i * (w + gap)
        body += cbox(x, 278, w, 44, BLUE) + (mtext(x + w / 2, 305, c, 13) if c.isascii() else text(x + w / 2, 306, c, 14.5, INK, "bold"))
        if i < len(calls) - 1:
            body += arrow(x + w, 300, x + w + gap - 1, 300, GRAY, 2)
    body += text(500, 348, "step += 1，batch_in_epoch += 1；损失先存成张量", 15)
    rows = [("每 log_every 步", "取一次 .item() 打印：GPU 上 .item() 会让 CPU 停下来等 GPU 算完", GRAY),
            ("每 eval_every 步", "model.eval() 测验证损失，再切回 model.train()", GRAY),
            ("每 save_every 步", "保存完整检查点：先写 .tmp，再 os.replace；只留最新几个", ORANGE),
            ("step == until", "返回；下一次从 progress 接着来", RED)]
    yy = 372
    for k, (when, what, color) in enumerate(rows):
        body += box(120, yy, 760, 36, "#ffffff", "#cbd5e1") + text(136, yy + 24, when, 14.5, color, "bold", "start")
        body += text(290, yy + 24, what, 14, INK, anchor="start")
        yy += 42
    body += text(500, 572, "这个 epoch 的 batch 用完：epoch += 1，batch_in_epoch = 0", 15, TEAL)
    svg("loop-structure.svg", "可以随时中断和恢复的训练循环",
        "最外面是 progress（step、epoch、batch_in_epoch）。每个 epoch 先 sampler.set_epoch(epoch, start)，跳过这个 epoch 已经用过的样本；"
        "每个 batch 依次 zero_grad、前向、backward、裁剪、optimizer.step、scheduler.step，然后推进 progress。"
        "每隔若干步取一次 .item() 打印日志、测一次验证损失、保存一次完整检查点（先写临时文件再替换）；"
        "到达 until 就返回，下次从 progress 接着来。一个 epoch 用完后 epoch 加一、batch_in_epoch 归零。", 620, body, width=1000)


def ckpt_contents():
    """检查点的组成、大小，以及缺了哪一样会怎样（数字来自 training-loop.py）。"""
    log = _loop_log()
    if log is None:
        return
    s, a = log["sizes"], log["ablation"]
    kb = lambda k: f"{s[k] / 1024:.0f} KB" if s[k] >= 10 * 1024 else f"{s[k] / 1024:.1f} KB"
    rows = [("model", "模型参数", "state_dict()：每个参数张量", None, BLUE),
            ("optimizer", "优化器状态", "AdamW 的 m、v、步数，当前学习率", "缺优化器状态", RED),
            ("scheduler", "调度器状态", "走到了第几步", "缺调度器状态", ORANGE),
            ("progress", "训练进度", "step、epoch、这个 epoch 用掉几个 batch", "缺数据位置", TEAL),
            ("rng", "随机数状态", "全局 torch 随机数（dropout 用）", "缺随机数状态", PURPLE),
            ("config", "配置", "模型配置与训练配置，新进程先按它造对象", None, GRAY)]
    body = text(480, 40, "一个能“接着训”的检查点里有什么", 22, weight="bold")
    body += text(130, 78, "组成", 15, GRAY, "bold") + text(470, 78, "内容", 15, GRAY, "bold") + text(800, 78, "恢复时缺了它", 15, GRAY, "bold")
    y = 92
    for key, name, what, label, color in rows:
        size = kb(key) if key != "config" else f"{(s['config'] + s['train_config']) / 1024:.1f} KB"
        body += cbox(40, y, 180, 50, color) + text(130, y + 22, name, 16, color, "bold") + text(130, y + 42, size, 13.5, GRAY)
        body += text(240, y + 31, what, 14.5, INK, anchor="start")
        if label:
            r = a[label]
            body += text(800, y + 22, f"参数最大差 {r['param_diff']:.2f}", 14, color)
            body += text(800, y + 42, f"最终验证 {r['val']:.4f}", 13.5, GRAY)
        elif key == "model":
            body += text(800, y + 31, "等于从头训练", 14, GRAY)
        else:
            body += text(800, y + 31, "造不出对象", 14, GRAY)
        y += 60
    full = a["完整恢复"]
    body += box(40, y + 8, 880, 46, "#ecfdf5", TEAL) + text(480, y + 37, f"全部存齐（再给 DataLoader 一个自己的 generator）：参数最大差 {full['param_diff']:.1f}，"
                                                      f"验证 {full['val']:.4f}，和一口气训完逐位相同", 15, TEAL, "bold")
    body += text(480, y + 84, f"另外和检查点放在一起：tokenizer.json。本例 {log['n_params']:,} 个参数，优化器状态约是模型的 2 倍", 14, GRAY)
    svg("ckpt-contents.svg", "检查点的组成与缺失的后果",
        f"检查点由模型参数（{kb('model')}）、优化器状态（{kb('optimizer')}）、调度器状态、训练进度、随机数状态和配置组成。"
        f"恢复时缺了优化器状态、调度器状态、数据位置或随机数状态中的任何一样，接着训练的参数都会偏离一口气训完的结果（最大差 "
        f"{a['缺优化器状态']['param_diff']:.2f}、{a['缺调度器状态']['param_diff']:.2f}、{a['缺数据位置']['param_diff']:.2f}、{a['缺随机数状态']['param_diff']:.2f}）；"
        f"全部存齐时最大差为 {full['param_diff']:.1f}，逐位相同。", y + 104, body)


def ckpt_resume():
    """从第 120 步恢复后，各种缺失方式的训练损失和参照的差。"""
    log = _loop_log()
    if log is None:
        return
    ref = np.array(log["reference"])
    r0 = log["resume_step"]
    styles = {"缺优化器状态": RED, "缺调度器状态": ORANGE, "缺数据位置": TEAL, "缺随机数状态": PURPLE}
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.0), layout="constrained", sharex=True, gridspec_kw={"height_ratios": [1.2, 1]})
    k = 9
    smooth = lambda v: np.convolve(v, np.ones(k) / k, mode="valid")
    x = np.arange(len(ref) - k + 1) + k // 2 + 1
    a1.plot(x, smooth(ref), color=INK, lw=2.6, label=f"一口气训完 / 完整恢复（验证 {log['reference_val']:.4f}）")
    for label, color in styles.items():
        v = np.array(log["ablation"][label]["losses"])
        a1.plot(x[x > r0 - 5], smooth(v)[x > r0 - 5], color=color, lw=1.6, label=f"{label}（验证 {log['ablation'][label]['val']:.4f}）")
        d = np.abs(v - ref)[r0:]
        a2.plot(np.arange(r0 + 1, len(ref) + 1), np.maximum(d, 1e-6), color=color, lw=1.2, alpha=0.9)
    for ax in (a1, a2):
        ax.axvline(r0 + 0.5, color=GRAY, ls="--", lw=1.2)
        ax.grid(alpha=0.25)
    a1.text(r0 - 2, 6.2, f"第 {r0} 步存档、“断电”", color=GRAY, fontsize=11, ha="right")
    a1.set_ylabel("训练损失（9 步滑动平均）")
    a1.set_ylim(4.6, 6.6)
    a1.legend(fontsize=10, loc="upper right")
    a2.set_yscale("log")
    a2.set_ylim(1e-6, 2)
    a2.set_ylabel("和参照的损失差（每步）")
    a2.set_xlabel("优化器步数")
    a2.text(r0 + 3, 2.2e-6, "完整恢复：每一步的差都是 0（对数坐标画不出来）", color=INK, fontsize=10.5)
    gaps = {lab: max(abs(a - b) for a, b in zip(log["ablation"][lab]["losses"][r0:], ref[r0:])) for lab in styles}
    save_plot(fig, "ckpt-resume.svg", "从检查点恢复后的训练损失",
              f"第 {r0} 步存档后恢复、接着训练到第 {len(ref)} 步。完整恢复时每一步的损失都和一口气训完相同。"
              f"缺优化器状态时，恢复后头几步的损失明显跳高（最大差 {gaps['缺优化器状态']:.2f}）；缺调度器状态时学习率重新 warmup、最后的衰减段没有发生，"
              f"损失降不下去（验证 {log['ablation']['缺调度器状态']['val']:.4f}）；缺数据位置、缺随机数状态时，损失从第 {r0 + 1} 步起就和参照不同，但走势相近。")


# ---------- 第 22 章：训练诊断与评估 ----------

def _eval_log():
    src = DATA / "tinyllm-training-evaluation-log.json"
    if not src.exists():
        print("skip training-evaluation figures: run scripts/build-tinyllm-code.py training-evaluation to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def eval_pretty_curves():
    """正确的代码与三个 bug 的训练损失：有 bug 的曲线反而更“好看”。"""
    log = _eval_log()
    if log is None:
        return
    c = log["curves"]
    picks = [("None", "正确的代码", INK), ("漏了因果掩码", "漏了因果掩码", RED), ("标签没错位", "标签没错位", ORANGE),
             ("每步同一个 batch", "每步同一个 batch", PURPLE)]
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    k = 9
    for key, label, color in picks:
        loss = np.array(c[key]["loss"])
        sm = np.convolve(loss, np.ones(k) / k, mode="valid")
        ax.plot(np.arange(len(sm)) + k // 2 + 1, sm, color=color, lw=2.6 if key == "None" else 1.8,
                label=f"{label}：训练 {loss[-20:].mean():.3f}，验证 {c[key]['val']:.3f}")
        ax.scatter([log["steps"] + 6], [c[key]["val"]], color=color, marker="D", s=60, clip_on=False, zorder=4)
    ax.axhline(log["ln_v"], color=GRAY, ls="--", lw=1.2)
    ax.text(3, log["ln_v"] + 0.12, f"均匀乱猜 ln V = {log['ln_v']:.2f}", color=GRAY, fontsize=11)
    ax.set_xlabel("优化器步数（右侧菱形是最终验证损失）")
    ax.set_ylabel("训练损失（9 步滑动平均）")
    ax.set_xlim(0, log["steps"] + 12)
    ax.set_ylim(-0.2, 9.2)
    ax.legend(fontsize=10.5, loc="upper center", bbox_to_anchor=(0.6, 0.97))
    ax.grid(alpha=0.25)
    save_plot(fig, "eval-pretty-curves.svg", "有 bug 的训练曲线反而更好看",
              f"正确的代码训练 240 步，验证损失 {c['None']['val']:.3f}。漏了因果掩码时训练、验证损失都降到 {c['漏了因果掩码']['val']:.2f}，"
              f"标签没错位时降到 {c['标签没错位']['val']:.3f}，看起来比正确的代码好得多；每步同一个 batch 时训练损失降到接近 0，验证损失却是 {c['每步同一个 batch']['val']:.2f}。")


def eval_matrix():
    """六个 bug × 六项检查：通过 / 不通过，以及每格的数值。"""
    log = _eval_log()
    if log is None:
        return
    m = log["matrix"]
    bugs = list(m)
    checks = list(m[bugs[0]])
    fig, ax = plt.subplots(figsize=(11.5, 4.9), layout="constrained")
    for i, bug in enumerate(bugs):
        for j, check in enumerate(checks):
            cell = m[bug][check]
            ok = cell["ok"]
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor="#dcfce7" if ok else "#fee2e2", edgecolor="white", lw=3))
            v = cell["value"]
            txt = "/".join(f"{x:.3g}" for x in v) if isinstance(v, list) else f"{v:.3g}"
            ax.text(j + 0.5, i + 0.38, "✓" if ok else "×", ha="center", va="center", fontsize=17,
                    color=TEAL if ok else RED, fontweight="bold")
            ax.text(j + 0.5, i + 0.74, txt, ha="center", va="center", fontsize=9.5, color=GRAY)
    ax.set_xlim(0, len(checks))
    ax.set_ylim(len(bugs), 0)
    ax.set_xticks(np.arange(len(checks)) + 0.5, [f"{n}{c}" for n, c in zip("①②③④⑤⑥", checks)], fontsize=11)
    ax.set_yticks(np.arange(len(bugs)) + 0.5, ["正确的代码" if b == "None" else b for b in bugs], fontsize=11)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    caught = {b: [c for c in checks if not m[b][c]["ok"]] for b in bugs if b != "None"}
    save_plot(fig, "eval-matrix.svg", "六个 bug 与六项检查",
              "行是六个 bug（第一行是正确的代码），列是六项检查，绿色勾表示通过，红色叉表示不通过，小字是检查测到的数。正确的代码六项全部通过；"
              + "；".join(f"{b}被{('、'.join(v))}抓住" for b, v in caught.items()) + "。没有一项检查能抓住所有 bug。")


def eval_causality():
    """因果性测试：改掉第 t 个 token，前面各位置的输出是否改变。"""
    body = text(480, 40, "因果性测试：改掉后面的一个 token，前面的输出不该变", 22, weight="bold")
    n, x0, w, gap = 9, 115, 70, 12
    pos = 6
    for row, (title, leak, color) in enumerate([("有因果掩码（正确）", False, TEAL), ("漏了因果掩码", True, RED)]):
        y0 = 92 + row * 210
        body += text(60, y0 + 6, title, 17, color, "bold", "start")
        for i in range(n):
            x = x0 + i * (w + gap)
            changed_in = i == pos
            body += box(x, y0 + 22, w, 40, "#fef3c7" if changed_in else "#ffffff", ORANGE if changed_in else "#94a3b8")
            body += text(x + w / 2, y0 + 48, "改" if changed_in else f"x{i}", 16, ORANGE if changed_in else INK, "bold" if changed_in else "normal")
            out_changed = i >= pos or leak
            body += arrow(x + w / 2, y0 + 64, x + w / 2, y0 + 92, GRAY, 1.6)
            body += box(x, y0 + 94, w, 40, "#fee2e2" if out_changed else "#ecfdf5", RED if out_changed else TEAL)
            body += text(x + w / 2, y0 + 120, "变了" if out_changed else "不变", 15, RED if out_changed else TEAL)
        body += text(40, y0 + 48, "输入", 14, GRAY, anchor="start")
        body += text(40, y0 + 120, "输出", 14, GRAY, anchor="start")
        note = "改动之前的位置全部不变：它们看不到后面" if not leak else "改动之前的位置也变了：模型在“偷看”后面的答案"
        body += text(480, y0 + 162, note, 15, color)
    svg("eval-causality.svg", "因果性测试示意",
        "把一段输入里第 6 个 token 换掉，比较前后两次的输出。有因果掩码时，第 6 个之前各位置的输出完全不变，只有它和它之后的位置会变；"
        "漏了因果掩码时，前面的位置也变了，说明模型能看到后面的 token，训练时等于偷看了答案。", 520, body)


def eval_bootstrap():
    """对验证诗做 bootstrap：两个检查点各自的区间重叠，配对的差的区间不含 0。"""
    log = _eval_log()
    if log is None:
        return
    b = log["bootstrap"]
    names = list(b)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.0), layout="constrained", gridspec_kw={"width_ratios": [1.4, 1]})
    for name, color in zip(names[:2], (ORANGE, BLUE)):
        v = np.array(b[name])
        a1.hist(v, bins=40, color=color, alpha=0.55, label=name)
        lo, hi = np.percentile(v, [2.5, 97.5])
        a1.axvline(lo, color=color, ls="--", lw=1)
        a1.axvline(hi, color=color, ls="--", lw=1)
    a1.set_xlabel("验证损失（对 290 首诗重抽 1000 次）")
    a1.set_ylabel("次数")
    a1.set_title("各自的 95% 区间（虚线）互相重叠", fontsize=12.5)
    a1.legend(fontsize=11)
    a1.grid(alpha=0.25)
    d = np.array(b[names[2]])
    a2.hist(d, bins=40, color=TEAL, alpha=0.7)
    lo, hi = np.percentile(d, [2.5, 97.5])
    a2.axvline(lo, color=TEAL, ls="--", lw=1)
    a2.axvline(hi, color=TEAL, ls="--", lw=1)
    a2.axvline(0, color=RED, lw=1.5)
    a2.text(0.0005, a2.get_ylim()[1] * 0.9, "0", color=RED, fontsize=11)
    a2.set_xlabel("配对的差：第 230 步 − 第 240 步")
    a2.set_title("配对以后，差的区间不含 0", fontsize=12.5)
    a2.set_xlim(-0.002, max(d) * 1.1)
    a2.grid(alpha=0.25)
    va, vb = np.percentile(b[names[0]], [2.5, 97.5]), np.percentile(b[names[1]], [2.5, 97.5])
    save_plot(fig, "eval-bootstrap.svg", "验证损失的抽样误差与配对比较",
              f"左：对验证诗有放回地重抽 1000 次，第 230 步检查点的验证损失落在 {va[0]:.3f}～{va[1]:.3f}，第 240 步落在 {vb[0]:.3f}～{vb[1]:.3f}，两个区间重叠。"
              f"右：每次重抽时两个检查点用同一批诗，算它们的差，95% 区间是 {lo:.4f}～{hi:.4f}，宽度只有各自区间的约八分之一，而且不含 0。")


def eval_quality():
    """同一次训练的几个检查点：验证损失与生成样例的格式、乱码、照抄比例。"""
    log = _eval_log()
    if log is None:
        return
    q = log["quality"]
    steps = [int(s) for s in q]
    fig, a1 = plt.subplots(figsize=(10, 4.2), layout="constrained")
    a1.plot(steps, [q[str(s)]["val"] for s in steps], color=INK, lw=2.4, marker="o", label="验证损失（左轴）")
    a1.set_xlabel("训练步数（检查点）")
    a1.set_ylabel("验证损失")
    a1.grid(alpha=0.25)
    a2 = a1.twinx()
    a2.plot(steps, [100 * q[str(s)]["五字句"] for s in steps], color=TEAL, lw=2.2, marker="s", label="五字句占比 %（右轴）")
    a2.plot(steps, [100 * q[str(s)]["乱码"] for s in steps], color=RED, lw=2.2, marker="^", label="乱码字符占比 %（右轴）")
    a2.plot(steps, [100 * q[str(s)]["照抄训练集"] for s in steps], color=PURPLE, lw=1.6, ls="--", marker="x", label="照抄训练集的句子 %（右轴）")
    a2.set_ylabel("百分比")
    a2.set_ylim(-3, 100)
    h1, l1 = a1.get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    a1.legend(h1 + h2, l1 + l2, fontsize=10.5, loc="upper center", bbox_to_anchor=(0.55, 0.99))
    first, last = q[str(steps[0])], q[str(steps[-1])]
    save_plot(fig, "eval-quality.svg", "验证损失与生成样例质量",
              f"同一次训练的 {len(steps)} 个检查点。验证损失从 {first['val']:.2f} 降到 {last['val']:.2f}；五字句占比从 {first['五字句']:.0%} 升到 {last['五字句']:.0%}，"
              f"乱码字符从 {first['乱码']:.0%} 降到 {last['乱码']:.1%}；照抄训练集的句子始终是 0。两者方向一致，但不成比例：后期损失降得慢，格式仍在明显改善。")


# ---------- 第 23 章：超参数与自动化调参 ----------

def _hp_log():
    src = DATA / "tinyllm-hyperparameter-tuning-log.json"
    if not src.exists():
        print("skip hyperparameter-tuning figures: run scripts/build-tinyllm-code.py hyperparameter-tuning to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def hp_sensitivity():
    """每次只改一个超参数：验证损失偏离主线多少个 σ（龙卷风图）。"""
    log = _hp_log()
    if log is None:
        return
    sig, center, base = log["sigma"], log["center"], log["base"]
    names = {"lr": "峰值学习率", "batch": "batch 大小（token 预算固定）", "warmup": "warmup 比例", "wd": "weight decay",
             "beta2": "Adam β2", "decay": "衰减段比例"}
    rows = sorted(log["sensitivity"].items(), key=lambda kv: -max(abs(x - center) for x in kv[1].values()))
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.axvspan(-2, 2, color=GRAY, alpha=0.12)
    ax.text(0, -0.75, "±2σ：噪声以内", ha="center", color=GRAY, fontsize=10.5)
    for i, (k, d) in enumerate(rows):
        for (v, x), color, dy in zip(d.items(), (BLUE, ORANGE), (-0.19, 0.19)):
            z = (x - center) / sig
            ax.barh(i + dy, z, color=color, alpha=0.85, height=0.36)
            ax.text(z + (0.3 if z >= 0 else -0.3), i + dy, f"{v}", va="center", ha="left" if z >= 0 else "right", fontsize=9.5, color=color)
    ax.set_yticks(range(len(rows)), [f"{names[k]}（主线 {base[k]}）" for k, _ in rows], fontsize=10.5)
    ax.invert_yaxis()
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel(f"验证损失相对主线的变化（单位 σ = {sig:.4f}，5 个种子的标准差）")
    ax.grid(alpha=0.25, axis="x")
    lr = log["sensitivity"]["lr"]
    save_plot(fig, "hp-sensitivity.svg", "超参数的敏感度",
              f"以主线配置为中心，每次只把一个超参数换成更小（蓝）或更大（橙）的值，单个种子。学习率偏离最大（3e-2 时变差 {(max(lr.values()) - center) / sig:.1f}σ），"
              "其次是固定 token 预算下的 batch 大小、过短的 warmup、过大的 weight decay；β2 和衰减段比例的变化都在 ±2σ 的噪声带以内。")


def hp_search():
    """左：网格与随机搜索试过的学习率和结果；右：各方法赢家换种子重训的成绩。"""
    log = _hp_log()
    if log is None:
        return
    s, curse, sig, noise = log["searches"], log["curse"], log["sigma"], log["noise"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.4), layout="constrained", gridspec_kw={"width_ratios": [1.3, 1]})
    for name, color, marker in (("网格", ORANGE, "s"), ("随机", BLUE, "o")):
        rs = s[name]["results"]
        a1.scatter([r["config"]["lr"] for r in rs], [r["val"] for r in rs], color=color, marker=marker, s=55, alpha=0.85,
                   label=f"{name}搜索（最好 {s[name]['best']:.4f}）", zorder=3)
    a1.set_xscale("log")
    a1.set_ylim(4.65, 5.6)
    a1.set_xlabel("峰值学习率")
    a1.set_ylabel("最终验证损失（种子 0）")
    a1.set_title("网格只试了 3 个学习率，随机试了 9 个", fontsize=12.5)
    a1.legend(fontsize=10.5, loc="upper left")
    a1.grid(alpha=0.25)
    m = sum(noise) / len(noise)
    a2.axhspan(m - 2 * sig, m + 2 * sig, color=GRAY, alpha=0.15)
    a2.axhline(m, color=GRAY, ls="--", lw=1.2)
    a2.text(2.45, m - 2 * sig + 0.002, "灰带：主线 5 个种子平均 ±2σ", color=GRAY, fontsize=10, ha="right", va="bottom")
    for i, (name, c) in enumerate(curse.items()):
        a2.scatter([i], [c["picked"]], color=RED, marker="D", s=70, zorder=4, label="挑中时（种子 0）" if i == 0 else None)
        a2.scatter([i, i], c["new_seeds"], color=BLUE, s=40, zorder=4, label="换新种子重训" if i == 0 else None)
        a2.plot([i, i], [c["picked"], sum(c["new_seeds"]) / 2], color=GRAY, lw=1, ls=":")
    a2.set_xticks(range(len(curse)), list(curse), fontsize=11)
    a2.set_xlim(-0.5, 2.5)
    a2.set_ylabel("验证损失")
    a2.set_title("赢家换个种子还是赢家吗", fontsize=12.5)
    a2.legend(fontsize=10, loc="upper left")
    a2.grid(alpha=0.25, axis="y")
    save_plot(fig, "hp-search.svg", "三种搜索方法的比较",
              f"左：网格搜索只试了 3 个学习率（1e-3、5.6e-3、3.2e-2），错过了 1e-2 附近的谷底，最好 {s['网格']['best']:.4f}；随机搜索的 9 个配置覆盖了 9 个不同的学习率，最好 {s['随机']['best']:.4f}。"
              f"右：各方法挑出的配置换两个新种子重训。随机搜索的赢家基本站住（平均 {sum(curse['随机']['new_seeds']) / 2:.4f}）；逐轮淘汰的赢家从 {curse['逐轮淘汰']['picked']:.4f} 变成平均 "
              f"{sum(curse['逐轮淘汰']['new_seeds']) / 2:.4f}，比主线还差；灰带是主线 5 个种子的平均 ±2σ。")


def hp_halving():
    """逐轮淘汰：27 个配置在第 32、96 步各淘汰三分之二，剩下的训练到第 240 步。"""
    log = _hp_log()
    if log is None:
        return
    r1, r2 = log["rungs"]
    finals = {json.dumps(r["config"], sort_keys=True): r["val"] for r in log["searches"]["逐轮淘汰"]["results"]}
    key = lambda c: json.dumps(c, sort_keys=True)
    v2 = {key(e["config"]): e["fork"] for e in r2}
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    for e in r1:
        k = key(e["config"])
        xs, ys = [32], [e["fork"]]
        if k in v2:
            xs.append(96); ys.append(v2[k])
        if k in finals:
            xs.append(240); ys.append(finals[k])
        color = RED if k in finals and finals[k] == min(finals.values()) else (BLUE if k in finals else (TEAL if k in v2 else GRAY))
        ax.plot(xs, ys, color=color, lw=1.6 if len(xs) > 1 else 1, alpha=0.9 if len(xs) > 1 else 0.5, marker="o", ms=4)
    for x, n in ((32, len(r1)), (96, len(r2)), (240, len(finals))):
        ax.text(x, 6.75, f"{n} 个", ha="center", color=INK, fontsize=11)
    ax.set_xticks([32, 96, 240])
    ax.set_xlabel("训练到第几步（第 32、96 步时从峰值阶段分叉、接一小段衰减再测）")
    ax.set_ylabel("验证损失")
    ax.set_ylim(4.6, 6.9)
    ax.grid(alpha=0.25)
    best = min(finals.values())
    save_plot(fig, "hp-halving.svg", "逐轮淘汰的过程",
              f"27 个随机配置先各训练 32 步，按分叉衰减后的验证损失只留最好的 9 个（灰色的被淘汰）；训练到第 96 步再留 3 个（青色的被淘汰）；"
              f"最后 3 个训练满 240 步，最好的是 {best:.4f}（红色）。一共约 {log['searches']['逐轮淘汰']['steps'] / log['steps']:.1f} 次完整训练的步数。")


def hp_peek():
    """第 96 步（峰值阶段）的验证损失和最终验证损失：按中间结果挑会挑错。"""
    log = _hp_log()
    if log is None:
        return
    rs = log["searches"]["网格"]["results"] + log["searches"]["随机"]["results"]
    early = np.array([r["val_at_peek"] for r in rs])
    final = np.array([r["val"] for r in rs])
    lrs = np.array([r["config"]["lr"] for r in rs])
    fig, ax = plt.subplots(figsize=(8.6, 4.6), layout="constrained")
    sc = ax.scatter(early, final, c=np.log10(lrs), cmap="viridis", s=60, zorder=3)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("log10（峰值学习率）")
    i_e, i_f = int(early.argmin()), int(final.argmin())
    ax.scatter([early[i_e]], [final[i_e]], facecolor="none", edgecolor=RED, s=220, lw=2, zorder=4)
    ax.annotate("按第 96 步挑中的", (early[i_e], final[i_e]), xytext=(early[i_e] + 0.15, final[i_e] + 0.12), color=RED, fontsize=11,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.scatter([early[i_f]], [final[i_f]], facecolor="none", edgecolor=BLUE, s=220, lw=2, zorder=4)
    ax.annotate("按最终挑中的", (early[i_f], final[i_f]), xytext=(early[i_f] + 0.15, final[i_f] - 0.03), color=BLUE, fontsize=11,
                arrowprops=dict(arrowstyle="->", color=BLUE))
    ax.set_xlabel("第 96 步的验证损失（峰值阶段，还没衰减）")
    ax.set_ylabel("最终验证损失")
    ax.set_ylim(4.62, min(5.6, final.max() + 0.05))
    ax.grid(alpha=0.25)
    save_plot(fig, "hp-peek.svg", "中间结果与最终结果",
              f"网格和随机搜索的 18 次训练：横轴是第 96 步（峰值阶段）的验证损失，纵轴是最终验证损失，颜色是学习率。两者大体一致，但不完全一致；"
              f"按第 96 步挑中的配置最终是 {final[i_e]:.4f}，按最终挑中的是 {final[i_f]:.4f}。")


# ---------- 第 24 章：缩放定律与算力预算 ----------

def _sl_log():
    src = DATA / "tinyllm-scaling-laws-log.json"
    if not src.exists():
        print("skip scaling-laws figures: run scripts/build-tinyllm-code.py scaling-laws to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def _sl_parabola(points):
    """和 scaling-laws.py 的 fit_parabola 相同：最低点左右各两个点，对 ln N 拟合抛物线。"""
    points = sorted(points, key=lambda r: r["N"])
    i = min(range(len(points)), key=lambda k: points[k]["loss"])
    chosen = points[max(0, i - 2):i + 3]
    x = np.log([r["N"] for r in chosen])
    a, b, c = np.polyfit(x, [r["loss"] for r in chosen], 2)
    return chosen, (lambda N: a * np.log(N) ** 2 + b * np.log(N) + c)


def sl_six_nd():
    """6ND 的来历：一个权重、一个 token，前向 2 次运算，反向 4 次；右边是实测核对。"""
    log = _sl_log()
    if log is None:
        return
    body = text(480, 36, "一个权重、一个 token：前向 2 次运算，反向 4 次", 21, weight="bold")
    steps = [
        (40, BLUE, "前向", "y_j += x_i * w_ij", "乘 1 次、加 1 次", "2"),
        (250, ORANGE, "反向：传给输入", "dx_i += dy_j * w_ij", "让梯度继续往前传", "2"),
        (460, ORANGE, "反向：给权重", "dw_ij += x_i * dy_j", "优化器要用的梯度", "2"),
    ]
    for x, color, title, formula, note, n in steps:
        body += cbox(x, 70, 190, 150, color)
        body += text(x + 95, 98, title, 16, color, "bold")
        body += mtext(x + 95, 136, formula, 14.5, INK)
        body += text(x + 95, 166, note, 13, GRAY)
        body += text(x + 95, 202, f"{n} 次", 17, color, "bold")
    body += text(355, 254, "每个参数、每个 token：2 + 2 + 2 = 6 次 → 一次训练约 6 × 参数量 N × token 数 D", 15, INK, "bold")
    body += cbox(680, 70, 250, 150, GRAY)
    body += text(805, 96, "实测一步（1024 个 token）", 14.5, INK, "bold")
    for i, d in enumerate(("32", "64", "128")):
        total, no_emb = log["params"][d]
        ratio = log["flops"][d] / (6 * total * log["tokens_per_step"])
        body += text(700, 126 + i * 30, f"宽度 {d}", 13.5, INK, anchor="start")
        body += mtext(910, 126 + i * 30, f"{ratio:.4f}", 13.5, TEAL, "bold", "end")
    body += text(805, 210, "实测 ÷ (6×全部参数×token)", 12, GRAY)
    body += box(40, 282, 890, 96, SOFT[TEAL], TEAL, width=1.6)
    body += text(60, 310, "N 要算哪些参数？", 15, TEAL, "bold", "start")
    body += text(60, 336, "词嵌入表的“查表”不做乘加，但 TinyLLM 的输出层和它共享同一张表（第 5 章），每个 token 都要乘一遍：", 13.5, INK, anchor="start")
    no = log["params"]["32"]
    body += text(60, 360, f"所以全部参数都要算。只算不含嵌入的部分，宽度 32 时会少算 {log['flops']['32'] / (6 * no[1] * log['tokens_per_step']):.1f} 倍。注意力分数那部分运算和序列长度有关，在 64 个 token 时可以忽略。", 13.5, INK, anchor="start")
    svg("scaling-6nd.svg", "训练算力 6ND 的来历",
        "一个权重 w_ij 遇到一个 token：前向时乘一次、加一次，共 2 次；反向时要把梯度传给输入（2 次），还要算这个权重自己的梯度（2 次）。"
        "合计每个参数每个 token 6 次，所以一次训练约 6ND 次浮点运算。用 FlopCounterMode 实测宽度 32、64、128 的一步训练，"
        "和 6 × 全部参数 × token 数的比值都在 0.997 以上；只算不含嵌入的参数会少算很多，因为共享权重的输出层也要乘一遍。", 400, body)


def sl_isoflop():
    """左：三档算力下验证损失随参数量的变化（IsoFLOP 曲线）；右：最优参数量和 token 数随算力的增长。"""
    log = _sl_log()
    if log is None:
        return
    runs, budgets, optima = log["runs"], log["budgets"], log["optima"]
    colors = (TEAL, BLUE, ORANGE)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.8), layout="constrained", gridspec_kw={"width_ratios": [1.35, 1]})
    for C, color, opt in zip(budgets, colors, optima):
        pts = sorted((r for r in runs if r["C"] == C), key=lambda r: r["N"])
        chosen, curve = _sl_parabola(pts)
        a1.plot([r["N"] for r in pts], [r["loss"] for r in pts], "o", color=color, ms=6, alpha=0.9)
        xs = np.exp(np.linspace(np.log(chosen[0]["N"]), np.log(chosen[-1]["N"]), 60))
        a1.plot(xs, curve(xs), "-", color=color, lw=2, label=f"C = {C:.0e}".replace("e+", "e"))
        a1.plot(opt["N"], opt["loss"], "*", color=color, ms=16, mec="white", zorder=4)
        if C == budgets[-1]:
            for r in pts:
                if r["d"] in (16, 32, 128):
                    a1.annotate(f"宽度 {r['d']}，{r['steps']} 步", (r["N"], r["loss"]), textcoords="offset points",
                                xytext=(-4, -16) if r["d"] == 16 else (0, -16), ha="left" if r["d"] == 16 else "center",
                                fontsize=9, color=color)
    a1.set_xscale("log")
    a1.set_ylim(4.5, 6.2)
    a1.set_xlabel("参数量 N（全部参数，对数坐标）")
    a1.set_ylabel("验证损失（衰减完，nats/token）")
    a1.legend(title="每一档的算力", fontsize=10, title_fontsize=10)
    a1.grid(alpha=0.25)
    Cs = np.array(budgets)
    Ns = np.array([o["N"] for o in optima])
    Ds = np.array([o["D"] for o in optima])
    a2.plot(Cs, Ns, "o", color=BLUE, ms=8)
    a2.plot(Cs, Ds, "s", color=ORANGE, ms=8)
    for arr, k, color, name in ((Ns, log["k_N"], BLUE, "最优参数量"), (Ds, log["k_D"], ORANGE, "最优 token 数")):
        kk, bb = np.polyfit(np.log(Cs), np.log(arr), 1)
        xs = np.exp(np.linspace(np.log(Cs[0]) - 0.2, np.log(Cs[-1]) + 0.2, 20))
        a2.plot(xs, np.exp(bb) * xs ** kk, "--", color=color, lw=1.6, label=f"{name} ∝ C^{k:.2f}")
    for C, N, D in zip(Cs, Ns, Ds):
        a2.annotate(f"{D / N:.0f} token/参数", (C, D), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9.5, color=ORANGE)
    a2.set_xscale("log")
    a2.set_yscale("log")
    a2.set_xlabel("训练算力 C（次浮点运算）")
    a2.set_ylabel("抛物线最低点")
    a2.legend(fontsize=10, loc="center right")
    a2.grid(alpha=0.25, which="both")
    o = optima
    save_plot(fig, "scaling-isoflop.svg", "IsoFLOP 曲线与最优参数量",
              f"左：三档算力下，7 个宽度的验证损失随参数量先降后升（单个种子）；对最低点附近拟合抛物线，星号是最低点："
              f"{o[0]['N']:,.0f}、{o[1]['N']:,.0f}、{o[2]['N']:,.0f} 个参数。宽度 128 只能训练十几到六十几步，损失最高。"
              f"右：算力每翻一倍，最优参数量增长较慢（∝ C^{log['k_N']:.2f}），最优 token 数增长较快（∝ C^{log['k_D']:.2f}），"
              f"每个参数分到的 token 从 {o[0]['D'] / o[0]['N']:.0f} 个增加到 {o[2]['D'] / o[2]['N']:.0f} 个。")


def sl_extrapolate():
    """用前两档预测第三档：L(N, D) 的预测曲线、趋势外推的最优点，和实测对照。"""
    log = _sl_log()
    if log is None:
        return
    runs, C = log["runs"], log["budgets"][-1]
    p, opt = log["law"], log["optima"][-1]
    pts = sorted((r for r in runs if r["C"] == C), key=lambda r: r["N"])
    chosen, curve = _sl_parabola(pts)
    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
    xs = np.exp(np.linspace(np.log(pts[0]["N"]) - 0.1, np.log(pts[-1]["N"]) + 0.1, 120))
    ax.plot(xs, p["E"] + p["A"] / xs ** p["alpha"] + p["B"] / (C / (6 * xs)) ** p["beta"], "--", color=BLUE, lw=2,
            label="做法二：只用前两档拟合的 L(N, D)，代入第三档的算力")
    xc = np.exp(np.linspace(np.log(chosen[0]["N"]), np.log(chosen[-1]["N"]), 60))
    ax.plot(xc, curve(xc), "-", color=INK, lw=1.6, label="第三档实测点拟合的抛物线")
    ax.plot([r["N"] for r in pts], [r["loss"] for r in pts], "o", color=INK, ms=7, label="第三档实测（单个种子）", zorder=4)
    lo, hi = opt["N"] / 1.5, opt["N"] * 1.5
    ax.axvspan(lo, hi, color=GRAY, alpha=0.12)
    ax.text(opt["N"], 5.32, f"最低点的 1/1.5～1.5 倍\n损失只高 {curve(lo) - opt['loss']:.3f} / {curve(hi) - opt['loss']:.3f}", ha="center", fontsize=9.5, color=GRAY)
    for N, color, name, y, side in ((opt["N"], INK, "实测抛物线最低点", 4.46, "left"), (log["N_trend"], ORANGE, "做法一：趋势外推", 4.53, "right"),
                                    (log["N_law"], BLUE, "做法二的最低点", 4.46, "right")):
        ax.axvline(N, color=color, lw=1.3, ls=":")
        ax.text(N * (1.03 if side == "left" else 0.97), y, f"{name} {N:,.0f}", ha=side, fontsize=9, color=color)
    ax.set_xscale("log")
    ax.set_ylim(4.42, 5.48)
    ax.set_xlabel("参数量 N（对数坐标）")
    ax.set_ylabel(f"验证损失（C = {C:.0e}）".replace("e+", "e"))
    ax.legend(fontsize=9.5, loc="lower right")
    ax.grid(alpha=0.25)
    errs = [p["E"] + p["A"] / r["N"] ** p["alpha"] + p["B"] / r["D"] ** p["beta"] - r["loss"] for r in pts]
    save_plot(fig, "scaling-extrapolate.svg", "用小预算预测大预算",
              f"只用前两档的数据预测第三档（算力翻倍）。做法一把前两档的最优参数量连成直线外推，得到 {log['N_trend']:,.0f}，"
              f"实测抛物线最低点是 {opt['N']:,.0f}。做法二拟合 L(N, D)，预测的损失和实测相差 {min(errs):+.3f}～{max(errs):+.3f}，"
              f"预测的最低点 {log['N_law']:,.0f} 偏小，但最低点附近很平：参数量在最低点的 1/1.5 到 1.5 倍之间，损失只高 0.02 左右。")


def sl_kaplan():
    """同一批训练，两种记账方式求出的指数，和 Kaplan、Chinchilla 的结论放在一起。"""
    log = _sl_log()
    if log is None:
        return
    rows = [("Kaplan 等，2020（不算嵌入）", 0.73, RED), ("Chinchilla，2022（全部参数）", 0.50, TEAL),
            ("本章：不算词嵌入表", log["kaplan"]["k_kaplan"], RED), ("本章：全部参数", log["k_N"], TEAL)]
    fig, ax = plt.subplots(figsize=(9.5, 3.4), layout="constrained")
    for i, (name, k, color) in enumerate(rows):
        ax.plot([0, k], [i, i], color=color, lw=2.2, alpha=0.5)
        ax.plot(k, i, "o", color=color, ms=11)
        ax.text(k + 0.015, i, f"{k:.2f}", va="center", fontsize=11, color=color, fontweight="bold")
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.set_xlim(0, 0.85)
    ax.invert_yaxis()
    ax.set_xlabel("最优参数量 ∝ C^a 中的指数 a（越大，多出来的算力越多地花在加大模型上）")
    ax.axhline(1.5, color=GRAY, lw=0.8, ls=":")
    ax.grid(alpha=0.25, axis="x")
    save_plot(fig, "scaling-kaplan.svg", "不同记账方式下的缩放指数",
              f"上两行是论文结论：Kaplan 等人不算词嵌入参数，得到 0.73；Chinchilla 算全部参数，得到 0.50。"
              f"下两行是本章同一批训练：按全部参数记账得到 {log['k_N']:.2f}，像 Kaplan 那样不算词嵌入表则变成 {log['kaplan']['k_kaplan']:.2f}，"
              "朝 Kaplan 的方向偏。本章模型很小、词嵌入表占参数的大头，这个偏差尤其明显。")


def sl_inference():
    """训练 + 推理的总算力：生成的 token 越多，越值得用小一点的模型多训。"""
    log = _sl_log()
    if log is None:
        return
    inf = log["inference"]
    rows = inf["rows"]
    fig, ax = plt.subplots(figsize=(10, 4.6), layout="constrained")
    T = np.linspace(0, 12e12, 200)
    colors = (INK, BLUE, TEAL, ORANGE)
    for r, color in zip(rows, colors):
        total = (r["train"] + 2 * r["N"] * T) / 1e24
        ax.plot(T / 1e12, total, color=color, lw=2.2,
                label=f"{r['N'] / 1e9:.0f}B，训练 {r['D'] / 1e12:.1f} 万亿 token（{r['D'] / r['N']:.0f} 个/参数）")
        if r["breakeven"]:
            x = r["breakeven"]
            ax.plot(x / 1e12, (r["train"] + 2 * r["N"] * x) / 1e24, "o", color=color, ms=7)
    ax.set_xlabel("部署后一共生成的 token（万亿）")
    ax.set_ylabel("训练 + 推理的总算力（×10²⁴ 次运算）")
    ax.legend(fontsize=9.5, loc="upper left", title=f"要达到同样的损失 {inf['target']:.3f}", title_fontsize=9.5)
    ax.grid(alpha=0.25)
    r2 = rows[2]
    save_plot(fig, "scaling-inference.svg", "把推理算进总账",
              f"用 Chinchilla 数据的重新拟合（Besiroglu 等，2024）计算：要达到 {rows[0]['N'] / 1e9:.0f}B 算力最优模型的损失，"
              f"{r2['N'] / 1e9:.0f}B 的模型要训练 {r2['D'] / 1e12:.1f} 万亿 token，训练算力多 {r2['train'] / rows[0]['train'] - 1:.0%}，"
              f"但每生成一个 token 只要一半的算力；部署后生成超过 {r2['breakeven'] / 1e12:.1f} 万亿 token，总账就比最优点省。圆点是各条线与黑线的交点。")


# ---------- 第 25 章：大规模训练稳定性 ----------

def _scale_log():
    src = DATA / "tinyllm-large-model-stability-log.json"
    if not src.exists():
        print("skip large-model-stability figures: run scripts/build-tinyllm-code.py large-model-stability to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def scale_instability():
    """学习率扫描：验证损失与注意力分数的最大值。"""
    log = _scale_log()
    if log is None:
        return
    lrs = log["lrs"]
    styles = {"原样": (GRAY, "o"), "加 QK Norm": (TEAL, "s"), "加 z-loss": (ORANGE, "^")}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.4), layout="constrained")
    for name, rows in log["sweep"].items():
        color, marker = styles[name]
        a1.plot(lrs, [r["val"] for r in rows], color=color, marker=marker, lw=2.2, ms=7, label=name)
        a2.plot(lrs, [r["attn"] for r in rows], color=color, marker=marker, lw=2.2, ms=7, label=name)
    for ax in (a1, a2):
        ax.set_xscale("log")
        ax.axvline(1e-2, color=BLUE, ls="--", lw=1)
        ax.set_xlabel("峰值学习率（虚线是主线 1e-2）")
        ax.grid(alpha=0.25)
    a1.set_ylabel("最终验证损失")
    a1.set_title("学习率变大时，QK Norm 坏得慢得多", fontsize=12.5)
    a1.legend(fontsize=10.5, loc="upper left")
    a2.set_yscale("log")
    a2.set_ylabel("注意力分数绝对值的最大值")
    a2.set_title("原样时注意力分数一路涨到十万以上", fontsize=12.5)
    base, qk = log["sweep"]["原样"], log["sweep"]["加 QK Norm"]
    save_plot(fig, "scale-instability.svg", "在小模型上用大学习率复现不稳定",
              f"左：峰值学习率从 3e-3 扫到 3e-1。主线 1e-2 附近三种设置差不多；学习率更大时，原样和加 z-loss 迅速变差（3e-1 时 {base[-1]['val']:.2f}），"
              f"加 QK Norm 变差得慢得多（{qk[-1]['val']:.2f}）。右：注意力分数（softmax 之前）的最大值。原样时从 {base[1]['attn']:.0f} 涨到 {base[-1]['attn']:.3g}；"
              f"QK Norm 把它压在 {qk[-1]['attn']:.0f} 以内。z-loss 管的是输出 logits，对注意力分数没有作用。")


def scale_mup():
    """标准参数化与 μP：不同宽度下验证损失随学习率的变化。"""
    log = _scale_log()
    if log is None:
        return
    lrs = log["mup_lrs"]
    colors = {"32": ORANGE, "64": GRAY, "128": BLUE}
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), layout="constrained", sharey=True)
    bests = {}
    for ax, kind, title in ((axes[0], "SP", "标准参数化：最佳学习率随宽度漂移"), (axes[1], "μP", "μP：最佳学习率不随宽度变")):
        for d, vals in log["mup"][kind].items():
            ax.plot(lrs, vals, color=colors[d], marker="o", lw=2.2, label=f"宽度 {d}")
            b = int(np.argmin(vals))
            ax.scatter([lrs[b]], [vals[b]], s=180, facecolor="none", edgecolor=colors[d], lw=2.2, zorder=4)
            bests[(kind, d)] = lrs[b]
        ax.set_xscale("log")
        ax.set_xlabel("峰值学习率（120 步，单个种子；圆圈是最好的一点）")
        ax.set_title(title, fontsize=12.5)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=10.5, loc="upper center")
    axes[0].set_ylabel("验证损失")
    axes[0].set_ylim(4.95, 6.1)
    save_plot(fig, "scale-mup.svg", "标准参数化与 μP 的学习率迁移",
              f"左：标准参数化下，宽度 32、64、128 的最佳学习率分别是 {bests[('SP', '32')]:.0e}、{bests[('SP', '64')]:.0e}、{bests[('SP', '128')]:.0e}，宽度每翻一倍，最佳学习率就往小移一档（网格每档约 3 倍）。"
              f"右：μP 下三种宽度的最佳学习率都是 {bests[('μP', '64')]:.0e}，而且同一个学习率下，宽度越大验证损失越低。宽度 64 是基准宽度，两种参数化在这里完全相同。")


def scale_memory():
    """70 亿参数、8 张卡：数据并行与 ZeRO 各阶段每张卡的显存（不含激活）。"""
    log = _scale_log()
    if log is None:
        return
    mem = log["memory"]
    names = list(mem)
    fig, ax = plt.subplots(figsize=(10, 3.6), layout="constrained")
    left = np.zeros(len(names))
    for j, (part, color) in enumerate((("参数（BF16）", BLUE), ("梯度（BF16）", TEAL), ("优化器状态（FP32 主权重、m、v）", ORANGE))):
        vals = np.array([mem[n][j] for n in names])
        ax.barh(range(len(names)), vals, left=left, color=color, alpha=0.85, label=part, height=0.6)
        left += vals
    for i, n in enumerate(names):
        ax.text(left[i] + 1.5, i, f"{left[i]:.1f} GB", va="center", fontsize=11)
    ax.axvline(80, color=RED, ls="--", lw=1.2)
    ax.text(81, 0.5, "一张 80 GB 的卡", color=RED, fontsize=10.5, va="center")
    ax.set_yticks(range(len(names)), names, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlabel("每张卡要放的训练状态（GB，不含激活）")
    ax.set_xlim(0, max(left) * 1.15)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(alpha=0.25, axis="x")
    save_plot(fig, "scale-memory.svg", "ZeRO 各阶段的显存",
              f"70 亿参数、8 张卡，混合精度每个参数 16 字节。普通数据并行每张卡放一整份，{sum(mem[names[0]]):.0f} GB，超过一张 80 GB 的卡；"
              f"ZeRO-1 把优化器状态切成 8 份，降到 {sum(mem[names[1]]):.1f} GB；ZeRO-2 再切梯度，{sum(mem[names[2]]):.1f} GB；ZeRO-3 / FSDP 连参数也切，{sum(mem[names[3]]):.1f} GB。")


def scale_parallel():
    """三种并行方式：每张卡放什么、在哪里通信。"""
    body = text(500, 40, "三种把训练分到多张卡上的方式（以 2 张卡为例）", 22, weight="bold")
    cols = [(170, "数据并行", BLUE, ["完整的模型", "完整的模型"], ["batch 前一半", "batch 后一半"],
             "反向后：all-reduce 梯度", "每张卡要放得下整个模型"),
            (500, "ZeRO-3 / FSDP", TEAL, ["参数、梯度、优化器的 1/2", "参数、梯度、优化器的 1/2"], ["batch 前一半", "batch 后一半"],
             "每层用前 all-gather 参数，反向后 reduce-scatter 梯度", "通信更多，换来显存除以卡数"),
            (830, "张量并行", ORANGE, ["每个矩阵的一半", "每个矩阵的一半"], ["同一个 batch", "同一个 batch"],
             "每个子层后：all-reduce 激活", "通信频繁，适合同一台机器内")]
    for cx, title, color, holds, data, comm, note in cols:
        body += text(cx, 84, title, 18, color, "bold")
        for r in range(2):
            y = 104 + r * 120
            body += cbox(cx - 140, y, 280, 96, color)
            body += text(cx, y + 24, f"卡 {r}", 14, GRAY)
            body += text(cx, y + 50, holds[r], 15, INK, "bold")
            body += text(cx, y + 76, "数据：" + data[r], 13.5, GRAY)
        body += f'<path d="M{cx - 150} 168 C {cx - 175} 190, {cx - 175} 230, {cx - 150} 252" stroke="{RED}" stroke-width="2.4" fill="none" marker-end="url(#arrow-{RED[1:]})" marker-start="url(#arrow-{RED[1:]})"/>'
        body += text(cx, 360, comm, 13.5, RED)
        body += text(cx, 386, note, 13.5, GRAY)
    svg("scale-parallel.svg", "数据并行、ZeRO-3/FSDP 与张量并行",
        "数据并行：每张卡放完整的模型，各算 batch 的一部分，反向后 all-reduce 梯度。ZeRO-3/FSDP：每张卡只放参数、梯度、优化器状态的一部分，"
        "每层用之前 all-gather 参数，反向后 reduce-scatter 梯度。张量并行：每个矩阵切开放在不同的卡上，所有卡处理同一个 batch，每个子层之后 all-reduce 激活。", 410, body, width=1000)


# ---------- 第 26 章：稀疏专家（MoE） ----------

def _moe_log():
    src = DATA / "tinyllm-mixture-of-experts-log.json"
    if not src.exists():
        print("skip mixture-of-experts figures: run scripts/build-tinyllm-code.py mixture-of-experts to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def moe_structure():
    """稠密前馈层与 MoE 层：路由器选 2 个专家，按分数加权求和。"""
    body = text(500, 40, "把一个前馈层换成 8 个专家：每个 token 只用其中 2 个", 22, weight="bold")
    # 左：稠密
    body += text(150, 84, "稠密前馈层", 18, BLUE, "bold")
    body += mtext(150, 116, "x（一个 token）", 15)
    body += arrow(150, 124, 150, 150, GRAY)
    body += cbox(60, 152, 180, 64, BLUE) + text(150, 182, "SwiGLU", 17, BLUE, "bold") + text(150, 204, "每个 token 都用全部参数", 13, GRAY)
    body += arrow(150, 216, 150, 244, GRAY)
    body += mtext(150, 264, "输出", 15)
    body += f'<line x1="300" y1="70" x2="300" y2="440" stroke="#e2e8f0" stroke-width="2"/>'
    # 右：MoE
    cx = 650
    body += text(cx, 84, "MoE 层（本章：8 个专家，每个 token 选 2 个）", 18, TEAL, "bold")
    body += mtext(cx, 116, "x（一个 token）", 15)
    body += arrow(cx, 124, cx, 146, GRAY)
    body += cbox(cx - 150, 148, 300, 52, ORANGE) + text(cx, 172, "路由器：Linear(d → 8) + softmax", 15, ORANGE, "bold") + text(cx, 192, "给 8 个专家各打一个分，选最高的 2 个", 12.5, GRAY)
    xs = [cx - 331 + i * 84 for i in range(8)]
    picked = {1, 5}
    for i, x in enumerate(xs):
        on = i in picked
        body += (path(f"M{cx} 200 L{x + 40} 252", TEAL, 2.4) if on else
                 f'<line x1="{cx}" y1="200" x2="{x + 40}" y2="252" stroke="#cbd5e1" stroke-width="1.2"/>')
        body += box(x + 3, 254, 74, 60, SOFT[TEAL] if on else "#ffffff", TEAL if on else "#cbd5e1", width=2.4 if on else 1.4)
        body += text(x + 40, 280, f"专家 {i}", 14, TEAL if on else GRAY, "bold" if on else "normal")
        body += text(x + 40, 302, "SwiGLU", 12, GRAY)
        if on:
            body += path(f"M{x + 40} 314 L{cx} 360", TEAL, 2.4)
    body += text(xs[1] + 40, 336, "× 0.62", 13, TEAL, "bold")
    body += text(xs[5] + 40, 336, "× 0.38", 13, TEAL, "bold")
    body += circle(cx, 374, 15) + text(cx, 381, "+", 21, weight="bold")
    body += arrow(cx, 389, cx, 410, GRAY)
    body += mtext(cx, 428, "输出 = 两个专家输出的加权和", 15)
    body += text(500, 470, "前馈层的参数变成 8 份，每个 token 只算其中 2 份；没被选中的 6 个专家这次完全不参与计算", 14.5, INK)
    svg("moe-structure.svg", "稠密前馈层与 MoE 层",
        "左：稠密前馈层，每个 token 都经过同一个 SwiGLU。右：MoE 层，路由器给 8 个专家打分，每个 token 只选分数最高的 2 个专家，"
        "两个专家的输出按归一化后的分数加权相加；没被选中的专家不参与这次计算。", 495, body, width=1000)


def moe_compare():
    """MoE 与三种稠密模型、稀疏升级：3 个种子的验证损失。"""
    log = _moe_log()
    if log is None:
        return
    r = log["results"]
    rows = [("稠密（主线）", GRAY), ("稠密，激活参数相同", BLUE), ("稠密，总参数相同", BLUE), ("MoE，不均衡", ORANGE),
            ("MoE，辅助损失", TEAL), ("MoE，偏置均衡", TEAL), ("稀疏升级", PURPLE)]
    fig, ax = plt.subplots(figsize=(10, 4.2), layout="constrained")
    for i, (name, color) in enumerate(rows):
        vals = r[name]
        m = sum(vals) / len(vals)
        ax.plot([min(vals), max(vals)], [i, i], color=color, lw=6, alpha=0.35, solid_capstyle="round")
        ax.scatter(vals, [i] * len(vals), color=color, s=22, zorder=3)
        ax.scatter([m], [i], color=color, s=90, marker="D", zorder=4)
        busy = r.get(name + "·最忙")
        note = f"{m:.3f}" + (f"   最忙专家 {max(busy):.0%}" if busy else "")
        ax.text(max(vals) + 0.006, i, note, va="center", fontsize=10.5, color=color)
    ax.set_yticks(range(len(rows)), [n for n, _ in rows], fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel("验证损失（3 个种子；菱形是平均，横条是范围）")
    lo, hi = ax.get_xlim()
    ax.set_xlim(lo, hi + 0.06)
    ax.grid(alpha=0.25, axis="x")
    mean = lambda k: sum(r[k]) / len(r[k])
    save_plot(fig, "moe-compare.svg", "MoE 与稠密模型的对照",
              f"代理模型、240 步、3 个种子。主线稠密模型 {mean('稠密（主线）'):.3f}；激活参数相同的稠密 {mean('稠密，激活参数相同'):.3f}、总参数相同的稠密 {mean('稠密，总参数相同'):.3f}、"
              f"三种均衡方式的 MoE（{mean('MoE，不均衡'):.3f}、{mean('MoE，辅助损失'):.3f}、{mean('MoE，偏置均衡'):.3f}）和稀疏升级（{mean('稀疏升级'):.3f}）的范围互相重叠，"
              "在这个尺度上分不出高下。不均衡时最忙的专家拿走四成多的选择，偏置均衡时只有 14%。")


def moe_routing():
    """偏置均衡的 MoE：每类 token 的第一选择落在哪个专家上。"""
    log = _moe_log()
    if log is None:
        return
    rt = log["routing"]
    classes = ["逗号", "句号", "<eos>", "其余（汉字）"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), layout="constrained")
    for layer, ax in enumerate(axes):
        mat = np.array([rt[f"{layer}|{c}"] for c in classes]) * 100
        im = ax.imshow(mat, cmap="Blues", vmin=0, vmax=100, aspect="auto")
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center", fontsize=10, color="white" if mat[i, j] > 60 else INK)
        ax.set_xticks(range(8), [f"专家{j}" for j in range(8)], fontsize=10)
        ax.set_yticks(range(len(classes)), classes, fontsize=11)
        ax.set_title(f"第 {layer} 层", fontsize=12.5)
    fig.colorbar(im, ax=axes, label="这类 token 里选它的比例（%）", shrink=0.9)
    save_plot(fig, "moe-routing.svg", "专家的分工",
              "偏置均衡的 MoE（种子 0）在验证集上的路由：每格是这一类 token 把第一选择给了哪个专家的比例。两层里，逗号、句号、<eos> 各自几乎全部交给一个固定的专家，"
              "汉字则分散在其余专家上。")


def moe_upcycle():
    """稀疏升级：把稠密前馈层复制成 8 个专家，加一个路由器，接着训练。"""
    log = _moe_log()
    if log is None:
        return
    r, sim = log["results"], log["similarity"]
    mean = lambda k: sum(r[k]) / len(r[k])
    body = text(500, 40, "稀疏升级：训练到一半的稠密模型，改成 MoE 接着训练", 22, weight="bold")
    body += cbox(60, 90, 220, 70, BLUE) + text(170, 120, "稠密模型训练到第 120 步", 15, BLUE, "bold") + text(170, 144, "参数 + 优化器状态", 13, GRAY)
    body += arrow(280, 125, 340, 125, GRAY)
    body += cbox(345, 82, 300, 86, ORANGE) + text(495, 108, "每层：前馈层复制 8 份 → 8 个专家", 14.5, ORANGE, "bold")
    body += text(495, 130, "新加路由器（随机、几乎均匀）", 13, GRAY) + text(495, 152, "Adam 的 m、v 也复制给每个专家", 13, GRAY)
    body += arrow(645, 125, 705, 125, GRAY)
    body += cbox(710, 90, 230, 70, TEAL) + text(825, 120, "MoE 接着训练到第 240 步", 15, TEAL, "bold") + text(825, 144, "和稠密模型同样的数据与调度", 13, GRAY)
    body += box(60, 196, 880, 64, "#ffffff", "#cbd5e1")
    body += text(500, 222, "升级那一刻：8 个专家一模一样，选哪 2 个、权重多少，加权和都等于原来的前馈层", 15)
    body += text(500, 246, "所以输出和稠密模型完全相同，验证损失一点不变：不用从头训练", 15, TEAL, "bold")
    body += text(500, 300, f"接着训练 120 步后（3 个种子）：稀疏升级 {mean('稀疏升级'):.3f}，稠密 {mean('稠密（主线）'):.3f}，从头训练的 MoE {mean('MoE，偏置均衡'):.3f}", 15)
    body += text(500, 328, f"专家之间的平均相似度：稀疏升级 {sim['upcycled']:.2f}，从头训练约为 0（{sim['scratch']:.3f}）：从同一个起点出发，专家分化得慢", 15, ORANGE)
    svg("moe-upcycle.svg", "稀疏升级的过程",
        "稠密模型训练到第 120 步后，每层的前馈层复制成 8 个一模一样的专家，新加一个路由器，Adam 的状态也一起复制，然后作为 MoE 接着训练到第 240 步。"
        f"升级那一刻输出和稠密模型完全相同。接着训练后，稀疏升级 {mean('稀疏升级'):.3f}，稠密 {mean('稠密（主线）'):.3f}，从头训练的 MoE {mean('MoE，偏置均衡'):.3f}；"
        f"专家之间的平均相似度，稀疏升级是 {sim['upcycled']:.2f}，从头训练约为 0。", 350, body, width=1000)


def moe_serving():
    """真实模型：权重显存与每 token 读的权重；批量变大时用到的专家比例。"""
    log = _moe_log()
    if log is None:
        return
    real, cov = log["real"], log["coverage"]
    names = list(real)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), layout="constrained", gridspec_kw={"width_ratios": [1.2, 1]})
    y = np.arange(len(names))
    a1.barh(y - 0.2, [real[n][0] * 2 / 1e9 for n in names], height=0.38, color=GRAY, alpha=0.8, label="要装进显存的权重（总参数）")
    a1.barh(y + 0.2, [real[n][1] * 2 / 1e9 for n in names], height=0.38, color=TEAL, alpha=0.9, label="每生成一个 token 读的权重（激活参数，批量 1）")
    a1.set_xscale("log")
    a1.set_yticks(y, names, fontsize=10.5)
    a1.invert_yaxis()
    a1.set_xlabel("GB（BF16，对数坐标）")
    a1.legend(fontsize=9.5, loc="upper right")
    a1.grid(alpha=0.25, axis="x")
    a1.set_title("显存看总参数，速度看激活参数", fontsize=12.5)
    batches = [1, 4, 16, 64, 256]
    for (name, c), color in zip(cov.items(), (ORANGE, BLUE, TEAL, RED)):
        a2.plot(batches, [100 * v for v in c], marker="o", lw=2, color=color, label=name, ls="--" if name == "DeepSeek-V3" else "-")
    a2.set_xscale("log")
    a2.set_xticks(batches, [str(b) for b in batches])
    a2.set_xlabel("同时解码的 token 数（批量）")
    a2.set_ylabel("一层里被用到的专家（%）")
    a2.set_title("批量一大，几乎所有专家都要读", fontsize=12.5)
    a2.legend(fontsize=9.5, loc="lower right")
    a2.grid(alpha=0.25)
    q = real["Qwen3-30B-A3B"]
    save_plot(fig, "moe-serving.svg", "MoE 的推理账",
              f"左：五个公开模型 BF16 权重的大小（总参数）和批量为 1 时每生成一个 token 要读的权重（激活参数）。Qwen3-30B-A3B 要装下 {q[0] * 2 / 1e9:.0f} GB，每个 token 只读 {q[1] * 2 / 1e9:.1f} GB。"
              "右：假设路由均匀独立，批量变大时一层里至少被一个 token 选中的专家比例；Qwen3-30B-A3B 在批量 64 时已经接近全部，单用户时的带宽优势在高并发下基本消失。")


# ---------- 第 29 章：注意力内核与算子融合 ----------

def _kernels_log():
    src = DATA / "tinyllm-attention-kernels-log.json"
    if not src.exists():
        print("skip attention-kernels figures: run scripts/build-tinyllm-code.py attention-kernels to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def kernels_memory():
    """朴素注意力与 SDPA 的峰值内存；朴素与分块的读写字节数。"""
    log = _kernels_log()
    if log is None:
        return
    mem, tr = log["memory"], log["traffic"]
    Ts = [r["T"] for r in mem]
    mib = lambda b: b / 2**20
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), layout="constrained")
    a1.plot(Ts, [mib(r["naive_peak"]) for r in mem], marker="o", lw=2.2, color=RED, label="朴素写法")
    a1.plot(Ts, [mib(r["table"]) for r in mem], ls="--", lw=1.6, color=GRAY, label="一张 T×T 分数表")
    a1.plot(Ts, [mib(r["sdpa_peak"]) for r in mem], marker="o", lw=2.2, color=TEAL, label="scaled_dot_product_attention")
    for r in mem:
        a1.annotate(f"{mib(r['naive_peak']):.1f}" if mib(r["naive_peak"]) < 10 else f"{mib(r['naive_peak']):.0f}", (r["T"], mib(r["naive_peak"])), textcoords="offset points", xytext=(-6, 8), fontsize=10, color=RED, ha="right")
        a1.annotate(f"{mib(r['sdpa_peak']):.2f}", (r["T"], mib(r["sdpa_peak"])), textcoords="offset points", xytext=(-6, 8), fontsize=10, color=TEAL, ha="right")
    a1.set_xscale("log", base=2)
    a1.set_yscale("log")
    a1.set_xticks(Ts, [str(t) for t in Ts])
    a1.set_xlabel("序列长度 T")
    a1.set_ylabel("中间张量峰值（MiB，对数）")
    a1.set_title("峰值：朴素写法随 T² 增长", fontsize=12.5)
    a1.legend(fontsize=9.5, loc="upper left")
    a1.grid(alpha=0.25)
    Ts2 = [r["T"] for r in tr]
    a2.plot(Ts2, [mib(r["naive"]) for r in tr], marker="o", lw=2.2, color=RED, label="朴素写法")
    for blk, color in (("16", ORANGE), ("64", BLUE), ("256", TEAL)):
        a2.plot(Ts2, [mib(r[blk]) for r in tr], marker="o", lw=2, color=color, label=f"分块，块大小 {blk}")
    last = tr[-1]
    for key, color in (("naive", RED), ("16", ORANGE), ("64", BLUE), ("256", TEAL)):
        a2.annotate(f"{mib(last[key]):.0f}", (last["T"], mib(last[key])), textcoords="offset points", xytext=(6, -4), fontsize=10, color=color)
    a2.set_xscale("log", base=2)
    a2.set_yscale("log")
    a2.set_xticks(Ts2, [str(t) for t in Ts2])
    a2.set_xlim(Ts2[0] * 0.8, Ts2[-1] * 1.7)
    a2.set_xlabel("序列长度 T")
    a2.set_ylabel("读写字节（MiB，对数）")
    a2.set_title("读写：块越大，K、V 被重读得越少", fontsize=12.5)
    a2.legend(fontsize=9.5, loc="upper left")
    a2.grid(alpha=0.25)
    m4, t4 = mem[-1], tr[-1]
    save_plot(fig, "kernels-memory.svg", "朴素注意力与分块注意力的内存账",
              f"batch 1、4 个头、每头 32 维、FP32，在算子层面记账。左：中间张量的峰值。T=4096 时朴素写法 {mib(m4['naive_peak']):.0f} MiB（一张分数表 {mib(m4['table']):.0f} MiB），"
              f"scaled_dot_product_attention 只有 {mib(m4['sdpa_peak']):.2f} MiB，几乎就是输出本身。右：读写的字节数。T=4096 时朴素写法 {mib(t4['naive']):.0f} MiB，"
              f"分块写法块大小 16、64、256 时分别是 {mib(t4['16']):.0f}、{mib(t4['64']):.0f}、{mib(t4['256']):.0f} MiB。")


def kernels_online():
    """online softmax：一行 64 个分数分 4 块到来，最大值与指数和怎样更新。"""
    log = _kernels_log()
    if log is None:
        return
    trace = log["online"]
    body = text(480, 38, "online softmax：一行分数分 4 块到来，每块只看 16 个", 21, weight="bold")
    heads = ["分数", "本块最大", "目前最大 m", "校正系数 e^(m旧−m新)", "指数和 ℓ"]
    xs = [120, 290, 450, 650, 840]
    for x, h in zip(xs, heads):
        body += text(x, 86, h, 15, GRAY, "bold")
    for i, (start, bmax, m, alpha, l) in enumerate(trace):
        y = 126 + i * 50
        raised = i > 0 and m > trace[i - 1][2]
        color = ORANGE if raised else INK
        body += box(40, y - 26, 880, 42, SOFT[ORANGE] if raised else "#ffffff", ORANGE if raised else "#e2e8f0", width=1.5)
        body += text(xs[0], y, f"第 {start}–{start + 15} 个", 15)
        body += text(xs[1], y, f"{bmax:.3f}", 15, color)
        body += text(xs[2], y, f"{m:.3f}", 15, color, "bold" if raised else "normal")
        body += text(xs[3], y, f"{alpha:.3f}", 15, color, "bold" if raised else "normal")
        body += text(xs[4], y, f"{l:.3f}", 15)
    body += text(480, 340, "橙色行：新的一块出现了更大的分数，旧的 ℓ 和加权和都乘以校正系数，换到新的基准上", 15, ORANGE)
    body += text(480, 368, "第一块之前什么都没有，校正系数是 0；最后输出 = 加权和 ÷ ℓ，与先算完整 softmax 的结果只差浮点舍入", 15)
    svg("kernels-online.svg", "online softmax 的更新过程",
        "第 0 层、第 0 句、第 0 个头最后一个位置的 64 个分数，分成 4 块、每块 16 个依次处理。每块之后更新目前的最大值 m 和以 m 为基准的指数和 ℓ；"
        "出现更大的分数时，旧的指数和与加权和乘以校正系数 e^(m旧−m新)。第三、四块各提高了一次最大值，校正系数分别是 "
        f"{trace[2][3]:.3f} 和 {trace[3][3]:.3f}。", 392, body)


def kernels_tiling():
    """分块注意力：4×4 个方块，因果掩码跳过右上方 6 块；数据在主存与片上之间怎样搬。"""
    log = _kernels_log()
    if log is None:
        return
    done, skipped = log["tiles_per_head"]
    body = text(500, 38, "分块注意力：一次只在片上算一个 16×16 的方块", 21, weight="bold")
    x0, y0, c = 110, 110, 62
    body += text(x0 + 2 * c, y0 - 34, "K、V 的块 j →", 15, GRAY)
    body += f'<text x="{x0 - 46}" y="{y0 + 2 * c}" font-size="15" fill="{GRAY}" text-anchor="middle" transform="rotate(-90 {x0 - 46} {y0 + 2 * c})">Q 的块 i →</text>'
    for i in range(4):
        body += text(x0 - 16, y0 + i * c + c / 2 + 5, str(i), 14, GRAY)
        body += text(x0 + i * c + c / 2, y0 - 10, str(i), 14, GRAY)
        for j in range(4):
            x, y = x0 + j * c, y0 + i * c
            if j > i:
                body += f'<rect x="{x + 3}" y="{y + 3}" width="{c - 6}" height="{c - 6}" rx="6" fill="#ffffff" stroke="#cbd5e1" stroke-dasharray="5 4" stroke-width="1.5"/>'
                body += text(x + c / 2, y + c / 2 + 5, "跳过", 13, GRAY)
            else:
                diag = j == i
                fill = SOFT[ORANGE] if diag else SOFT[TEAL]
                stroke = ORANGE if diag else TEAL
                body += f'<rect x="{x + 3}" y="{y + 3}" width="{c - 6}" height="{c - 6}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
                if diag:
                    body += f'<path d="M{x + 3} {y + 3} L{x + c - 3} {y + c - 3} L{x + c - 3} {y + 3} Z" fill="#ffffff" opacity="0.85"/>'
                body += text(x + c / 2 - (8 if diag else 0), y + c / 2 + (14 if diag else 5), "算", 13, stroke, "bold")
    body += f'<rect x="{x0 - 2}" y="{y0 + 2 * c - 2}" width="{4 * c + 4}" height="{c + 4}" rx="8" fill="none" stroke="{BLUE}" stroke-width="2.5"/>'
    body += text(x0 + 2 * c, y0 + 4 * c + 30, f"每个头 16 块：算 {done} 块，跳过 {skipped} 块", 15, INK, "bold")
    body += text(x0 + 2 * c, y0 + 4 * c + 54, "对角线上的块只算左下半（橙色），其余整块可见（绿色）", 13.5, GRAY)
    # 右：一行 Q 块的处理过程
    rx = 450
    body += text(rx + 250, 92, "蓝框那一行（Q 块 2）怎样走", 16, BLUE, "bold")
    body += cbox(rx, 108, 500, 74, GRAY) + text(rx + 250, 132, "主存（显存 / 内存）：完整的 Q、K、V，最后写回输出 O 和每行的 lse", 14)
    body += text(rx + 250, 158, "容量大、读写慢", 13, GRAY)
    body += cbox(rx, 240, 500, 128, TEAL) + text(rx + 250, 264, "片上快速存储（GPU 的共享内存 / CPU 的缓存）", 14, TEAL, "bold")
    body += text(rx + 250, 290, "Q 块 2 常驻；每行的 m、ℓ 和加权和 o", 14)
    body += text(rx + 250, 314, "依次放进 K、V 的块 0、1、2，算一个 16×16 的分数块", 14)
    body += text(rx + 250, 338, "用 online softmax 更新 m、ℓ、o，分数块用完即弃", 14)
    body += text(rx + 250, 358, "容量小、读写快", 13, GRAY)
    body += f'<line x1="{rx + 120}" y1="184" x2="{rx + 120}" y2="236" stroke="{BLUE}" stroke-width="2.5"/>'
    body += text(rx + 112, 214, "读 Q 块、K/V 块", 13, BLUE, anchor="end")
    body += f'<line x1="{rx + 380}" y1="184" x2="{rx + 380}" y2="236" stroke="{ORANGE}" stroke-width="2.5"/>'
    body += text(rx + 388, 214, "只写回 O 块和 lse", 13, ORANGE, anchor="start")
    body += text(rx + 250, 400, "T×T 的分数表从头到尾没有完整出现在主存里", 15, TEAL, "bold")
    svg("kernels-tiling.svg", "分块注意力的计算顺序",
        f"左：64 个位置按 16 切成 4×4 个方块。因果掩码让对角线右上方的 {skipped} 块整块不用算，对角线上的块只算左下半，一共算 {done} 块。"
        "右：处理一行 Q 块时，Q 块常驻片上，K、V 的块依次读进来，每次只算一个 16×16 的分数块，用 online softmax 更新每行的最大值、指数和与加权和；"
        "最后只把输出块和每行一个 lse 写回主存。", 440, body, width=1000)


def kernels_fusion():
    """逐元素小算子：eager 实际读写与融合后的下限。"""
    log = _kernels_log()
    if log is None:
        return
    rows, comp = log["fusion"], log.get("compile")
    fig, ax = plt.subplots(figsize=(10, 3.6), layout="constrained")
    y = np.arange(len(rows))
    mib = lambda b: b / 2**20
    ax.barh(y - 0.19, [mib(r["traffic"]) for r in rows], height=0.36, color=RED, alpha=0.75, label="eager：每个算子各读一遍输入、写一遍输出")
    ax.barh(y + 0.19, [mib(r["lower"]) for r in rows], height=0.36, color=TEAL, alpha=0.85, label="融合后的下限：输入读一次、输出写一次")
    for i, r in enumerate(rows):
        ax.text(mib(r["traffic"]) + 0.15, i - 0.19, f"{mib(r['traffic']):.2f} MiB（{r['ops']} 个算子，{r['traffic'] / r['lower']:.1f} 倍）", va="center", fontsize=10.5, color=RED)
        ax.text(mib(r["lower"]) + 0.15, i + 0.19, f"{mib(r['lower']):.2f} MiB", va="center", fontsize=10.5, color=TEAL)
    ax.set_yticks(y, [r["name"] for r in rows], fontsize=12)
    ax.invert_yaxis()
    ax.set_xlabel("读写字节（MiB），一个训练 batch：32 × 64 个位置")
    ax.set_xlim(0, max(mib(r["traffic"]) for r in rows) * 1.55)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(alpha=0.25, axis="x")
    note = f"整层 Block：eager 调用 {comp['eager_ops']} 个算子，torch.compile 生成 {len(comp['fused'])} 个融合内核。" if comp else ""
    save_plot(fig, "kernels-fusion.svg", "逐元素小算子的读写",
              "RMSNorm、RoPE、SiLU 门控在 eager 模式下实际读写的字节数（每个算子读一遍输入、写一遍输出），以及把它们融合成一个内核后的下限。"
              + "，".join(f"{r['name']} {r['ops']} 个算子、多搬 {r['traffic'] / r['lower']:.1f} 倍" for r in rows) + "。" + note)


# ---------- 第 30 章：量化 ----------

def _quant_log():
    src = DATA / "tinyllm-quantization-log.json"
    if not src.exists():
        print("skip quantization figures: run scripts/build-tinyllm-code.py quantization to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def quant_levels():
    """INT4 的刻度：嵌入行用对称量化；SiLU 输出对称与非对称的差别。"""
    log = _quant_log()
    if log is None:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.9), layout="constrained")
    row = np.array(log["row"])
    a1.hist(row, bins=40, color=BLUE, alpha=0.55)
    for v in log["row_levels"]:
        a1.axvline(v, color=ORANGE, lw=1, alpha=0.8)
    a1.set_title("嵌入表“，”这一行：INT4 对称，15 个刻度", fontsize=12.5)
    a1.set_xlabel("数值")
    a1.set_ylabel("个数")
    h = log["act_hist"]
    edges, counts = np.array(h["edges"]), np.array(h["counts"])
    a2.bar(edges[:-1], counts, width=np.diff(edges), align="edge", color=TEAL, alpha=0.55)
    a2.set_yscale("log")
    ymax = counts.max() * 3
    for v in log["act_levels"]["sym"]:
        a2.plot([v, v], [ymax * 0.25, ymax], color=RED, lw=1.4)
    for v in log["act_levels"]["asym"]:
        a2.plot([v, v], [0.5, 1.6], color=ORANGE, lw=1.4)
    a2.set_ylim(0.5, ymax)
    a2.text(edges[-1], ymax * 0.5, f"对称：实际用到 {len(log['act_levels']['sym'])} 个刻度（红，上）", ha="right", fontsize=10.5, color=RED)
    a2.text(edges[-1], 2.4, f"非对称：用满 {len(log['act_levels']['asym'])} 个刻度（橙，下）", ha="right", fontsize=10.5, color=ORANGE)
    a2.set_title("第 0 层 SiLU 输出：负的一侧很短", fontsize=12.5)
    a2.set_xlabel("数值")
    a2.set_ylabel("个数（对数）")
    save_plot(fig, "quant-levels.svg", "INT4 量化的刻度",
              "左：种子 0 的嵌入表中“，”那一行的 128 个数，大致关于 0 对称，INT4 对称量化的刻度（橙色竖线）均匀覆盖两侧。"
              f"右：第 0 层 SiLU 门控的输出，最小约 −0.28，最大约 7。对称量化按绝对值最大的一侧定刻度，负半边几乎用不上，实际只用到 {len(log['act_levels']['sym'])} 个刻度；"
              f"非对称量化用最小值和最大值定范围，{len(log['act_levels']['asym'])} 个刻度全部用上。")


def quant_granularity():
    """各种量化方案：每个权重的位数、相对误差；3 个种子上的验证损失增量。"""
    log = _quant_log()
    if log is None:
        return
    g, res, base = log["granularity"], log["results"], log["base_loss"]
    names = [r["scheme"] for r in g]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2), layout="constrained", gridspec_kw={"width_ratios": [1, 1.15]})
    y = np.arange(len(names))
    colors = [GRAY if n.startswith("INT8") else (RED if "按张量" in n or n.startswith("INT3") else TEAL) for n in names]
    a1.barh(y, [r["rel_err"] * 100 for r in g], color=colors, alpha=0.75)
    for i, r in enumerate(g):
        a1.text(r["rel_err"] * 100 + 0.4, i, f"{r['rel_err']:.1%}，{r['bpw']:.2f} 位/权重", va="center", fontsize=10)
    a1.set_yticks(y, names, fontsize=11)
    a1.invert_yaxis()
    a1.set_xlim(0, max(r["rel_err"] for r in g) * 100 * 1.6)
    a1.set_xlabel("权重的相对误差（%，种子 0）")
    a1.set_title("单位越小，误差越小，位数略多", fontsize=12.5)
    seeds = sorted(base)
    for i, n in enumerate(names):
        dl = [res[n][j][0] - base[s] for j, s in enumerate(seeds)]
        a2.plot([min(dl), max(dl)], [i, i], color=colors[i], lw=6, alpha=0.35, solid_capstyle="round")
        a2.scatter(dl, [i] * len(dl), color=colors[i], s=22, zorder=3)
        a2.scatter([sum(dl) / len(dl)], [i], color=colors[i], s=80, marker="D", zorder=4)
        a2.text(max(dl) + 0.0015, i, f"{sum(dl) / len(dl):+.4f}", va="center", fontsize=10, color=colors[i])
    a2.axvline(0, color=GRAY, lw=1)
    a2.set_yticks(y, names, fontsize=11)
    a2.invert_yaxis()
    a2.set_xlabel("验证损失的增量（3 个种子；菱形是平均）")
    a2.set_title("放回模型：INT8 看不出差别，INT4 要分组", fontsize=12.5)
    a2.grid(alpha=0.25, axis="x")
    lo, hi = a2.get_xlim()
    a2.set_xlim(lo, hi + 0.008)
    mean = lambda n: sum(res[n][j][0] - base[s] for j, s in enumerate(seeds)) / len(seeds)
    save_plot(fig, "quant-granularity.svg", "量化粒度与模型质量",
              "左：种子 0 的全部权重矩阵在各方案下的相对误差（量化误差的范数除以权重的范数）和每个权重摊到的位数（含 FP16 缩放因子）。"
              f"右：3 个种子上验证损失的增量。INT8 按通道 {mean('INT8 按通道'):+.4f}，INT4 按张量 {mean('INT4 按张量'):+.4f}，INT4 按通道 {mean('INT4 按通道'):+.4f}，"
              f"INT4 分组 32 {mean('INT4 分组 32'):+.4f}，INT3 分组 32 {mean('INT3 分组 32'):+.4f}。")


def quant_outliers():
    """第 1 层 down 的输入：每个通道的最大绝对值，SmoothQuant 前后；对照 qkv 的输入。"""
    log = _quant_log()
    if log is None:
        return
    down, sm, qkv = np.array(log["absmax_down1"]), np.array(log["absmax_down1_smoothed"]), np.array(log["absmax_qkv1"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.9), layout="constrained", gridspec_kw={"width_ratios": [1, 2.3]})
    a1.bar(np.arange(len(qkv)), qkv, color=BLUE, alpha=0.7, width=1.0)
    a1.axhline(np.median(qkv), color=GRAY, ls="--", lw=1.2)
    a1.set_title(f"qkv 的输入（128 个通道）：最大 / 中位数 = {qkv.max() / np.median(qkv):.1f}", fontsize=12)
    a1.set_xlabel("通道")
    a1.set_ylabel("最大绝对值")
    x = np.arange(len(down))
    a2.bar(x, down / np.median(down), color=RED, alpha=0.55, width=1.0, label=f"原始：最大 / 中位数 = {down.max() / np.median(down):.1f}")
    a2.bar(x, sm / np.median(sm), color=TEAL, alpha=0.75, width=1.0, label=f"SmoothQuant（α=0.5）之后：{sm.max() / np.median(sm):.1f}")
    a2.axhline(1, color=GRAY, ls="--", lw=1.2)
    a2.set_title("down 的输入（341 个通道），按中位数归一", fontsize=12)
    a2.set_xlabel("通道")
    a2.set_ylabel("最大绝对值 ÷ 中位数")
    a2.legend(fontsize=10, loc="upper right")
    ar = log["act_results"]
    m = lambda k: sum(ar[k]) / len(ar[k])
    save_plot(fig, "quant-outliers.svg", "激活里的离群通道",
              "种子 0 的模型、第 1 层，在一批验证文本上统计每个输入通道出现过的最大绝对值。左：qkv 的输入（RMSNorm 之后）各通道差不多大。"
              f"右：down 的输入（SiLU 门控乘 up）少数通道是中位数的十几倍，SmoothQuant 把一部分尺度挪给权重后降到 {sm.max() / np.median(sm):.1f} 倍。"
              f"激活 INT6 时，按张量量化损失增加 {m('W8A6 按张量'):+.4f}，SmoothQuant 后 {m('W8A6 SmoothQuant + 按张量'):+.4f}，按 token 量化 {m('W8A6 按 token'):+.4f}（3 个种子平均）。")


# ---------- 第 31 章：投机解码 ----------

def _spec_log():
    src = DATA / "tinyllm-speculative-decoding-log.json"
    if not src.exists():
        print("skip speculative-decoding figures: run scripts/build-tinyllm-code.py speculative-decoding to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def spec_round():
    """一轮投机解码：草稿猜 4 个，目标一次前向给出 5 个位置上的选择，接受到第一处不同为止。数据取自脚本 trace 的一轮。"""
    log = _spec_log()
    if log is None:
        return
    rnd = max((r for r in log["trace"] if r["k"] < len(r["draft"])), key=lambda r: r["k"])   # 接受得最多、但没有全部接受的一轮
    prev = log["trace"][log["trace"].index(rnd) - 1]
    last = prev["draft"][:prev["k"]] + [prev["choice"][prev["k"]]]
    last = last[-1]                                                         # 上一轮留下、还没送进目标模型的 token
    draft, choice, k = rnd["draft"], rnd["choice"], rnd["k"]
    g = len(draft)
    x0, cw, gap = 230, 100, 14
    cx = lambda j: x0 + j * (cw + gap)
    body = text(480, 36, f"投机解码的一轮：草稿猜 {g} 个，目标模型一次前向验证", 21, weight="bold")
    # 第 1 行：目标模型的输入
    body += text(40, 92, "① 草稿模型连续猜 4 个", 15, ORANGE, "bold", "start")
    body += text(40, 114, "目标模型把它们和上一轮", 13.5, GRAY, anchor="start")
    body += text(40, 132, "留下的 token 一次送进去", 13.5, GRAY, anchor="start")
    cells = [(last, GRAY)] + [(t, ORANGE) for t in draft]
    for j, (t, color) in enumerate(cells):
        body += cbox(cx(j), 82, cw, 50, color)
        body += text(cx(j) + cw / 2, 114, t, 19 if len(t) == 1 else 15, color if color != GRAY else INK, "bold")
    body += text(cx(0) + cw / 2, 152, "上一轮留下", 12.5, GRAY)
    body += text((cx(1) + cx(g) + cw) / 2, 152, f"草稿 d1 … d{g}", 12.5, ORANGE)
    # 斜箭头：位置 j 的输出是位置 j+1 的预测
    for j in range(g + 1):
        body += arrow(cx(j) + cw / 2, 164, cx(j + 1) + cw / 2 - 8, 214, BLUE, 2)
    body += text(40, 196, "② 目标模型一次前向", 15, BLUE, "bold", "start")
    body += text(40, 218, "每个位置给出它自己", 13.5, GRAY, anchor="start")
    body += text(40, 236, "选的下一个 token", 13.5, GRAY, anchor="start")
    # 第 2 行：目标模型的选择（错开一格，和它要验证的草稿上下对齐）
    for j, t in enumerate(choice):
        col = j + 1
        used = j <= k
        body += cbox(cx(col), 222, cw, 50, BLUE if used else GRAY, dash=not used)
        body += text(cx(col) + cw / 2, 254, t, 19 if len(t) == 1 else 15, BLUE if used else GRAY, "bold")
    # 第 3 行：比较
    body += text(40, 318, "③ 上下逐个比较", 15, TEAL, "bold", "start")
    body += text(40, 340, "第一处不同就停", 13.5, GRAY, anchor="start")
    for j in range(g):
        col = j + 1
        if j < k:
            body += text(cx(col) + cw / 2, 326, "✓ 相同，接受", 14, TEAL, "bold")
        elif j == k:
            body += text(cx(col) + cw / 2, 326, "× 不同", 14, RED, "bold")
            body += text(cx(col) + cw / 2, 346, "换成目标的选择", 12.5, RED)
        else:
            body += text(cx(col) + cw / 2, 326, "不用比了", 13, GRAY)
    if k < g:
        body += text(cx(g + 1) + cw / 2, 326, "用不上", 13, GRAY)
    # 第 4 行：结果
    new = draft[:k] + [choice[k]]
    body += cbox(40, 378, 880, 92, TEAL)
    body += text(60, 408, f"④ 这一轮前进 {len(new)} 个 token：", 16, TEAL, "bold", "start")
    xx = 300
    for i, t in enumerate(new):
        color = ORANGE if i < k else BLUE
        body += box(xx, 388, 64, 32, SOFT[color], color)
        body += text(xx + 32, 410, t, 16 if len(t) == 1 else 12.5, color, "bold")
        xx += 72
    body += text(xx + 10, 410, f"（前 {k} 个来自草稿，最后 1 个来自目标模型）", 14, INK, anchor="start")
    body += text(60, 450, f"目标模型只前向了 1 次。被拒的“{draft[k]}”" + ("及其后的草稿" if k < g - 1 else "")
                 + "已经写进了 KV cache，要回滚删掉；最后那个 token 下一轮再送进去。", 14, INK, anchor="start")
    svg("spec-round.svg", "投机解码的一轮",
        f"上一轮留下的 token“{last}”和草稿模型猜的 {g} 个 token（{'、'.join(draft)}）一起送进目标模型，一次前向得到 {g + 1} 个位置上目标模型自己的选择（{'、'.join(choice)}）。"
        f"错开一格逐个比较，前 {k} 个相同、全部接受，第 {k + 1} 个不同，换成目标模型的“{choice[k]}”。这一轮前进 {len(new)} 个 token，目标模型只前向 1 次；被拒草稿的 KV 要从缓存里回滚。",
        490, body)


def spec_rejection():
    """拒绝采样：一个位置上 p、q 与 min(p, q)；四种写法与 p 的总变差距离。"""
    log = _spec_log()
    if log is None:
        return
    r = log["rejection"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.0), layout="constrained", gridspec_kw={"width_ratios": [1.25, 1]})
    p, q = np.array(r["p"]) * 100, np.array(r["q"]) * 100
    x = np.arange(len(p))
    a1.bar(x - 0.2, p, 0.4, color=BLUE, alpha=0.75, label="目标 p")
    a1.bar(x + 0.2, q, 0.4, color=ORANGE, alpha=0.75, label="草稿 q")
    lo = np.minimum(p, q)
    a1.bar(x - 0.2, lo, 0.4, fill=False, hatch="///", edgecolor=TEAL, lw=0)
    a1.bar(x + 0.2, lo, 0.4, fill=False, hatch="///", edgecolor=TEAL, lw=0, label="min(p, q)：一定接受的部分")
    a1.set_xticks(x, r["tokens"], fontsize=13)
    a1.set_ylabel("概率（%）")
    a1.set_title(f"“春眠不觉晓，”之后，p 最大的 8 个 token（Σmin(p, q) = {r['overlap']:.3f}）", fontsize=12)
    a1.set_ylim(0, max(p.max(), q.max()) * 1.35)
    a1.legend(fontsize=9.5, loc="upper center", ncol=3)
    names = list(r["tv"])
    vals = [r["tv"][n] for n in names]
    colors = [GRAY, TEAL, RED, RED]
    y = np.arange(len(names))
    a2.barh(y, vals, color=colors, alpha=0.75)
    for i, v in enumerate(vals):
        a2.text(v + 0.003, i, f"{v:.3f}", va="center", fontsize=11)
    a2.axvline(vals[0], color=GRAY, ls="--", lw=1.2)
    a2.set_yticks(y, names, fontsize=11.5)
    a2.invert_yaxis()
    a2.set_xlim(0, max(vals) * 1.25)
    a2.set_xlabel("20 万个样本的频率与 p 的总变差距离")
    a2.set_title("虚线 = 只有抽样误差时的水平", fontsize=12)
    save_plot(fig, "spec-rejection.svg", "拒绝采样保持目标分布",
              f"左：提示词“春眠不觉晓，”之后，目标模型 p 和蒸馏草稿 q 在概率最大的 8 个 token 上的分布，斜线部分是 min(p, q)；"
              f"把它在全部 4096 个 token 上加起来是 {r['overlap']:.3f}，正是草稿 token 被接受的概率。"
              f"右：20 万个样本的频率与 p 的总变差距离。直接从 p 抽 {vals[0]:.3f}（只有抽样误差），正确的拒绝采样 {vals[1]:.3f}，"
              f"草稿全部接受 {vals[2]:.3f}，被拒后从 p 重抽 {vals[3]:.3f}。")


def spec_gamma():
    """左：每次前向前进的 token 数随 γ 的变化（3 个种子）与公式；右：加速比公式和本机实测。"""
    log = _spec_log()
    if log is None:
        return
    sweep, wall = log["sweep"], log["wall"]
    seeds = sorted(sweep)
    gammas = sorted(int(g) for g in sweep[seeds[0]])
    tau = np.array([[sweep[s][str(g)]["tau"] for g in gammas] for s in seeds])
    alpha1 = np.mean([sweep[s]["1"]["alpha"] for s in seeds])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2), layout="constrained")
    gg = np.arange(1, 9)
    a1.plot(gg, (1 - alpha1 ** (gg + 1)) / (1 - alpha1), color=GRAY, ls="--", lw=1.5, label=f"公式 (1−α^(γ+1))/(1−α)，α={alpha1:.2f}")
    a1.fill_between(gammas, tau.min(0), tau.max(0), color=BLUE, alpha=0.18)
    a1.plot(gammas, tau.mean(0), "o-", color=BLUE, lw=2, label="贪心，蒸馏草稿（3 个种子，阴影是范围）")
    sr = log["sample_rows"]
    for g in (2, 4):
        t = [(sr[f"{g}-{s}"]["accepted"] + sr[f"{g}-{s}"]["rounds"]) / sr[f"{g}-{s}"]["rounds"] for s in seeds]
        a1.errorbar([g], [np.mean(t)], yerr=[[np.mean(t) - min(t)], [max(t) - np.mean(t)]], fmt="s", color=ORANGE, ms=8, capsize=4,
                    label="采样（温度 1），同一批草稿" if g == 2 else None)
    a_s = np.mean([sr[f"4-{s}"]["accepted"] / sr[f"4-{s}"]["tested"] for s in seeds])
    a1.plot(gg, (1 - a_s ** (gg + 1)) / (1 - a_s), color=ORANGE, ls=":", lw=1.5, label=f"公式，α={a_s:.2f}")
    a1.set_xlabel("每轮起草的个数 γ")
    a1.set_ylabel("每轮前进的 token 数 τ")
    a1.set_title("γ 超过 4 以后几乎不再增加", fontsize=12.5)
    a1.legend(fontsize=9.5, loc="upper left")
    a1.grid(alpha=0.25)
    gg2 = np.arange(1, 13)
    spd = lambda a, c: (1 - a ** (gg2 + 1)) / (1 - a) / (1 + gg2 * c)
    for a, c, color, ls in [(0.45, 0.5, BLUE, "--"), (0.77, 0.5, ORANGE, "--"), (0.45, 0.05, BLUE, "-"), (0.77, 0.05, ORANGE, "-"), (0.9, 0.05, TEAL, "-")]:
        a2.plot(gg2, spd(a, c), color=color, ls=ls, lw=1.8, label=f"α={a}，c={c}")
    meas = [np.mean(wall["speedup"][str(g)]) for g in gammas]
    a2.plot(gammas, meas, "o", color=BLUE, ms=7, label=f"本机实测：贪心，c≈{wall['c']:.2f}")
    a2.axhline(1, color=INK, lw=1)
    a2.set_xlabel("每轮起草的个数 γ")
    a2.set_ylabel("相对普通 decode 的加速比")
    a2.set_title("加速比 ≈ τ / (1 + γc)：草稿必须便宜", fontsize=12.5)
    a2.legend(fontsize=9.5, ncol=2, loc="upper left")
    a2.set_ylim(0, 6.6)
    a2.grid(alpha=0.25)
    save_plot(fig, "spec-gamma.svg", "起草长度、接受率与加速比",
              f"左：蒸馏草稿贪心解码时，每轮（目标模型一次前向）平均前进的 token 数随 γ 增加，从 γ=1 的 {tau.mean(0)[0]:.2f} 到 γ=8 的 {tau.mean(0)[-1]:.2f}；"
              f"用 γ=1 的接受率 α={alpha1:.2f} 代入的公式在 γ≥3 时偏低，因为接受往往成串出现。同一批草稿在温度 1 采样时接受率约 {a_s:.2f}，γ=4 时每轮前进约 3 个 token。"
              f"右：加速比公式 τ/(1+γc) 的几条曲线。本机 CPU 上草稿一次前向是目标的 {wall['c']:.2f} 倍，贪心实测加速比从 γ=1 的 {meas[0]:.2f} 降到 γ=8 的 {meas[-1]:.2f}，都低于 1；"
              f"草稿成本降到 c=0.05 时，α=0.45 最多快 {spd(0.45, 0.05).max():.1f} 倍，α=0.77 最多快 {spd(0.77, 0.05).max():.1f} 倍。")


# ---------- 第 32 章：批处理与调度 ----------

def _batch_log():
    src = DATA / "tinyllm-batching-log.json"
    if not src.exists():
        print("skip batching figures: run scripts/build-tinyllm-code.py batching to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def batch_layouts():
    """矩形批（左补齐）与首尾相接的变长批：同样 4 个提示词，各占多少位置。长度与第 2 节相同。"""
    lens = [6, 12, 24, 40]
    colors = [BLUE, TEAL, ORANGE, PURPLE]
    body = text(480, 36, "同样 4 个提示词，两种拼法", 21, weight="bold")
    # 上：矩形批
    body += text(40, 84, "① 拼成矩形（左补齐）", 16, INK, "bold", "start")
    cell, x0, y0 = 14, 210, 100
    T = max(lens)
    for r, n in enumerate(lens):
        body += text(x0 - 12, y0 + r * (cell + 4) + 11, f"请求 {r + 1}（{n}）", 12.5, GRAY, anchor="end")
        for c in range(T):
            real = c >= T - n
            fill = SOFT[colors[r]] if real else "#f1f5f9"
            stroke = colors[r] if real else "#cbd5e1"
            body += f'<rect x="{x0 + c * cell}" y="{y0 + r * (cell + 4)}" width="{cell - 2}" height="{cell}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    total = sum(lens)
    body += text(x0 + T * cell + 16, y0 + 20, f"真 token {total} 个", 14, INK, anchor="start")
    body += text(x0 + T * cell + 16, y0 + 42, f"矩形 {len(lens)} × {T} = {len(lens) * T} 个位置", 14, INK, anchor="start")
    body += text(x0 + T * cell + 16, y0 + 64, f"灰格（pad）白算 {1 - total / (len(lens) * T):.0%}", 14, RED, "bold", "start")
    body += text(x0 + T * cell / 2, y0 + 4 * (cell + 4) + 18, "每行最后一列都是真 token；pad 的列要用掩码遮掉，位置从每行第一个真 token 开始数", 12.5, GRAY)
    # 下：首尾相接
    y1 = 262
    body += text(40, y1, "② 首尾相接（不补齐，本章的引擎）", 16, INK, "bold", "start")
    c2, x1 = 7.4, 90
    body += text(x1 + total * c2 / 2, y1 + 34, "注意力：每一段只和自己槽位里的 K、V 算（各自的长度、各自的位置）", 13.5, INK)
    x = x1
    for r, n in enumerate(lens):
        body += f'<path d="M{x + 2:.1f} {y1 + 54} V{y1 + 46} H{x + n * c2 - 4:.1f} V{y1 + 54}" stroke="{colors[r]}" stroke-width="1.5" fill="none"/>'
        body += f'<rect x="{x:.1f}" y="{y1 + 60}" width="{n * c2 - 1.5:.1f}" height="26" rx="4" fill="{SOFT[colors[r]]}" stroke="{colors[r]}" stroke-width="1.5"/>'
        body += text(x + n * c2 / 2, y1 + 78, f"{n}", 13, colors[r], "bold")
        x += n * c2
    body += text(x + 14, y1 + 70, f"共 {total} 个位置", 14, TEAL, "bold", "start")
    body += text(x + 14, y1 + 90, "没有一个是白算的 pad", 14, TEAL, "bold", "start")
    body += line(x1, y1 + 98, x - 2, y1 + 98, GRAY, 1.5)
    body += text((x1 + x) / 2, y1 + 120, "线性层、前馈层：这一整行一起算，权重只读一遍", 13.5, INK)
    svg("batch-layouts.svg", "矩形批与首尾相接的变长批",
        f"长度为 6、12、24、40 的 4 个提示词。上：拼成 4×40 的矩形并左补齐，真 token {total} 个，矩形 {len(lens) * T} 个位置，"
        f"{1 - total / (len(lens) * T):.0%} 是白算的 pad。下：首尾相接排成一行，共 {total} 个位置，没有 pad；"
        "线性层和前馈层对整行一起算，注意力按段分开，每段只看自己槽位里的 K、V。", 410, body)


def batch_timeline():
    """同一份重负载请求流（种子 0）：静态批与连续批下每个请求的等待和生成时间段。"""
    log = _batch_log()
    if log is None:
        return
    tl = log["timeline"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), layout="constrained", sharey=True, sharex=True)
    for ax, (pol, title) in zip(axes, [("static", "静态批（B=8）"), ("continuous", "连续批（B=8）")]):
        rows = tl[pol]
        for i, r in enumerate(rows):
            color = ORANGE if r["prompt"] > 20 else BLUE
            ax.plot([r["arrive"], r["times"][0]], [i, i], color=GRAY, lw=2.2, alpha=0.45, solid_capstyle="butt")
            ax.plot([r["times"][0], r["times"][-1]], [i, i], color=color, lw=2.6, solid_capstyle="butt")
        ttft = sorted(r["times"][0] - r["arrive"] for r in rows)
        end = max(r["times"][-1] for r in rows)
        ax.set_title(f"{title}：TTFT 中位 {ttft[len(ttft) // 2]:.0f}，全部完成于 {end:.0f}", fontsize=12.5)
        ax.set_xlabel("时间（成本模型的单位）")
        ax.grid(alpha=0.2, axis="x")
    axes[0].set_ylabel("请求（按到达顺序）")
    axes[0].invert_yaxis()
    axes[0].plot([], [], color=GRAY, lw=2.2, alpha=0.45, label="到达 → 第一个 token（等待 + prefill）")
    axes[0].plot([], [], color=BLUE, lw=2.6, label="生成中（短提示词）")
    axes[0].plot([], [], color=ORANGE, lw=2.6, label="生成中（长提示词）")
    axes[0].legend(fontsize=9.5, loc="upper right")
    save_plot(fig, "batch-timeline.svg", "静态批与连续批的时间线",
              "同一份 40 个请求的重负载请求流（种子 0），每一行是一个请求：灰色段是从到达到第一个 token，彩色段是生成过程。"
              "静态批要等凑够 8 个才开始，整批一起结束，后到的请求排很长的队，灰色段越来越长；"
              "连续批每次前向后立刻补进新请求，灰色段一直很短，全部请求也更早完成。")


def batch_chunked():
    """连续批的每一次 token 间隔：不分块时长提示词进来会让正在生成的请求卡住，分块后间隔都是 1。"""
    log = _batch_log()
    if log is None:
        return
    tl = log["timeline"]
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 4.8), layout="constrained", sharex=True, sharey=True)
    for ax, (pol, title) in zip(axes, [("continuous", "连续批"), ("continuous-chunked", "连续批 + 分块 prefill（每次前向最多 16 个新 token）")]):
        ts, gaps = [], []
        for r in tl[pol]:
            for a, b in zip(r["times"], r["times"][1:]):
                ts.append(b); gaps.append(b - a)
        for r in tl[pol]:
            if r["prompt"] > 20:
                ax.axvline(r["arrive"], color=ORANGE, lw=1, alpha=0.35)
        ax.scatter(ts, gaps, s=7, color=BLUE, alpha=0.6)
        ax.set_title(f"{title}：最长间隔 {max(gaps):.2f}", fontsize=12)
        ax.set_ylabel("token 间隔")
        ax.grid(alpha=0.2)
    axes[1].set_xlabel("时间（成本模型的单位）；橙色竖线是长提示词到达的时刻")
    save_plot(fig, "batch-chunked.svg", "分块 prefill 消除卡顿",
              "同一份重负载请求流（种子 0），每个点是某个请求相邻两个 token 之间的间隔。上：不分块时，长提示词（橙色竖线）进来的那次前向要处理几十个新 token，"
              "正在生成的请求这一步的间隔跳到 1.1～5.4 个单位。下：每次前向最多 16 个新 token，提示词分几次送完，所有间隔都是 1 个单位。")


def batch_tradeoff():
    """左：本机一次前向带 B 个请求的耗时和摊到每个 token 的耗时；右：过载下槽位数 B 的吞吐、goodput 与 TPOT。"""
    log = _batch_log()
    if log is None:
        return
    bm = {int(k): v for k, v in log["batch_ms"].items()}
    Bs = sorted(bm)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2), layout="constrained")
    a1.plot(Bs, [bm[b] for b in Bs], "o-", color=GRAY, label="一次前向的耗时")
    a1.plot(Bs, [bm[b] / b for b in Bs], "o-", color=BLUE, label="摊到每个 token")
    a1.set_xscale("log", base=2)
    a1.set_yscale("log")
    a1.set_xticks(Bs, [str(b) for b in Bs])
    a1.set_xlabel("一次前向带的请求数 B（各算 1 个 token）")
    a1.set_ylabel("毫秒（本机 CPU）")
    a1.set_title(f"B 从 1 到 {Bs[-1]}：前向变慢 {bm[Bs[-1]] / bm[1]:.1f} 倍，每个 token 便宜 {bm[1] / (bm[Bs[-1]] / Bs[-1]):.0f} 倍", fontsize=11.5)
    a1.legend(fontsize=10)
    a1.grid(alpha=0.25, which="both")
    sl = {int(k): v for k, v in log["slots"].items()}
    S = sorted(sl)
    avg = lambda B, k: sum(r[k] for r in sl[B]) / len(sl[B])
    a2.plot(S, [avg(b, "throughput") for b in S], "o-", color=GRAY, label="吞吐（token/单位）")
    a2.plot(S, [avg(b, "goodput") for b in S], "o-", color=TEAL, lw=2.2, label="goodput（只算达标请求）")
    a2.plot(S, [avg(b, "tpot50") for b in S], "s--", color=ORANGE, label="TPOT 中位（单位）")
    a2.set_xscale("log", base=2)
    a2.set_xticks(S, [str(b) for b in S])
    a2.set_xlabel("槽位数 B（过载，连续批，3 份请求流平均）")
    a2.set_title("吞吐一直涨，goodput 在 B=8～16 之间最高", fontsize=12)
    a2.legend(fontsize=10, loc="upper left")
    a2.grid(alpha=0.25)
    save_plot(fig, "batch-tradeoff.svg", "批大小：吞吐与延迟的交换",
              f"左：本机 CPU 上一次前向给 B 个请求各算一个 token 的耗时，B 从 1 到 {Bs[-1]}，一次前向从 {bm[1]:.2f} ms 涨到 {bm[Bs[-1]]:.2f} ms，"
              f"摊到每个 token 从 {bm[1]:.2f} ms 降到 {bm[Bs[-1]] / Bs[-1]:.2f} ms。"
              f"右：成本模型下的过载请求流，槽位数 B 从 1 到 {S[-1]}，吞吐从 {avg(1, 'throughput'):.2f} 涨到 {avg(S[-1], 'throughput'):.2f}，"
              f"TPOT 中位从 {avg(1, 'tpot50'):.2f} 涨到 {avg(S[-1], 'tpot50'):.2f}；goodput 在 B=8 和 16 时最高（B=16 在 3 份请求流之间波动很大），B=32 时掉到 {avg(32, 'goodput'):.2f}。")


# ---------- 第 33 章：KV 显存管理 ----------

def _kv_log():
    src = DATA / "tinyllm-kv-memory-log.json"
    if not src.exists():
        print("skip kv-memory figures: run scripts/build-tinyllm-code.py kv-memory to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def kv_layouts():
    """同样 3 个请求：按最大长度预留一整段，和按块表分页。示意，长度是举例。"""
    reqs = [("A", 20, 30, BLUE, [7, 2, 12]), ("B", 9, 26, TEAL, [0, 15]), ("C", 37, 45, ORANGE, [4, 9, 18, 1, 21])]
    body = text(480, 36, "同样 3 个请求的 K、V，两种放法", 21, weight="bold")
    body += text(40, 80, "① 按上下文上限预留（第 32 章的槽位）", 16, INK, "bold", "start")
    cell, x0, y0 = 8.6, 150, 96
    for r, (name, written, final, color, _) in enumerate(reqs):
        y = y0 + r * 24
        body += text(x0 - 12, y + 13, f"请求 {name}：已写 {written}", 12.5, GRAY, anchor="end")
        for c in range(64):
            if c < written:
                fill, stroke = color, color
            elif c < final:
                fill, stroke = SOFT[color], color
            else:
                fill, stroke = "#f1f5f9", "#cbd5e1"
            body += f'<rect x="{x0 + c * cell:.1f}" y="{y}" width="{cell - 1.5:.1f}" height="16" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>'
    written = sum(r[1] for r in reqs)
    xr = x0 + 64 * cell + 16
    body += text(xr, y0 + 8, "预留 3 × 64 = 192 个位置", 13.5, INK, anchor="start")
    body += text(xr, y0 + 28, f"存着 K、V 的只有 {written} 个", 13.5, RED, "bold", "start")
    body += text(xr, y0 + 48, "实心：已写；浅色：以后才会写", 12, GRAY, anchor="start")
    body += text(xr, y0 + 66, "灰格：到请求结束都用不上", 12, GRAY, anchor="start")
    # 下：分页
    y1 = 196
    body += text(40, y1, "② 分页（块大小 8）：每个请求一张块表，块按需从池子里拿", 16, INK, "bold", "start")
    owner = {}
    for name, written_, _, color, table in reqs:
        for j, b in enumerate(table):
            owner[b] = (name, color, min(8, written_ - j * 8))
    for r, (name, written_, _, color, table) in enumerate(reqs):
        y = y1 + 30 + r * 46
        body += text(40, y + 20, f"请求 {name} 的块表", 13.5, color, "bold", "start")
        for j, b in enumerate(table):
            bx = 150 + j * 40
            body += box(bx, y + 2, 36, 26, SOFT[color], color, width=1.5)
            body += mtext(bx + 18, y + 20, str(b), 13, color, "bold")
        body += text(150, y + 42, "逻辑块 0 1 2 …  →  物理块号", 11, GRAY, anchor="start") if r == 2 else ""
    px, py, bw = 400, y1 + 24, 66
    body += text(px + 4 * bw, py - 2, "物理块池（24 块，每块 8 个位置）", 13.5, INK, "bold")
    for b in range(24):
        bx, by = px + (b % 8) * bw, py + 12 + (b // 8) * 44
        if b in owner:
            name, color, filled = owner[b]
            body += box(bx, by, bw - 6, 34, "#ffffff", color, width=1.6)
            for c in range(8):
                fill = color if c < filled else "#ffffff"
                body += f'<rect x="{bx + 3 + c * 6.8:.1f}" y="{by + 15}" width="5.6" height="15" fill="{fill}" stroke="{color}" stroke-width="0.6"/>'
            body += mtext(bx + 4, by + 12, f"#{b}", 10.5, color, "bold", "start") + text(bx + bw - 10, by + 12, name, 10.5, color, "bold", "end")
        else:
            body += box(bx, by, bw - 6, 34, "#f8fafc", "#cbd5e1", dash=True, width=1.2)
            body += mtext(bx + 4, by + 12, f"#{b}", 10.5, GRAY, anchor="start")
            body += text(bx + (bw - 6) / 2, by + 28, "空闲", 11, GRAY)
    n_blocks = sum(len(r[4]) for r in reqs)
    body += text(480, py + 160, f"分出去 {n_blocks} 块 = {n_blocks * 8} 个位置，存着 K、V 的 {written} 个：浪费只剩每个请求最后一块没写满的部分", 14, TEAL, "bold")
    body += text(480, py + 184, "块在池子里不必连续；注意力按块表把块拼回来读，第 p 个位置在 table[p // 8] 的第 p % 8 格", 13, GRAY)
    svg("kv-layouts.svg", "按上限预留与分页的 KV 布局",
        f"示意：3 个请求分别已写 20、9、37 个位置。上：每个请求按上下文上限预留 64 个位置，共 192 个，存着 K、V 的只有 {written} 个，"
        "其余有的以后才会写，有的到请求结束都用不上。下：分页，块大小 8，每个请求一张块表记录逻辑块放在哪个物理块，"
        f"3 个请求一共拿了 {n_blocks} 块、{n_blocks * 8} 个位置，物理块在池子里不连续，空闲块留给别的请求。", py + 200, body)


def kv_sharing():
    """前缀共享（块级哈希链）和 fork 后的写时复制。示意，块号是举例。"""
    body = text(480, 36, "共享块：引用计数决定能不能直接写", 21, weight="bold")
    # 左：前缀共享
    body += text(240, 74, "① 前缀共享：同一段系统提示词", 16, BLUE, "bold")
    keys = ["k1 = hash(·, 第 0～7 个)", "k2 = hash(k1, 第 8～15 个)", "k3 = hash(k2, 第 16～23 个)"]
    for j, k in enumerate(keys):
        body += cbox(40, 92 + j * 40, 210, 30, BLUE)
        body += text(145, 112 + j * 40, k, 12, INK)
        body += arrow(252, 107 + j * 40, 296, 107 + j * 40, BLUE, 1.6)
        body += box(300, 92 + j * 40, 90, 30, SOFT[BLUE], BLUE, width=1.6)
        body += text(345, 112 + j * 40, f"块 #{[3, 8, 5][j]}  引用 2", 12, BLUE, "bold")
    body += text(240, 228, "请求 A 的块表：[3, 8, 5, 11]", 13, INK)
    body += text(240, 250, "请求 B 的块表：[3, 8, 5, 14]", 13, INK)
    body += text(240, 278, "前 3 块只算一次、只存一份；各自的第 4 块不同", 12.5, GRAY)
    body += text(240, 300, "键链着前一块的键：同一个键 = 同一段完整前缀", 12.5, GRAY)
    body += text(240, 322, "没写满的块不登记，也不会被别人命中", 12.5, GRAY)
    body += line(480, 64, 480, 340, "#cbd5e1", 1.5)
    # 右：fork + 写时复制
    body += text(720, 74, "② fork 4 条采样：37 个 token 的提示词", 16, ORANGE, "bold")
    for j in range(4):
        bx = 520 + j * 66
        body += box(bx, 92, 58, 30, SOFT[ORANGE], ORANGE, width=1.6)
        body += text(bx + 29, 112, "引用 4", 11.5, ORANGE, "bold")
    body += box(788, 92, 150, 30, "#ffffff", RED, width=2)
    body += text(863, 112, "只写了 5/8 格 · 引用 4", 11.5, RED, "bold")
    body += text(647, 142, "前 4 块写满：只读，4 条一直共用", 12.5, ORANGE)
    body += text(863, 142, "第 5 块：4 条都要往里写", 12.5, RED)
    rows = [("第 1 条要写第 38 个 token", "引用 4 > 1 → 复制一块再写", True),
            ("第 2 条", "引用 3 > 1 → 复制", True),
            ("第 3 条", "引用 2 > 1 → 复制", True),
            ("第 4 条", "引用 1 → 原块直接写", False)]
    for j, (who, what, copy) in enumerate(rows):
        y = 168 + j * 34
        body += text(530, y + 16, who, 12.5, INK, anchor="start")
        body += box(712, y, 230, 26, SOFT[RED] if copy else SOFT[TEAL], RED if copy else TEAL, width=1.4)
        body += text(827, y + 18, what, 12, RED if copy else TEAL, "bold")
    body += text(720, 322, "写时复制 3 次；块数峰值 16，各自 prefill 要 28", 13.5, TEAL, "bold")
    svg("kv-sharing.svg", "前缀共享与写时复制",
        "示意。左：两个请求开头是同一段 24 个 token 的系统提示词，正好 3 个写满的块，每块的键是前一块的键加这一块 token 的哈希；"
        "两张块表的前 3 项指向同样的物理块，引用计数 2，只算一次、只存一份。右：37 个 token 的提示词 prefill 一次后 fork 出 4 条采样，"
        "4 个写满的块一直共用；第 5 块只写了 5 格，每条都要往里写，前 3 条写时引用计数大于 1，先复制一块再写，第 4 条写时引用计数已经是 1，直接写。"
        "共复制 3 次，块数峰值 16，各自 prefill 要 28 块。", 350, body)


def kv_waste():
    """左：种子 0、重负载下，块大小 64 与 8 的分配量随时间；右：各块大小的平均分配量拆成存着的、以后才写的、白占的。"""
    log = _kv_log()
    if log is None:
        return
    tr = log["trace"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.4), layout="constrained", gridspec_kw={"width_ratios": [1.35, 1]})
    t64, t8 = tr["64"], tr["8"]
    a1.step(t64["t"], t64["alloc"], where="pre", color=GRAY, lw=1.8, label="块大小 64：分配出去的位置")
    a1.step(t64["t"], t64["used"], where="pre", color=BLUE, lw=1.4, label="块大小 64：存着 K、V 的位置")
    a1.step(t8["t"], t8["alloc"], where="pre", color=TEAL, lw=1.8, label="块大小 8：分配出去的位置")
    a1.step(t8["t"], t8["used"], where="pre", color=TEAL, lw=1.0, ls="--", label="块大小 8：存着 K、V 的位置")
    a1.axhline(512, color=RED, lw=1, ls=":")
    a1.text(2, 520, "显存上限 512", color=RED, fontsize=10)
    a1.set_xlabel("时间（成本模型的单位）")
    a1.set_ylabel("位置数")
    a1.set_title("同一份请求流（种子 0，重负载）", fontsize=12)
    a1.legend(fontsize=9, loc="upper center", ncol=2)
    a1.grid(alpha=0.2)
    a1.set_ylim(0, 700)
    w = log["waste"]
    bss = ["64", "16", "8", "4", "1"]
    avg = lambda bs, k: sum(r[k] for r in w[bs]) / len(w[bs])
    used = np.array([avg(b, "used") for b in bss])
    alloc = np.array([avg(b, "alloc") for b in bss])
    fut64 = avg("64", "future")
    y = np.arange(len(bss))
    a2.barh(y, used, color=BLUE, label="存着 K、V")
    a2.barh(y[0], fut64, left=used[0], color="#fcd34d", label="以后才会写（只看块大小 64）")
    a2.barh(y[0], alloc[0] - used[0] - fut64, left=used[0] + fut64, color="#cbd5e1", label="分配了但空着")
    a2.barh(y[1:], alloc[1:] - used[1:], left=used[1:], color="#cbd5e1")
    for i in range(len(bss)):
        a2.text(alloc[i] + 6, y[i], f"{used[i] / alloc[i]:.0%}", va="center", fontsize=10.5, color=INK)
    a2.set_yticks(y, [f"块大小 {b}" for b in bss])
    a2.invert_yaxis()
    a2.set_xlabel("平均占用的位置数（3 份请求流）")
    a2.set_title("百分比 = 存着 K、V 的占分配的比例", fontsize=12)
    a2.legend(fontsize=9, loc="lower right")
    a2.set_xlim(0, 640)
    a2.grid(alpha=0.2, axis="x")
    save_plot(fig, "kv-waste.svg", "分配出去的显存里有多少存着 K、V",
              f"左：同一份重负载请求流（种子 0）随时间的显存占用。块大小 64 时每个请求一进来就拿走 64 个位置，灰线常年贴着 512 的上限，"
              f"真正存着 K、V 的蓝线只有它的三分之一左右；块大小 8 时分配的位置（绿线）紧跟实际写入的位置。"
              f"右：3 份请求流的平均。块大小 64 时存着 K、V 的占 {used[0] / alloc[0]:.0%}，以后才会写的占 {fut64 / alloc[0]:.0%}，"
              f"其余到请求结束都用不上；块大小 16、8、4、1 时这个比例是 "
              + "、".join(f"{used[i] / alloc[i]:.0%}" for i in range(1, len(bss))) + "，浪费只剩每个请求最后一块没写满的部分。")


def kv_prefix_eviction():
    """左：两种共享场景下实际算的 prefill token 与 TTFT；右：多轮对话上四种淘汰策略的命中率随显存变化。"""
    log = _kv_log()
    if log is None:
        return
    pr, ev = log["prefix"], log["eviction"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), layout="constrained")
    names = ["系统提示词", "多轮对话"]
    avg = lambda key, k: sum(r[k] for r in pr[key]) / len(pr[key])
    x = np.arange(2)
    for off, label, color in ((-0.18, "不共享", GRAY), (0.18, "前缀缓存", BLUE)):
        comp = [avg(f"{n}-{label}", "prefill") - avg(f"{n}-{label}", "cached") for n in names]
        ttft = [avg(f"{n}-{label}", "ttft50") for n in names]
        bars = a1.bar(x + off, comp, 0.34, color=color, label=label)
        for b, c, t in zip(bars, comp, ttft):
            a1.text(b.get_x() + b.get_width() / 2, c + 20, f"{c:.0f}\nTTFT {t:.1f}", ha="center", fontsize=9.5)
    a1.set_xticks(x, names)
    a1.set_ylabel("实际算的 prefill token（3 份平均）")
    a1.set_ylim(0, 2050)
    a1.set_title("块大小 8、显存 512 个位置", fontsize=12)
    a1.legend(fontsize=10, loc="upper right")
    a1.grid(alpha=0.2, axis="y")
    pools = sorted(int(p) for p in ev)
    for pol, label, color, ls in (("lru", "LRU", BLUE, "-"), ("fifo", "FIFO", ORANGE, "-"), ("all", "缺块时一次清空", PURPLE, "--"), ("none", "不保留", GRAY, ":")):
        hs = np.array([ev[str(p)][pol] for p in pools])
        a2.plot(pools, hs.mean(1) * 100, "o" + ls, color=color, label=label, ms=4)
        a2.fill_between(pools, hs.min(1) * 100, hs.max(1) * 100, color=color, alpha=0.12)
    a2.set_xlabel("显存（能放多少个位置的 K、V）")
    a2.set_ylabel("命中率 %（多轮对话）")
    a2.set_title("中等显存时，淘汰谁最要紧", fontsize=12)
    a2.legend(fontsize=10, loc="upper left")
    a2.grid(alpha=0.2)
    lru, fifo = (np.array([ev[str(p)][k] for p in pools]).mean(1) for k in ("lru", "fifo"))
    save_plot(fig, "kv-prefix-eviction.svg", "前缀缓存的收益与淘汰策略",
              f"左：块大小 8、显存 512 个位置时实际算的 prefill token。系统提示词场景从 {avg('系统提示词-不共享', 'prefill'):.0f} 个降到 "
              f"{avg('系统提示词-前缀缓存', 'prefill') - avg('系统提示词-前缀缓存', 'cached'):.0f} 个，TTFT 中位从 {avg('系统提示词-不共享', 'ttft50'):.1f} 降到 {avg('系统提示词-前缀缓存', 'ttft50'):.1f}；"
              f"多轮对话从 {avg('多轮对话-不共享', 'prefill'):.0f} 个降到 {avg('多轮对话-前缀缓存', 'prefill') - avg('多轮对话-前缀缓存', 'cached'):.0f} 个。"
              f"右：多轮对话上四种淘汰策略的命中率，阴影是 3 份请求流的范围。显存 768 时三种保留策略都是 {lru[-1]:.0%}；"
              f"显存 512 时 LRU {lru[4]:.0%}、FIFO {fifo[4]:.0%}，差得最多；显存太紧（256）时几种保留策略都留不住多少，差别不大；不保留始终是 0。")

# ---------- 第 34 章：推理优化 ----------

def _io_log():
    src = DATA / "tinyllm-inference-optimization-log.json"
    if not src.exists():
        print("skip inference-optimization figures: run scripts/build-tinyllm-code.py inference-optimization to create", src)
        return None
    return json.loads(src.read_text(encoding="utf-8"))


def io_ablation():
    """两份请求流上：单独打开每一项、全部打开再去掉一项、本章的选择，goodput 的平均和范围（对数坐标）。"""
    log = _io_log()
    if log is None:
        return
    ab = log["ablation"]
    rows = [("基线", "alone", "基线", GRAY), ("+ 连续批", "alone", "连续批", BLUE), ("+ 分页与前缀缓存", "alone", "分页 + 前缀缓存", BLUE),
            ("+ INT8 权重", "alone", "INT8 权重", BLUE), ("+ 投机（γ=3）", "alone", "投机（γ=3）", BLUE), None,
            ("全部打开", "loo", "全部打开", TEAL), ("− 连续批", "loo", "去掉连续批", ORANGE), ("− 分块 prefill", "loo", "去掉分块 prefill", ORANGE),
            ("− 分页", "loo", "去掉分页", ORANGE), ("− 前缀缓存", "loo", "去掉前缀缓存", ORANGE), ("− INT8", "loo", "去掉 INT8", ORANGE),
            ("− 投机", "loo", "去掉投机", ORANGE), None, ("本章的选择", "choice", None, PURPLE)]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.6), layout="constrained", sharey=True)
    for ax, w in zip(axes, ["通用", "系统提示词"]):
        labels, y = [], 0
        for row in rows:
            if row is None:
                y += 0.6
                continue
            name, kind, key, color = row
            data = ab[f"choice | {w}"] if kind == "choice" else ab[f"{kind} | {w} | {key}"]
            g = [r["goodput"] for r in data]
            m = sum(g) / len(g)
            ax.barh(y, m, color=color, height=0.72)
            ax.plot([min(g), max(g)], [y, y], color=INK, lw=1.2)
            ax.text(max(max(g), m) * 1.12, y, f"{m:.2f}", va="center", fontsize=9.5)
            labels.append((y, name))
            y += 1
        ax.set_xscale("log")
        ax.set_xlim(0.02, 40)
        ax.set_title(f"{w}请求流（过载，3 份）", fontsize=12)
        ax.set_xlabel("goodput（达标请求的 token / 单位，对数坐标）")
        ax.grid(alpha=0.2, axis="x", which="both")
    axes[0].set_yticks([p for p, _ in labels], [n for _, n in labels])
    axes[0].invert_yaxis()
    full = {w: sum(r["goodput"] for r in ab[f"loo | {w} | 全部打开"]) / 3 for w in ["通用", "系统提示词"]}
    save_plot(fig, "io-ablation.svg", "逐项对照：单独打开与去掉一项",
              "两份过载请求流上的 goodput（对数坐标，横线是 3 份请求流的范围）。上面一组是在基线上单独打开一项：连续批让 goodput 涨了十几到四十几倍，INT8 涨到 2～3 倍多，"
              "分页与前缀缓存、投机几乎不动。中间一组是全部打开（通用 "
              f"{full['通用']:.2f}、系统提示词 {full['系统提示词']:.2f}）再一次去掉一项：去掉连续批掉到 0.1 左右；系统提示词请求流上去掉分页或前缀缓存都掉到 1.7；"
              "去掉 INT8 两份都变差；去掉投机两份都变好。最下面是去掉投机、分块额度放宽到 32 的本章选择。")


def io_routing():
    """4 个实例、四种路由：多轮对话与热门前缀两份负载上的 goodput、命中率和最忙实例的负载倍数。"""
    log = _io_log()
    if log is None:
        return
    rt = log["routing"]
    names = ["轮询", "最少负载", "前缀优先", "前缀优先 + 负载上限"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2), layout="constrained")
    for ax, w in zip(axes, ["多轮对话", "热门前缀"]):
        for i, n in enumerate(names):
            data = rt[f"{w} | {n}"]
            g = [r["goodput"] for r in data]
            m = sum(g) / 3
            hit = sum(r["hit"] for r in data) / 3
            imb = sum(r["imbalance"] for r in data) / 3
            ax.bar(i, m, color=[GRAY, BLUE, ORANGE, TEAL][i], width=0.65)
            ax.plot([i, i], [min(g), max(g)], color=INK, lw=1.2)
            ax.annotate(f"{m:.1f}\n命中 {hit:.0%}\n最忙 {imb:.2f}×", (i, max(g)), xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9.5)
        ax.set_xticks(range(4), ["轮询", "最少负载", "前缀优先", "前缀优先\n+ 负载上限"])
        ax.set_ylabel("goodput（3 份平均）")
        ax.set_title(w, fontsize=12)
        ax.margins(y=0.3)
        ax.grid(alpha=0.2, axis="y")
    save_plot(fig, "io-routing.svg", "多实例的路由",
              "4 个实例、四种路由，柱子上标着 goodput、前缀命中率和最忙实例干的活是平均的几倍。左：多轮对话，前缀优先把下一轮发回上一轮的实例，"
              "命中率从轮询的约 10% 升到约 50%，goodput 从约 6 升到约 12。右：所有请求共用一段系统提示词，前缀优先把全部请求都发给第一个实例，"
              "最忙的实例干了平均 4 倍的活，goodput 只有约 2；加上负载上限后回到约 40，和轮询相当。")


def io_server():
    """本章服务的结构：HTTP 线程、收件箱、独占模型的引擎线程、每个请求自己的队列。"""
    body = text(480, 34, "一个最小的推理服务：HTTP 线程不碰模型，引擎线程独占模型", 20, weight="bold")
    body += cbox(30, 70, 190, 238, GRAY)
    body += text(125, 96, "客户端", 15, GRAY, "bold")
    for i, t in enumerate(["POST /v1/chat/completions", "  stream=false：一次返回", "  stream=true：SSE 逐段", "GET /metrics", "GET /health"]):
        body += text(44, 128 + i * 30, t, 12.5, INK, anchor="start")
    body += cbox(270, 70, 190, 238, BLUE)
    body += text(365, 96, "HTTP 线程（每个连接一个）", 13.5, BLUE, "bold")
    for i, t in enumerate(["解析 JSON、分词", "检查长度，退出中就回 503", "submit → 收件箱", "从自己的队列取 token", "DecodeStream 攒成整字", "写回 JSON 或 SSE"]):
        body += text(365, 128 + i * 28, t, 12.5, INK)
    body += arrow(222, 140, 266, 140, GRAY, 2)
    body += arrow(266, 260, 222, 260, GRAY, 2)
    body += cbox(510, 70, 140, 60, ORANGE)
    body += text(580, 96, "收件箱", 14, ORANGE, "bold") + text(580, 116, "queue.Queue", 12, INK)
    body += cbox(510, 248, 140, 60, ORANGE)
    body += text(580, 274, "每个请求的队列", 13, ORANGE, "bold") + text(580, 294, "新 token / 结束", 12, INK)
    body += arrow(462, 100, 506, 100, BLUE, 2)
    body += arrow(506, 278, 462, 278, ORANGE, 2)
    body += cbox(700, 70, 230, 238, TEAL)
    body += text(815, 96, "引擎线程（只有一个）", 14, TEAL, "bold")
    for i, t in enumerate(["取收件箱里的新请求", "Replica.step()：", "  抢占 / 放人 / 分块", "  一次前向（INT8 权重）", "  块池 + 前缀缓存", "把新 token 放进各自的队列"]):
        body += text(716, 128 + i * 28, t, 12.5, INK, anchor="start")
    body += arrow(652, 100, 696, 100, ORANGE, 2)
    body += arrow(696, 278, 652, 278, TEAL, 2)
    body += box(270, 336, 660, 70, "#ffffff", RED, width=1.6)
    body += text(600, 360, "优雅退出：① accepting = False，新请求一律 503（/health 也变 503，负载均衡器把流量切走）", 12.5, RED)
    body += text(600, 384, "② 引擎线程把收件箱和正在跑的请求都跑完　③ 线程结束，关掉 HTTP 服务", 12.5, RED)
    svg("io-server.svg", "推理服务的结构",
        "客户端发来的请求由 HTTP 线程解析、分词后放进收件箱；唯一的引擎线程取出新请求交给 Replica，一步一步跑（抢占、放人、分块、一次前向、块池和前缀缓存），"
        "把每一步新出的 token 放进各请求自己的队列；HTTP 线程从队列里取 token，用 DecodeStream 攒成完整的字，按普通 JSON 或 SSE 流写回。"
        "优雅退出时先拒绝新请求并让健康检查返回 503，再把手上的请求跑完，最后关掉服务。", 424, body)

# ---------- 2026-11 评审补充的结构示意图 ----------

def line(x1, y1, x2, y2, color=GRAY, width=2, dash=False):
    extra = ' stroke-dasharray="6 4"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"{extra}/>'


def mod(x, y, w, h, title, shape=None, color=GRAY, size=14):
    """一个模块框：名字在上，形状（等宽）在下。"""
    if shape:
        return (cbox(x, y, w, h, color) + text(x + w / 2, y + h / 2 - 3, title, size, color, "bold")
                + mtext(x + w / 2, y + h / 2 + 15, shape, 12.5, INK))
    return cbox(x, y, w, h, color) + text(x + w / 2, y + h / 2 + 5, title, size, color, "bold")


def first_run_shapes():
    """第 1 章的模型：一次前向里张量形状怎样变化。"""
    body = text(480, 36, "第 1 章的模型：一个 batch 穿过一次前向", 21, weight="bold")
    x, w = 90, 340
    steps = [("一批训练样本：每格是一个字的编号", "[32, 24]", GRAY),
             ("查表：字向量 + 位置向量", "[32, 24, 96]", BLUE),
             ("Block 1：注意力 + 前馈层", "[32, 24, 96]", TEAL),
             ("Block 2", "[32, 24, 96]", TEAL),
             ("Block 3", "[32, 24, 96]", TEAL),
             ("RMSNorm，再乘字表的转置", "[32, 24, 556]", ORANGE)]
    y = 66
    tops = []
    for i, (t, s, c) in enumerate(steps):
        body += mod(x, y, w, 52, t, s, c)
        tops.append(y)
        if i < len(steps) - 1:
            body += arrow(x + w / 2, y + 52, x + w / 2, y + 70, GRAY, 2)
        y += 72
    body += f'<rect x="{x - 12}" y="{tops[2] - 10}" width="{w + 24}" height="{tops[4] - tops[2] + 72}" rx="12" fill="none" stroke="{TEAL}" stroke-dasharray="6 4" stroke-width="1.5"/>'
    body += text(x + w + 24, tops[3] + 30, "形状不变", 13, TEAL, anchor="start")
    body += text(x + w + 24, tops[1] + 22, "字表 556×96", 13, BLUE, anchor="start")
    body += text(x + w + 24, tops[1] + 40, "位置表 24×96", 13, BLUE, anchor="start")
    body += text(x + w + 24, tops[5] + 22, "每个位置给 556 个字", 13, ORANGE, anchor="start")
    body += text(x + w + 24, tops[5] + 40, "各打一个分", 13, ORANGE, anchor="start")
    body += path(f"M{x} {tops[1] + 26} H{x - 30} V{tops[5] + 26} H{x - 4}", ORANGE, 1.8, dash=True)
    body += text(x - 36, (tops[1] + tops[5]) / 2 + 60, "同一张字表", 12, ORANGE, anchor="end")
    rx = 630
    body += text(rx + 150, 96, "训练时", 16, RED, "bold")
    body += mod(rx, 112, 300, 52, "目标：同一段往后错一位", "[32, 24]", GRAY)
    body += mod(rx, 196, 300, 52, "交叉熵损失", "一个数", RED)
    body += arrow(rx + 150, 164, rx + 150, 192, GRAY, 2)
    body += path(f"M{x + w} {tops[5] + 26} H{rx - 40} V222 H{rx - 4}", ORANGE, 2)
    body += text(rx + 150, 284, "backward 给 388,128 个参数各算一个梯度，", 13.5)
    body += text(rx + 150, 306, "AdamW 把每个参数挪一小步，重复 600 次", 13.5)
    body += text(rx + 150, 366, "生成时", 16, TEAL, "bold")
    body += text(rx + 150, 392, "只取最后一个位置的 556 个分数，", 13.5)
    body += text(rx + 150, 414, "抽一个字接到末尾，再走一遍左边这一列", 13.5)
    svg("first-run-shapes.svg", "第 1 章模型的形状流",
        "一个 batch 是 32 段、每段 24 个字的编号，查字表和位置表后变成 [32, 24, 96]，穿过 3 个 Block 形状不变，最后归一化并乘字表的转置得到 [32, 24, 556] 的分数。"
        "训练时这些分数和往后错一位的目标算交叉熵，backward 给 388,128 个参数算梯度，AdamW 更新参数；生成时只取最后一个位置的分数抽一个字。", y + 6, body)


def reshape_vs_transpose():
    """同一个 [3, 4] 张量：reshape 成 [4, 3] 与 transpose 成 [4, 3]。"""
    body = text(480, 36, "reshape 与 transpose：结果都是 [4, 3]，数的位置不一样", 20, weight="bold")
    cell = 38

    def grid(x0, y0, vals, color, hl):
        out = ""
        for r, row in enumerate(vals):
            for c, v in enumerate(row):
                on = v in hl
                out += box(x0 + c * cell, y0 + r * cell, cell, cell, SOFT[ORANGE] if on else SOFT[color], ORANGE if on else color, width=1.4)
                out += mtext(x0 + c * cell + cell / 2, y0 + r * cell + cell / 2 + 5, str(v), 15, ORANGE if on else INK, "bold" if on else "normal")
        return out

    a = [[r * 4 + c for c in range(4)] for r in range(3)]
    rs = [[r * 3 + c for c in range(3)] for r in range(4)]
    tr = [[a[c][r] for c in range(3)] for r in range(4)]
    hl = {1, 5, 9}
    body += text(170, 86, "原张量 x：[3, 4]", 16, BLUE, "bold") + grid(94, 104, a, BLUE, hl)
    body += text(170, 246, "内存里依次是 0 1 2 … 11", 13.5, GRAY)
    body += text(500, 86, "x.reshape(4, 3)", 16, TEAL, "bold") + grid(443, 104, rs, TEAL, hl)
    body += text(500, 284, "按内存顺序重新分行", 14, TEAL)
    body += text(500, 306, "第 0 行仍是 0 1 2", 13.5, GRAY)
    body += text(800, 86, "x.transpose(0, 1)", 16, ORANGE, "bold") + grid(743, 104, tr, ORANGE, hl)
    body += text(800, 284, "行和列互换", 14, ORANGE)
    body += text(800, 306, "第 0 行是原来的第 0 列：0 4 8", 13.5, GRAY)
    body += arrow(260, 150, 428, 150, GRAY, 2) + arrow(260, 178, 728, 190, GRAY, 2)
    body += text(480, 352, "橙色的 1、5、9 原来是第 1 列：transpose 后正好成了第 1 行；reshape 后散在三行里", 14.5)
    body += text(480, 378, "拆注意力头时先用 view 切出“头”这一维，再用 transpose 把它换到前面；用错一个，形状对，结果错", 14.5, INK, "bold")
    svg("reshape-vs-transpose.svg", "reshape 与 transpose 的区别",
        "左边是 [3, 4] 的张量，里面是 0 到 11。reshape(4, 3) 按内存顺序把 12 个数重新分成 4 行，第 0 行是 0 1 2；transpose(0, 1) 交换行和列，第 0 行是原来的第 0 列 0 4 8。"
        "两者形状相同，元素的位置不同。", 400, body)


def mask_patterns():
    """三种注意力：编码器双向、解码器因果、交叉注意力。"""
    body = text(480, 36, "三种注意力的区别就是“谁能看谁”：着色的格子是允许看的位置", 20, weight="bold")
    cell = 34

    def grid(x0, y0, rows, cols, allow, fill, edge, rl, cl):
        out = ""
        for r in range(rows):
            out += text(x0 - 10, y0 + r * cell + cell / 2 + 5, rl[r], 13, GRAY, anchor="end")
            for c in range(cols):
                ok = allow(r, c)
                out += box(x0 + c * cell, y0 + r * cell, cell, cell, fill if ok else "#ffffff", edge if ok else "#cbd5e1", width=1.2)
        for c in range(cols):
            out += text(x0 + c * cell + cell / 2, y0 - 8, cl[c], 13, GRAY)
        return out

    src = ["I", "am", "a", "cat", "."]
    tgt = ["我", "是", "猫", "。"]
    body += text(180, 80, "编码器自注意力：5 × 5", 16, BLUE, "bold")
    body += grid(95, 120, 5, 5, lambda r, c: True, "#bfdbfe", BLUE, src, src)
    body += text(180, 314, "原文每个词看全部原文：25 / 25", 14, BLUE)
    body += text(490, 80, "解码器自注意力：4 × 4", 16, TEAL, "bold")
    body += grid(422, 120, 4, 4, lambda r, c: c <= r, "#99f6e4", TEAL, tgt, tgt)
    body += text(490, 280, "只看自己和前面：10 / 16", 14, TEAL)
    body += text(490, 304, "TinyLLM 只用这一种（因果掩码）", 13.5, TEAL, "bold")
    body += text(800, 80, "交叉注意力：4 × 5", 16, ORANGE, "bold")
    body += grid(720, 120, 4, 5, lambda r, c: True, "#fde68a", ORANGE, tgt, src)
    body += text(805, 280, "每个译词看全部原文：20 / 20", 14, ORANGE)
    body += text(480, 360, "行是“谁在看”（Q），列是“被看的是谁”（K）；计数与本章脚本 masks 一段的输出一致", 14, GRAY)
    svg("mask-patterns.svg", "三种注意力的掩码",
        "左：编码器自注意力，5 个原文词互相都能看，25 个格子全部允许。中：解码器自注意力，4 个译词只能看自己和前面，是下三角，16 个格子里 10 个允许，这就是因果掩码。"
        "右：交叉注意力，每个译词能看全部 5 个原文词，20 个格子全部允许。", 385, body)


def attention_dataflow():
    """单头注意力的完整数据流，带形状。"""
    body = text(480, 36, "一层注意力的数据流（T 个位置，每头 d_h 维）", 20, weight="bold")
    y = 64
    body += mod(380, y, 200, 48, "输入 x", "[T, d]", GRAY)
    xs = [130, 380, 630]
    for (n, c), xx in zip([("Q = x·W_Q", BLUE), ("K = x·W_K", TEAL), ("V = x·W_V", ORANGE)], xs):
        body += path(f"M480 {y + 48} V{y + 70} H{xx + 100} V{y + 92}", GRAY, 1.8)
        body += mod(xx, y + 96, 200, 48, n, "[T, d_h]", c)
    body += path(f"M230 {y + 144} V{y + 180} H420 V{y + 202}", BLUE, 1.8)
    body += path(f"M480 {y + 144} V{y + 202}", TEAL, 1.8)
    body += text(500, y + 180, "Kᵀ", 13, TEAL, anchor="start")
    rows = [("分数 S = Q·Kᵀ / √d_h", "[T, T]", INK), ("因果掩码：右上方置为 −∞", "[T, T]", RED),
            ("softmax：每行加起来是 1", "[T, T] 权重", INK), ("加权求和：权重 · V", "[T, d_h]", ORANGE),
            ("多头拼接 → 输出投影 W_O", "[T, d]，加回残差流", PURPLE)]
    yy = y + 206
    ys = []
    for i, (t, s, c) in enumerate(rows):
        body += mod(330, yy, 300, 50, t, s, c)
        ys.append(yy)
        if i < len(rows) - 1:
            body += arrow(480, yy + 50, 480, yy + 72, GRAY, 2)
        yy += 76
    body += path(f"M730 {y + 144} V{ys[3] + 25} H634", ORANGE, 1.8)
    body += line(318, ys[0] + 4, 300, ys[0] + 4, "#94a3b8", 1.5) + line(300, ys[0] + 4, 300, ys[2] + 46, "#94a3b8", 1.5) + line(300, ys[2] + 46, 318, ys[2] + 46, "#94a3b8", 1.5)
    body += text(288, ys[1] + 0, "这三步都要", 13.5, GRAY, anchor="end")
    body += text(288, ys[1] + 22, "一张 T×T 的表：", 13.5, GRAY, anchor="end")
    body += text(288, ys[1] + 44, "长度翻倍，表变 4 倍", 13.5, GRAY, anchor="end")
    body += text(288, ys[4] + 16, "多头：d 拆成 H 份，每份 d_h = d/H 维，", 13.5, PURPLE, anchor="end")
    body += text(288, ys[4] + 38, "各自走中间这一列，在 W_O 处合并", 13.5, PURPLE, anchor="end")
    svg("attention-dataflow.svg", "注意力的数据流",
        "输入 [T, d] 经三个投影得到 Q、K、V，各是 [T, d_h]。Q 乘 K 的转置再除以根号 d_h 得到 [T, T] 的分数，因果掩码把右上方置为负无穷，softmax 后每行加起来是 1，"
        "再对 V 加权求和得到 [T, d_h]。多个头的结果拼起来，经输出投影回到 [T, d]，加回残差流。分数、掩码、softmax 这三步都要一张 T×T 的表。", yy + 10, body)


def gqa_heads():
    """MHA、GQA、MQA：几个 Q 头共用一组 K、V。"""
    body = text(480, 36, "MHA、GQA、MQA：Q 头数相同，K/V 的组数不同", 21, weight="bold")
    configs = [("MHA：8 组 K/V", 8, BLUE, "每个 Q 头各有一组"), ("GQA：2 组 K/V", 2, TEAL, "每 4 个 Q 头共用一组"),
               ("MQA：1 组 K/V", 1, ORANGE, "所有 Q 头共用一组")]
    for row, (title, kv, color, note) in enumerate(configs):
        y = 74 + row * 128
        body += text(110, y + 46, title, 16, color, "bold") + text(110, y + 70, note, 13, GRAY)
        group = 8 // kv
        for g in range(kv):
            x0 = 240 + g * group * 52
            wb = group * 52 - 12
            for h in range(g * group, (g + 1) * group):
                body += line(240 + h * 52 + 20, y + 42, x0 + wb / 2, y + 78, color, 1.3)
            body += box(x0, y + 78, wb, 32, SOFT[color], color, width=1.6)
            body += text(x0 + wb / 2, y + 99, "K、V" if kv > 1 else "一组 K、V", 13, color, "bold")
        for h in range(8):
            x = 240 + h * 52
            body += box(x, y + 10, 40, 32, SOFT[BLUE], BLUE, width=1.4) + text(x + 20, y + 31, f"Q{h}", 13, BLUE)
        body += text(830, y + 46, f"KV cache = MHA × {kv}/8", 15, color, "bold")
    body += text(480, 470, "缓存大小正比于 K/V 的组数（第 28 章的公式）。Llama 3 8B 用 32 个 Q 头、8 组 K/V，缓存是 MHA 的四分之一", 14.5)
    svg("gqa-heads.svg", "MHA、GQA 与 MQA",
        "三行都有 8 个 Q 头。MHA 每个 Q 头各有一组 K、V，共 8 组；GQA 每 4 个 Q 头共用一组，共 2 组；MQA 所有 Q 头共用 1 组。KV cache 的大小正比于 K/V 的组数，"
        "分别是 MHA 的 8/8、2/8、1/8。", 490, body)


def tinyllm_architecture():
    """第 12 章：把一个 Block 展开，标出每一步的形状、章节号和初始化。"""
    body = text(500, 36, "完整 TinyLLM：一句 11 个 token 的诗走一遍（d=128，4 个头，每头 32 维）", 20, weight="bold")
    lx, lw = 50, 270
    body += mod(lx, 66, lw, 50, "token ID（第 4 章）", "[1, 11]", GRAY)
    body += arrow(lx + lw / 2, 116, lx + lw / 2, 136, GRAY, 2)
    body += mod(lx, 138, lw, 50, "查嵌入表 E（第 5 章）", "[1, 11, 128]", BLUE)
    body += arrow(lx + lw / 2, 188, lx + lw / 2, 226, GRAY, 2)
    body += f'<rect x="{lx}" y="228" width="{lw}" height="200" rx="12" fill="{SOFT[TEAL]}" stroke="{TEAL}" stroke-width="2"/>'
    body += text(lx + lw / 2, 282, "Block × 4（第 9 章）", 17, TEAL, "bold")
    body += mtext(lx + lw / 2, 308, "[1, 11, 128] → [1, 11, 128]", 13)
    body += text(lx + lw / 2, 344, "每层结构相同、参数各自独立", 13, GRAY)
    body += text(lx + lw / 2, 366, "展开见右边", 13, GRAY)
    body += arrow(lx + lw / 2, 428, lx + lw / 2, 466, GRAY, 2)
    body += mod(lx, 468, lw, 50, "最终 RMSNorm（第 11 章）", "[1, 11, 128]", GRAY)
    body += arrow(lx + lw / 2, 518, lx + lw / 2, 538, GRAY, 2)
    body += mod(lx, 540, lw, 50, "乘 E 的转置，得到 logits", "[1, 11, 4096]", ORANGE)
    body += path(f"M{lx} 163 H{lx - 26} V565 H{lx - 4}", ORANGE, 2, dash=True)
    body += f'<text x="{lx - 34}" y="364" font-size="12.5" fill="{ORANGE}" text-anchor="middle" transform="rotate(-90 {lx - 34} 364)">输入输出共用 E（4096×128）</text>'
    rx, rw = 370, 600
    body += f'<rect x="{rx}" y="62" width="{rw}" height="652" rx="14" fill="#ffffff" stroke="{TEAL}" stroke-width="2"/>'
    body += line(lx + lw, 228, rx, 62, TEAL, 1.2, True) + line(lx + lw, 428, rx, 714, TEAL, 1.2, True)
    body += text(rx + rw / 2, 88, "一个 Block 展开", 16, TEAL, "bold")
    cx, bw = rx + 230, 280
    bx = cx - bw / 2
    body += mtext(cx, 116, "残差流 x：[1, 11, 128]", 13.5, INK, "bold")
    body += arrow(cx, 122, cx, 132, GRAY, 1.6)

    def stack(items, y):
        ys = []
        for i, (t, s, c) in enumerate(items):
            body_ = cbox(bx, y, bw, 40, c) + text(cx, y + 17, t, 13.5, c, "bold") + mtext(cx, y + 34, s, 11.5, INK)
            ys.append((y, body_))
            y += 48
        return ys, y

    attn = [("RMSNorm", "[1, 11, 128]", GRAY), ("qkv：一个 Linear", "[1, 11, 384]，切成 Q、K、V", BLUE),
            ("拆成 4 个头", "[1, 4, 11, 32]", BLUE), ("Q、K 加 RoPE（第 7 章）", "[1, 4, 11, 32]", PURPLE),
            ("因果 SDPA（第 6 章），再合头", "[1, 11, 128]", BLUE), ("proj", "[1, 11, 128]", RED)]
    ys, y = stack(attn, 134)
    for i, (yy, b) in enumerate(ys):
        body += b
        if i < len(ys) - 1:
            body += arrow(cx, yy + 40, cx, yy + 48, GRAY, 1.6)
    add1 = y + 6
    body += arrow(cx, ys[-1][0] + 40, cx, add1 - 11, GRAY, 1.6)
    body += circle(cx, add1, 11) + text(cx, add1 + 5, "+", 16, weight="bold")
    body += path(f"M{cx} 127 H{bx - 30} V{add1} H{cx - 13}", INK, 2)
    ffn = [("RMSNorm", "[1, 11, 128]", GRAY), ("gate、up：两个 Linear", "各 [1, 11, 341]", TEAL),
           ("SiLU(gate) × up（第 8 章）", "[1, 11, 341]", TEAL), ("down", "[1, 11, 128]", RED)]
    ys2, y2 = stack(ffn, add1 + 22)
    body += arrow(cx, add1 + 11, cx, add1 + 20, GRAY, 1.6)
    for i, (yy, b) in enumerate(ys2):
        body += b
        if i < len(ys2) - 1:
            body += arrow(cx, yy + 40, cx, yy + 48, GRAY, 1.6)
    add2 = y2 + 6
    body += arrow(cx, ys2[-1][0] + 40, cx, add2 - 11, GRAY, 1.6)
    body += circle(cx, add2, 11) + text(cx, add2 + 5, "+", 16, weight="bold")
    body += path(f"M{cx} {add1 + 15} H{bx - 30} V{add2} H{cx - 13}", INK, 2)
    body += text(bx - 36, (127 + add1) / 2, "残差", 13, INK, anchor="end")
    body += text(bx - 36, (add1 + add2) / 2 + 10, "残差", 13, INK, anchor="end")
    body += arrow(cx, add2 + 11, cx, add2 + 28, GRAY, 1.6)
    body += mtext(cx, add2 + 44, "下一层：[1, 11, 128]", 13, INK)
    nx = bx + bw + 16
    body += text(nx, ys[1][0] + 18, "线性层都不带偏置", 12.5, GRAY, anchor="start")
    body += text(nx, ys[3][0] + 16, "cos/sin 表预先算好，", 12.5, PURPLE, anchor="start")
    body += text(nx, ys[3][0] + 33, "4 层共用一份", 12.5, PURPLE, anchor="start")
    body += text(nx, ys[5][0] + 16, "红框：写回残差流的投影，", 12.5, RED, anchor="start")
    body += text(nx, ys[5][0] + 33, "初始化再乘 1/√(2L)（第 10 章）", 12.5, RED, anchor="start")
    body += text(nx, ys2[1][0] + 24, "中间宽度 8d/3 = 341", 12.5, TEAL, anchor="start")
    body += text(nx, ys2[3][0] + 24, "同样乘 1/√(2L)", 12.5, RED, anchor="start")
    svg("tinyllm-architecture.svg", "完整 TinyLLM 的结构",
        "左：11 个 token 的 ID 查嵌入表变成 [1, 11, 128]，穿过 4 个 Block，最终 RMSNorm 后乘嵌入表的转置得到 [1, 11, 4096] 的 logits，输入输出共用一张表。"
        "右：一个 Block 展开。注意力半块：RMSNorm，qkv 投影到 [1, 11, 384] 再切成 Q、K、V，拆成 4 个头 [1, 4, 11, 32]，Q、K 加 RoPE，因果 SDPA 后合头，proj 投影，加回残差。"
        "前馈半块：RMSNorm，gate 和 up 各投影到 341 维，SiLU(gate) 乘 up，down 投影回 128 维，加回残差。proj 和 down 的初始化再乘 1/√(2L)。", 730, body, width=1000)


def _notebook_lines(slug, prefix):
    """从已生成的 notebook 输出里取一行（保证图里的数和脚本真实输出一致）。"""
    nb = json.loads((ROOT / f"docs/public/tinyllm/notebooks/{slug}.ipynb").read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        for o in cell.get("outputs", []):
            for ln in "".join(o.get("text", "")).splitlines():
                if ln.startswith(prefix):
                    return ln[len(prefix):].strip()
    raise SystemExit(f"{slug}.ipynb 里找不到以 {prefix!r} 开头的输出")


def tokenizer_pipeline():
    """第 4 章：一句话穿过 tokenizer 流水线，每一步的中间结果。"""
    import ast
    toks = ast.literal_eval(_notebook_lines("tokenization", "tokens:"))
    ids = ast.literal_eval(_notebook_lines("tokenization", "IDs:"))
    body = text(480, 36, "tokenizer 是一条流水线：“猫在学习 TinyLLM。\\n” 每一步变成什么", 20, weight="bold")
    stages = [("原文", "猫在学习 TinyLLM。⏎", GRAY, "14 个字符"),
              ("① 规范化", "本例不改写（NFKC 等规则在这一步）", GRAY, "随词表保存"),
              ("② 预切分 + 字节映射", "UTF-8 字节 → 可显示符号；空格变成 Ġ，换行变成 Ċ", BLUE, "汉字 3 字节"),
              ("③ BPE 按合并优先级切分", None, TEAL, f"{len(toks)} 个 token"),
              ("④ 查词表得到 ID", None, ORANGE, "送进模型"),
              ("⑤ 解码：ID → 字节 → 整段拼回", "猫在学习 TinyLLM。⏎（和原文逐字相同）", PURPLE, "整段解码")]
    y = 64
    for i, (name, content, color, note) in enumerate(stages):
        body += cbox(40, y, 220, 50, color) + text(150, y + 30, name, 14.5, color, "bold")
        body += box(276, y, 520, 50, "#ffffff", "#e2e8f0", width=1.2)
        if name.startswith("③"):
            x = 284
            for t in toks:
                w = 10 + 9 * len(t)
                body += box(x, y + 12, w, 26, SOFT[TEAL], TEAL, width=1.1) + mtext(x + w / 2, y + 30, t, 12.5, INK)
                x += w + 3
        elif name.startswith("④"):
            body += mtext(536, y + 31, " ".join(str(i_) for i_ in ids), 12.5, INK)
        else:
            body += text(536, y + 31, content, 14)
        body += text(810, y + 31, note, 12.5, GRAY, anchor="start")
        if i < len(stages) - 1:
            body += arrow(150, y + 50, 150, y + 66, GRAY, 2)
        y += 68
    body += text(480, y + 14, "③ 里 “ç Į «” 三个片段合起来才是“猫”这一个字的 3 个字节；“学习”两个字合成了一个 token", 14)
    body += text(480, y + 38, "① ② 是配置，③ 是训练出来的合并表，④ 是词表；四样都要和模型一起保存（第 4 章第 7 节）", 14, GRAY)
    svg("tokenizer-pipeline.svg", "tokenizer 流水线",
        "原文“猫在学习 TinyLLM。”加一个换行，经规范化（本例不改写）、预切分与字节映射（空格变成 Ġ、换行变成 Ċ，一个汉字是 3 个字节），"
        f"BPE 按合并优先级切成 {len(toks)} 个 token，查词表得到同样多的 ID；解码时把 ID 变回字节、整段拼回原文。数据来自第 4 章脚本的 encode-roundtrip 输出。", y + 60, body)


def ffn_vs_attention():
    """注意力在位置之间搬信息；前馈层对每个位置做同一个变换。"""
    body = text(480, 36, "注意力管“位置之间”，前馈层管“每个位置自己”", 21, weight="bold")
    toks = ["春", "眠", "不", "觉", "晓"]
    # 左：注意力
    body += text(240, 78, "注意力：每个位置看前面的位置", 16, BLUE, "bold")
    xs = [70 + i * 85 for i in range(5)]
    for i, (x, t) in enumerate(zip(xs, toks)):
        body += box(x, 110, 60, 44, SOFT[GRAY], GRAY, width=1.4) + text(x + 30, 139, t, 18)
        body += box(x, 290, 60, 44, SOFT[BLUE], BLUE, width=1.6) + text(x + 30, 319, t + "′", 18, BLUE)
        for j in range(i + 1):
            body += line(xs[j] + 30, 154, x + 30, 288, BLUE if j == i else "#93c5fd", 2 if j == i else 1.2)
    body += text(240, 372, "第 5 个位置“晓”的输出混合了前 5 个位置的信息", 13.5, GRAY)
    body += text(240, 394, "权重随输入而变；位置之间的连线就是 T×T 的表", 13.5, GRAY)
    body += line(480, 70, 480, 410, "#e2e8f0", 2)
    # 右：前馈层
    body += text(720, 78, "前馈层：每个位置各自过同一个变换", 16, TEAL, "bold")
    xs2 = [540 + i * 85 for i in range(5)]
    for x, t in zip(xs2, toks):
        body += box(x, 110, 60, 44, SOFT[BLUE], BLUE, width=1.4) + text(x + 30, 139, t + "′", 18, BLUE)
        body += arrow(x + 30, 154, x + 30, 194, GRAY, 1.6)
        body += box(x - 2, 196, 64, 52, SOFT[TEAL], TEAL, width=1.6) + text(x + 30, 218, "SwiGLU", 11.5, TEAL, "bold") + text(x + 30, 236, "W 相同", 11, GRAY)
        body += arrow(x + 30, 248, x + 30, 288, GRAY, 1.6)
        body += box(x, 290, 60, 44, SOFT[TEAL], TEAL, width=1.6) + text(x + 30, 319, t + "″", 18, TEAL)
    body += text(720, 372, "5 个框是同一组参数 W_gate、W_up、W_down", 13.5, GRAY)
    body += text(720, 394, "位置之间没有连线：换掉别的字，“晓”的结果不变", 13.5, GRAY)
    svg("ffn-vs-attention.svg", "注意力与前馈层的分工",
        "左：注意力里，每个位置的输出由它自己和前面所有位置加权混合而成，连线就是 T×T 的注意力表。右：前馈层对每个位置单独做同一个变换，"
        "5 个框共用同一组参数，位置之间没有连线。", 420, body)


def norm_axes():
    """[B, T, d] 张量上，RMSNorm/LayerNorm 与 BatchNorm 各沿哪些元素算统计量。"""
    body = text(480, 36, "归一化沿哪一维：同一个 [B, T, d] 张量，两种取法", 21, weight="bold")
    cell = 22
    B, T, D = 3, 4, 8

    def tensor(x0, y0, pick):
        out = ""
        for b in reversed(range(B)):
            ox, oy = x0 + b * 26, y0 - b * 26
            for t in range(T):
                for d in range(D):
                    on = pick(b, t, d)
                    out += f'<rect x="{ox + d * cell}" y="{oy + t * cell}" width="{cell}" height="{cell}" fill="{"#fdba74" if on else "#ffffff"}" stroke="{ORANGE if on else "#94a3b8"}" stroke-width="1"/>'
        return out

    for k, (title, pick, color, notes) in enumerate([
            ("RMSNorm / LayerNorm：每个 token 自己算", lambda b, t, d: b == 0 and t == 1, TEAL,
             ["一组统计量 = 一个 token 的 d 个数", "B × T 个 token，各算各的", "和 batch 里别的样本无关，", "训练、推理、batch 大小 1 都一样"]),
            ("BatchNorm：每个特征跨样本算", lambda b, t, d: d == 2, RED,
             ["一组统计量 = 某一维在全部 B×T 个位置上", "依赖 batch 里的其他样本，", "推理时要换成训练时攒下的均值；", "语言模型里基本不用"])]):
        x0 = 120 + k * 460
        body += text(x0 + 150, 84, title, 15.5, color, "bold")
        body += tensor(x0, 160, pick)
        body += text(x0 + 88, 270, "d（特征）→", 12.5, GRAY)
        body += f'<text x="{x0 - 14}" y="{160 + 44}" font-size="12.5" fill="{GRAY}" text-anchor="middle" transform="rotate(-90 {x0 - 14} {204})">T（位置）</text>'
        body += text(x0 + D * cell + 60, 108, "B（样本）↗", 12.5, GRAY, anchor="start")
        for i, n in enumerate(notes):
            body += text(x0 + 150, 304 + i * 22, n, 13.5)
    body += text(480, 410, "橙色是“一起算均值或均方根”的那组数。TinyLLM 用 RMSNorm：每个 token 的 128 维各算一个均方根", 14, INK, "bold")
    svg("norm-axes.svg", "归一化沿哪一维",
        "左右都是形状 [B, T, d] 的张量，画成 B 层、每层 T 行 d 列。左：RMSNorm 和 LayerNorm 对每个 token 的 d 个数算一组统计量，B×T 个 token 各算各的，"
        "与 batch 里的其他样本无关。右：BatchNorm 对每一维特征，在 batch 的全部位置上算一组统计量，依赖其他样本，语言模型里基本不用。", 430, body)


def data_eval_protocol():
    """第 12 章：训练流、batch 计划与验证窗口。"""
    body = text(500, 36, "数据流与评估口径：每个模型吃同一批数据，验证集每次算法相同", 20, weight="bold")

    def stream(y, color, label, count):
        out = text(40, y + 16, label, 14.5, color, "bold", "start") + text(40, y + 36, count, 12.5, GRAY, "normal", "start")
        x = 200
        for i, n in enumerate([7, 5, 9, 6, 8, 4, 7]):
            w = n * 11
            out += box(x, y, w, 34, SOFT[color], color, width=1.2) + text(x + w / 2, y + 22, f"诗{i + 1}", 11.5, color)
            x += w
            out += box(x, y, 22, 34, "#fef3c7", ORANGE, width=1.2) + mtext(x + 11, y + 22, "e", 11, ORANGE)
            x += 22
        return out

    body += stream(70, BLUE, "训练流", "225,007 个 token")
    body += text(960, 62, "e = <eos>", 12.5, ORANGE, anchor="end")
    body += text(500, 140, "每一步：用一个单独的随机数生成器（种子 1234）事先排好 32 个起点", 14)
    for i, x in enumerate([230, 420, 610]):
        body += line(x, 104, x, 156, RED, 2)
        body += box(x, 158, 260 if i < 2 else 240, 30, "#fff1f2", RED, width=1.4) + text(x + 120, 178, "65 个 token 的窗口", 12.5, RED)
    body += text(500, 214, "窗口内：输入 x = 前 64 个，目标 y = 后 64 个（往后错一位）", 14)
    xs = 230
    for i in range(9):
        body += box(xs + i * 30, 228, 28, 26, "#ffffff", GRAY, width=1) + mtext(xs + i * 30 + 14, 246, f"t{i}", 10.5)
    body += text(xs - 10, 246, "窗口", 12.5, GRAY, anchor="end")
    body += box(xs, 260, 8 * 30 - 2, 24, SOFT[BLUE], BLUE, width=1.2) + text(xs + 120, 277, "x：t0 … t63", 12.5, BLUE)
    body += box(xs + 30, 290, 8 * 30 - 2, 24, SOFT[TEAL], TEAL, width=1.2) + text(xs + 150, 307, "y：t1 … t64", 12.5, TEAL)
    body += text(560, 268, "→ 模型的种子只决定初始参数，", 13.5, INK, anchor="start")
    body += text(560, 290, "  换结构、换超参数时 batch 完全相同", 13.5, INK, anchor="start")
    body += stream(350, PURPLE, "验证流", "12,256 个 token")
    for k in range(4):
        x = 200 + k * 160
        body += box(x, 398, 156, 28, "#f5f3ff", PURPLE, width=1.3) + text(x + 78, 417, f"窗口 {k + 1}：64 个", 12, PURPLE)
    body += text(850, 417, "…… 共 191 个", 12.5, PURPLE, anchor="start")
    body += text(500, 460, "不重叠、不抽样、全部算一遍取平均：同一个模型每次得到同一个数", 14)
    body += text(500, 486, "nats/token × 每字 0.954 个 token ÷ ln 2 = 比特/字（换分词器也能比）", 14, GRAY)
    svg("data-eval-protocol.svg", "数据流与评估口径",
        "训练集和验证集各自拼成一条长 token 流，每首诗后接一个 <eos>。训练时用单独的随机数生成器事先排好每步 32 个起点，各切 65 个 token，前 64 个是输入、后 64 个是目标。"
        "验证时把整条验证流切成 191 个不重叠的 64-token 窗口，全部算一遍取平均，再换算成比特/字。", 510, body, width=1000)


def gpu_async_timeline():
    """第 13 章：CPU 排队发射内核，GPU 异步执行；.item() 让两边互相等。"""
    body = text(480, 36, "CPU 和 GPU 是两条时间线：CPU 只负责排队，GPU 慢慢执行", 20, weight="bold")

    def row(y, label, segs, color):
        out = text(110, y + 24, label, 14.5, color, "bold", "end")
        for x, w, t, kind in segs:
            fill = {"run": SOFT[color], "idle": "#ffffff", "wait": "#fef2f2"}[kind]
            stroke = {"run": color, "idle": "#cbd5e1", "wait": RED}[kind]
            dash = ' stroke-dasharray="5 4"' if kind != "run" else ""
            out += f'<rect x="{x}" y="{y}" width="{w}" height="36" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.3"{dash}/>'
            out += text(x + w / 2, y + 23, t, 12, RED if kind == "wait" else (color if kind == "run" else GRAY))
        return out

    body += text(480, 80, "好的写法：损失留在 GPU 上，每隔 N 步才取一次", 15, TEAL, "bold")
    body += row(96, "CPU", [(130, 70, "发射 step1", "run"), (200, 70, "发射 step2", "run"), (270, 70, "发射 step3", "run"), (340, 70, "发射 step4", "run"), (410, 360, "可以去准备下一批数据", "idle")], BLUE)
    body += row(142, "GPU", [(150, 150, "step1", "run"), (300, 150, "step2", "run"), (450, 150, "step3", "run"), (600, 150, "step4", "run")], TEAL)
    body += text(480, 210, "GPU 一刻不停；CPU 远远跑在前面，只受队列长度限制", 13.5, GRAY)
    body += text(480, 254, "坏的写法：每步都 loss.item()（或 print、.cpu()）", 15, RED, "bold")
    body += row(270, "CPU", [(130, 60, "发射 1", "run"), (190, 120, "item() 等 GPU", "wait"), (310, 60, "发射 2", "run"), (370, 120, "item() 等 GPU", "wait"), (490, 60, "发射 3", "run")], BLUE)
    body += row(316, "GPU", [(150, 150, "step1", "run"), (300, 30, "空", "idle"), (330, 150, "step2", "run"), (480, 30, "空", "idle"), (510, 150, "step3", "run")], TEAL)
    body += text(480, 384, "每次 .item() 都要把数从 GPU 拷回 CPU，CPU 只能等 GPU 把队列里的活干完；", 13.5)
    body += text(480, 406, "等到以后才发射下一步，GPU 在两步之间空转。计时也一样：测 GPU 时间前要 torch.cuda.synchronize()", 13.5)
    svg("gpu-async-timeline.svg", "CPU 与 GPU 的异步时间线",
        "上：CPU 依次发射每一步的计算，GPU 按顺序执行，两者互不等待，GPU 一直在忙。下：每步调用 loss.item() 时，CPU 必须等 GPU 算完并把数拷回来，"
        "之后才发射下一步，GPU 在两步之间空转。这是示意图，块的长短不代表实测时间。", 430, body)


def near_dup_index():
    """第 14 章：字二元组、重合度与倒排索引。"""
    import re as _re
    a = "倡楼启曙扉，杨柳正依依。莺啼知岁隔，条变识春归。"
    b = "倡楼启曙扉，园柳正依依。鸟鸣知岁隔，条变识春归。"

    def grams(t):
        s = _re.sub("[，。]", "", t)
        return [s[i:i + 2] for i in range(len(s) - 1)]

    ga, gb = grams(a), grams(b)
    shared = set(ga) & set(gb)
    score = len(shared) / min(len(set(ga)), len(set(gb)))
    body = text(500, 36, f"近重复：拆成字二元组，数共有的比例（下面这两段的重合度 {score:.2f}）", 20, weight="bold")
    for k, (poem, g, color) in enumerate([(a, ga, BLUE), (b, gb, TEAL)]):
        y = 70 + k * 120
        body += text(40, y + 20, f"诗 {'甲乙'[k]}：{poem}", 15, color, "bold", "start")
        x = 40
        for i, gram in enumerate(g):
            on = gram in shared
            body += box(x, y + 36, 42, 28, SOFT[color] if on else "#fff1f2", color if on else RED, width=1.2)
            body += text(x + 21, y + 55, gram, 12.5, INK if on else RED)
            x += 45
            if i == 9:
                x, y = 40, y + 34
    body += text(500, 326, f"共有 {len(shared)} 个（蓝绿框），不同的在红框里；重合度 = 共有数 ÷ 较短那首的二元组数 = {len(shared)}/{min(len(set(ga)), len(set(gb)))} = {score:.2f}", 14)
    body += text(500, 350, "逐句比较会因为每句差一个字而一句都对不上；二元组只丢掉含那个字的两三个", 13.5, GRAY)
    iy = 380
    body += text(500, iy + 8, "倒排索引：从二元组查到含有它的诗，只和至少共享一个二元组的诗比较", 15, ORANGE, "bold")
    entries = [("倡楼", "诗甲、诗乙、……"), ("正依", "诗甲、诗乙、……"), ("岁隔", "诗甲、诗乙、……"), ("杨柳", "诗甲、其他含“杨柳”的诗")]
    for i, (k_, v) in enumerate(entries):
        x = 70 + i * 225
        body += box(x, iy + 26, 70, 30, SOFT[ORANGE], ORANGE, width=1.3) + text(x + 35, iy + 46, k_, 13.5, ORANGE)
        body += arrow(x + 70, iy + 41, x + 90, iy + 41, GRAY, 1.6)
        body += text(x + 94, iy + 46, v, 12.5, INK, anchor="start")
    body += text(500, iy + 92, "925 首两两比较要 43 万对；有了索引，大部分诗只和几十首候选比较", 13.5, GRAY)
    svg("near-dup-index.svg", "二元组重合度与倒排索引",
        f"两首几乎相同的诗各自去掉标点后拆成相邻两字的二元组，共有 {len(shared)} 个，重合度 {score:.2f}。倒排索引记录每个二元组出现在哪些诗里，"
        "查重时只和至少共享一个二元组的诗比较，不必两两比较全部 43 万对。例子来自第 14 章脚本的输出。", 490, body, width=1000)


def lm_targets_mask():
    """第 15 章：错位出题，以及哪些位置算损失。"""
    body = text(480, 36, "一段 65 个 token 出 64 道题；不是每道题都算进损失", 20, weight="bold")
    toks = ["春", "眠", "不", "觉", "晓", "，", "处", "处"]
    cell = 60
    x0 = 160
    body += text(140, 92, "窗口", 14, GRAY, anchor="end")
    for i, t in enumerate(toks + ["…"]):
        body += box(x0 + i * cell, 70, cell - 6, 36, "#ffffff", GRAY, width=1.2) + text(x0 + i * cell + 27, 94, t, 16)
    body += text(140, 146, "输入 x", 14, BLUE, "bold", "end")
    body += text(140, 196, "目标 y", 14, TEAL, "bold", "end")
    for i in range(8):
        body += box(x0 + i * cell, 124, cell - 6, 36, SOFT[BLUE], BLUE, width=1.3) + text(x0 + i * cell + 27, 148, toks[i], 16, BLUE)
        nxt = toks[i + 1] if i + 1 < len(toks) else "…"
        body += box(x0 + i * cell, 174, cell - 6, 36, SOFT[TEAL], TEAL, width=1.3) + text(x0 + i * cell + 27, 198, nxt, 16, TEAL)
        body += arrow(x0 + i * cell + 27, 160, x0 + i * cell + 27, 172, GRAY, 1.4)
    body += text(720, 148, "第 t 道题：看 x 的前 t 个，", 13.5, INK, anchor="start")
    body += text(720, 170, "猜 y 的第 t 个", 13.5, INK, anchor="start")
    body += text(720, 196, "因果掩码保证看不到答案", 13.5, GRAY, anchor="start")
    # 掩码条
    body += text(480, 262, "哪些位置算损失（指令微调时的一条样本，补齐到同样长度）", 15, INK, "bold")
    segs = [("用户：写一句春天", 4, GRAY, "提问：-100，不算"), ("助手：春眠不觉晓", 4, TEAL, "回答：算"), ("<eos>", 1, ORANGE, "结束：要算"), ("<pad>", 2, "#94a3b8", "补齐：-100")]
    x = 100
    for label, n, color, note in segs:
        w = n * 62
        fill = SOFT.get(color, "#f1f5f9") if color != "#94a3b8" else "#f1f5f9"
        body += box(x, 280, w - 4, 40, fill, color, width=1.5) + text(x + w / 2 - 2, 305, label, 13.5, color if color != "#94a3b8" else GRAY, "bold")
        body += text(x + w / 2 - 2, 342, note, 12.5, color if color not in (GRAY, "#94a3b8") else GRAY)
        x += w
    body += text(480, 384, "预训练（第 14 章的拼接流）没有提问和补齐，64 个位置全部算；<eos> 在两种情况下都要算", 13.5)
    body += text(480, 406, "平均时分母是“算了损失的位置数”，不是窗口长度（第 5 节）", 13.5, GRAY)
    svg("lm-targets-mask.svg", "错位出题与损失掩码",
        "上：一段窗口里，输入 x 是前 64 个 token，目标 y 是往后错一位的 64 个 token，第 t 道题看 x 的前 t 个、猜 y 的第 t 个。下：指令微调的一条样本里，"
        "提问部分和补齐的 <pad> 标成 -100、不算损失，回答和 <eos> 算损失；预训练的拼接流里所有位置都算。", 430, body)


def adam_step():
    """第 16 章：AdamW 一步的数据流，以及每个参数占多少字节。"""
    body = text(480, 36, "AdamW 的一步：每个参数带着两个“记忆” m、v", 21, weight="bold")
    body += mod(40, 70, 170, 50, "梯度 g", "backward 得到", RED)
    body += mod(260, 70, 230, 50, "m ← β1·m + (1−β1)·g", "β1 = 0.9：梯度的平均方向", BLUE, 13.5)
    body += mod(260, 150, 230, 50, "v ← β2·v + (1−β2)·g^2", "β2 = 0.999：梯度的平均大小的平方", TEAL, 13.5)
    body += arrow(210, 95, 256, 95, GRAY, 2) + path("M225 95 V175 H256", GRAY, 2)
    body += mod(540, 110, 200, 50, "偏差修正", "m^ = m/(1−β1ᵗ)，v^ 同理", GRAY, 13.5)
    body += arrow(490, 95, 536, 125, GRAY, 2) + arrow(490, 175, 536, 145, GRAY, 2)
    body += mod(540, 200, 200, 50, "方向 ÷ 大小", "m^ / (√v^ + ε)", ORANGE, 14)
    body += arrow(640, 160, 640, 196, GRAY, 2)
    body += mod(540, 290, 200, 50, "乘学习率 η", "第 17 章的调度给出 η", ORANGE, 14)
    body += arrow(640, 250, 640, 286, GRAY, 2)
    body += mod(800, 290, 140, 50, "w ← w − 更新", None, PURPLE)
    body += arrow(740, 315, 796, 315, GRAY, 2)
    body += mod(800, 200, 140, 50, "衰减 η·λ·w", "直接作用在 w 上", RED, 13.5)
    body += arrow(870, 250, 870, 286, GRAY, 2)
    body += text(870, 186, "AdamW 的“W”", 12.5, RED)
    body += text(240, 262, "每个方向各自除以自己的 √v^：", 13.5, INK)
    body += text(240, 284, "梯度一直很大的方向步子变小，", 13.5, INK)
    body += text(240, 306, "一直很小的方向步子变大", 13.5, INK)
    # 内存
    y = 380
    body += text(480, y, "每个参数要多存几个数（FP32 训练）", 16, INK, "bold")
    parts = [("参数 w", 4, PURPLE), ("梯度 g", 4, RED), ("m", 4, BLUE), ("v", 4, TEAL)]
    x = 240
    for name, b_, color in parts:
        body += box(x, y + 18, 110, 40, SOFT[color], color, width=1.5) + text(x + 55, y + 43, f"{name}：{b_} 字节", 13.5, color, "bold")
        x += 120
    body += text(480, y + 84, "合计 16 字节 / 参数：第 12 章 131 万参数约 21 MB；70 亿参数就是 112 GB（还没算激活）", 14)
    body += text(480, y + 108, "m 和 v 存在 optimizer.state 里，续训时必须一起保存（第 21 章）；Adafactor 把 v 压成行、列两个向量来省内存", 13.5, GRAY)
    svg("adam-step.svg", "AdamW 一步的数据流与内存",
        "梯度 g 同时更新两个滑动平均：m 是梯度的平均方向（β1=0.9），v 是梯度平方的平均（β2=0.999）。偏差修正后用 m^ 除以 √v^ 加 ε 得到每个方向各自归一的步子，"
        "乘学习率后从参数里减掉；权重衰减直接作用在参数上。FP32 训练时每个参数要存参数、梯度、m、v 各 4 字节，共 16 字节。", y + 128, body)


def wsd_branches():
    """第 17、23 章：WSD 的主干停在峰值上，从检查点分叉出不同预算的模型。"""
    body = text(480, 36, "WSD：一条主干一直在峰值上，从检查点接一段衰减就得到一个“训完”的模型", 19, weight="bold")
    x0, y0, w, h = 110, 80, 760, 260
    body += line(x0, y0 + h, x0 + w, y0 + h, INK, 1.5) + line(x0, y0, x0, y0 + h, INK, 1.5)
    body += text(x0 + w, y0 + h + 26, "训练步数 →", 13, GRAY, anchor="end")
    body += f'<text x="{x0 - 30}" y="{y0 + h / 2}" font-size="13" fill="{GRAY}" text-anchor="middle" transform="rotate(-90 {x0 - 30} {y0 + h / 2})">学习率</text>'
    peak = y0 + 30
    warm = x0 + 50
    body += f'<path d="M{x0} {y0 + h} L{warm} {peak} L{x0 + w - 20} {peak}" stroke="{BLUE}" stroke-width="3" fill="none"/>'
    body += text(warm - 4, peak - 10, "warmup", 12.5, GRAY, anchor="end")
    body += text(x0 + w - 10, peak - 12, "主干：停在峰值，可以一直往后接", 13, BLUE, anchor="end")
    for i, (bx, label, color) in enumerate([(300, "预算 A", TEAL), (480, "预算 B", ORANGE), (660, "预算 C", PURPLE)]):
        dec = (bx - x0) * 0.25
        body += circle(bx, peak, 6, SOFT[color], color)
        body += f'<path d="M{bx} {peak} L{bx + dec} {y0 + h - 4}" stroke="{color}" stroke-width="2.6" fill="none" stroke-dasharray="7 4"/>'
        body += text(bx + dec + 4, y0 + h - 14, f"{label}：衰减到 0", 12.5, color, anchor="start")
        body += text(bx, peak - 12, "检查点", 12, color)
    body += text(480, y0 + h + 60, "衰减段约占这一个预算的最后 20%（第 17 章）；分叉不浪费主干：每个预算只多花一段衰减", 14)
    body += text(480, y0 + h + 84, "余弦调度的形状由总步数决定，换一个预算就要从头重训；第 23 章的逐轮淘汰正是靠这个分叉", 13.5, GRAY)
    svg("wsd-branches.svg", "WSD 的分叉",
        "横轴是训练步数，纵轴是学习率。主干经过 warmup 后一直停在峰值上。从主干上的几个检查点出发，各接一段线性衰减到 0，就得到预算 A、B、C 三个训练完成的模型，"
        "衰减段约占各自预算的最后 20%。这是示意图，不是某次实验的曲线。", y0 + h + 104, body)


def bf16_rounding():
    """第 19 章：1 附近的刻度，以及小更新被舍入吞掉。"""
    body = text(480, 36, "1 附近的刻度有多密：一次 0.001 的更新还留得住吗", 21, weight="bold")
    rows = [("FP32", 2 ** -23, BLUE, "间隔 2^-23 ≈ 0.00000012", "1.001 → 1.00100005", "留住了"),
            ("FP16", 2 ** -10, TEAL, "间隔 2^-10 ≈ 0.00098", "1.001 → 1.0009766", "大致留住"),
            ("BF16", 2 ** -7, RED, "间隔 2^-7 = 0.0078125", "1.001 → 1.0", "整个被吞掉")]
    x0, x1 = 140, 860
    lo, hi = 0.996, 1.010
    sx = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
    for i, (name, ulp, color, gap, res, verdict) in enumerate(rows):
        y = 100 + i * 100
        body += text(110, y + 6, name, 16, color, "bold", "end")
        body += line(x0, y, x1, y, "#94a3b8", 1.5)
        if ulp > 1e-5:
            k0 = int((lo - 1) / ulp) - 1
            k = k0
            while 1 + k * ulp <= hi:
                v = 1 + k * ulp
                if v >= lo:
                    body += line(sx(v), y - 8, sx(v), y + 8, color, 1.4)
                k += 1
        else:
            body += f'<rect x="{x0}" y="{y - 8}" width="{x1 - x0}" height="16" fill="{SOFT[color]}" stroke="none"/>'
            body += text(480, y + 4, "刻度密到画不出来", 11.5, color)
        body += circle(sx(1.0), y, 5, INK, INK) + circle(sx(1.001), y, 5, ORANGE, ORANGE)
        body += text(x1 + 10, y - 6, gap, 12.5, color, anchor="start") if False else ""
        body += text(sx(1.0), y + 30, gap, 12.5, color, anchor="start")
        body += text(x1, y + 30, f"{res}：{verdict}", 13, color, "bold", "end")
    body += text(sx(1.0), 76, "1.0", 12.5, INK) + text(sx(1.001) + 6, 76, "1.001", 12.5, ORANGE, anchor="start")
    body += text(480, 420, "学习率 1e-3 量级的一步更新，落在 BF16 的半个刻度以内，加上去再舍入就回到原值", 14.5)
    body += text(480, 446, "所以混合精度训练时，前向和反向可以用 BF16，参数本身（主权重）和优化器状态要留在 FP32", 14.5, INK, "bold")
    svg("bf16-rounding.svg", "1 附近的浮点刻度",
        "三条数轴画出 1.0 附近能精确表示的数。FP32 的间隔约 1.2e-7，1.001 能保留；FP16 的间隔约 0.00098，1.001 舍入成 1.0009766；BF16 的间隔是 0.0078125，"
        "1.001 舍入回 1.0，一次 0.001 的更新完全丢失。所以混合精度训练要把主权重留在 FP32。", 470, body)


def rng_timeline():
    """第 21 章：全局随机数被谁取走了。"""
    body = text(480, 36, "恢复训练为什么差了一点：全局随机数多被取走了一次", 21, weight="bold")

    def row(y, label, items, color):
        out = text(150, y + 24, label, 14.5, color, "bold", "end")
        x = 170
        for t, kind in items:
            w = {"step": 92, "iter": 108, "load": 120, "gap": 30}[kind]
            fill = {"step": SOFT[color], "iter": "#fef2f2", "load": "#f1f5f9", "gap": "#ffffff"}[kind]
            stroke = {"step": color, "iter": RED, "load": GRAY, "gap": "#ffffff"}[kind]
            out += box(x, y, w - 6, 38, fill, stroke, width=1.4)
            out += text(x + (w - 6) / 2, y + 24, t, 12.5, RED if kind == "iter" else (GRAY if kind in ("load", "gap") else color))
            x += w
        return out

    body += text(480, 78, "全局随机数是一串依次取用的数：r1 r2 r3 …，dropout 每步按顺序取", 14, GRAY)
    body += row(100, "一口气训完", [("step 119：r1", "step"), ("step 120：r2", "step"), ("step 121：r3", "step"), ("step 122：r4", "step"), ("…", "gap")], BLUE)
    body += row(170, "断电后恢复", [("读检查点", "load"), ("iter(loader)：r3", "iter"), ("step 121：r4", "step"), ("step 122：r5", "step"), ("…", "gap")], ORANGE)
    body += text(170, 160, "恢复了第 120 步之后的随机数状态，下一个该取的是 r3", 12.5, GRAY, anchor="start")
    body += text(480, 248, "恢复后从 epoch 1 中间开始，先创建一次迭代器，DataLoader 顺手取走 r3 给 worker 当种子；", 14)
    body += text(480, 272, "从第 121 步起每一步的 dropout 掩码都错开一位，损失差在小数点后第 4 位，120 步后参数最大差 0.52", 14)
    body += box(170, 300, 620, 46, SOFT[TEAL], TEAL, width=1.5)
    body += text(480, 329, "修法：DataLoader(..., generator=torch.Generator().manual_seed(种子))，它就不再碰全局随机数", 14, TEAL, "bold")
    svg("rng-timeline.svg", "全局随机数的取用顺序",
        "上：一口气训练时，第 119、120、121、122 步的 dropout 依次取全局随机数 r1、r2、r3、r4。下：从第 120 步的检查点恢复时，随机数状态恢复到该取 r3，"
        "但从 epoch 中间开始训练要先创建迭代器，DataLoader 取走了 r3，第 121 步的 dropout 只能取 r4，之后全部错开一位。给 DataLoader 自己的随机数生成器就能修好。", 370, body)


def eval_checklist_flow():
    """第 22 章：训练前、训练中、训练后、比较模型四个阶段各查什么。"""
    body = text(500, 36, "诊断清单按时间排：越早的检查越便宜，越晚的越接近真实质量", 20, weight="bold")
    stages = [("训练前", "几秒", BLUE, ["初始损失 ≈ ln V", "因果性：改后面的 token，", "前面的输出不变", "单 batch 能过拟合", "（用同一份训练代码）"]),
              ("训练中", "每隔几十步", TEAL, ["训练损失和验证损失", "梯度范数（裁剪前）", "学习率是否按计划走", "有没有 NaN / inf"]),
              ("训练后", "一次", ORANGE, ["固定提示词的生成样例", "简单结构指标", "（字数、标点、重复）"]),
              ("比较两个模型", "每次对照", PURPLE, ["同一验证集、同一口径", "配对 bootstrap 求差的区间", "多个种子，报平均和范围", "测试集只报告一次"])]
    x = 30
    for i, (name, when, color, items) in enumerate(stages):
        w = 225
        body += cbox(x, 70, w, 46, color) + text(x + w / 2, 92, name, 16, color, "bold") + text(x + w / 2, 110, when, 12, GRAY)
        body += box(x, 128, w, 170, "#ffffff", color, width=1.3)
        for j, it in enumerate(items):
            bullet = not it.startswith("（") and not (j > 0 and items[j - 1].endswith("，"))
            body += text(x + 14, 156 + j * 28, ("• " if bullet else "  ") + it, 13.5, INK, anchor="start")
        if i < 3:
            body += arrow(x + w, 93, x + w + 14, 93, GRAY, 2)
        x += w + 16
    body += text(500, 334, "第 4 节的矩阵说明：没有一项检查能抓住全部 6 个 bug，训练前的三项几秒内就抓住了其中 4 个", 14)
    body += text(500, 358, "有 bug 的模型验证损失可以比正确代码还低，所以“损失降得好”不能代替前面的检查", 13.5, GRAY)
    svg("eval-checklist-flow.svg", "诊断清单的四个阶段",
        "训练前花几秒做三项检查：初始损失约等于 ln V、因果性测试、单 batch 过拟合。训练中记录训练与验证损失、梯度范数和学习率。训练后看固定提示词的生成样例和简单结构指标。"
        "比较两个模型时在同一验证集上做配对 bootstrap，并结合多个种子。", 380, body, width=1000)


def tensor_parallel_swiglu():
    """第 25 章：SwiGLU 在两张卡上按列切、再按行切。"""
    body = text(500, 36, "张量并行：一个 SwiGLU 前馈层切到 2 张卡上", 21, weight="bold")
    for g, (color, gx) in enumerate([(BLUE, 60), (TEAL, 530)]):
        body += f'<rect x="{gx}" y="66" width="410" height="330" rx="14" fill="{SOFT[color]}" stroke="{color}" stroke-width="1.6"/>'
        body += text(gx + 205, 90, f"GPU {g}", 16, color, "bold")
        body += mod(gx + 105, 104, 200, 44, "输入 x（每张卡一份完整的）", "[T, d]", GRAY, 13)
        body += mod(gx + 20, 176, 170, 48, f"gate 的第 {g} 半列", "[d, h/2]", color, 13)
        body += mod(gx + 220, 176, 170, 48, f"up 的第 {g} 半列", "[d, h/2]", color, 13)
        body += path(f"M{gx + 205} 148 V162 H{gx + 105} V174", GRAY, 1.6) + path(f"M{gx + 205} 162 H{gx + 305} V174", GRAY, 1.6)
        body += mod(gx + 105, 250, 200, 44, "SiLU(gate)·up", "[T, h/2]：只在本卡算", color, 13)
        body += path(f"M{gx + 105} 224 V236 H{gx + 205} V248", GRAY, 1.6) + path(f"M{gx + 305} 224 V236 H{gx + 205}", GRAY, 1.6)
        body += mod(gx + 105, 322, 200, 48, f"down 的第 {g} 半行", "[h/2, d] → 部分和 [T, d]", color, 13)
        body += arrow(gx + 205, 294, gx + 205, 318, GRAY, 1.6)
    body += cbox(330, 420, 340, 50, RED) + text(500, 442, "all-reduce：两张卡的部分和相加", 15, RED, "bold") + mtext(500, 461, "y = y0 + y1   [T, d]", 13)
    body += path("M265 370 V444 H326", RED, 1.8) + path("M735 370 V444 H674", RED, 1.8)
    body += text(500, 500, "gate、up 按列切，down 按行切：中间的门控完全在各卡内部算完，前向只在最后通信一次", 14)
    body += text(500, 524, "每张卡只存一半的前馈层参数；代价是每层都要一次和激活一样大的通信，所以只在同一台机器的几张卡之间做", 13.5, GRAY)
    svg("tensor-parallel-swiglu.svg", "SwiGLU 的张量并行切分",
        "两张卡各有一份完整的输入 x。gate 和 up 的权重按列切成两半，每张卡算出中间宽度的一半，SiLU 门控在本卡内完成；down 的权重按行切成两半，每张卡算出一份部分和，"
        "最后用一次 all-reduce 把两份部分和相加，得到完整输出。", 545, body, width=1000)


def activation_recompute():
    """第 25 章：激活重计算只存每个 Block 的输入，反向时重算。"""
    body = text(480, 36, "激活重计算：前向少存，反向时把这一个 Block 再算一遍", 21, weight="bold")
    for row, (title, color, recompute) in enumerate([("普通训练：Block 内部的中间结果全都存着", GRAY, False), ("激活重计算：只存每个 Block 的输入", TEAL, True)]):
        y = 76 + row * 190
        body += text(60, y, title, 15.5, color, "bold", "start")
        for b in range(4):
            x = 60 + b * 210
            body += box(x, y + 18, 180, 60, SOFT[BLUE], BLUE, width=1.4) + text(x + 90, y + 44, f"Block {b + 1}", 14, BLUE, "bold")
            body += box(x - 4, y + 90, 20, 22, "#fde68a", ORANGE, width=1.2)
            if not recompute:
                for k in range(5):
                    body += box(x + 26 + k * 30, y + 90, 24, 22, "#fde68a", ORANGE, width=1.2)
            else:
                for k in range(5):
                    body += box(x + 26 + k * 30, y + 90, 24, 22, "#ffffff", "#cbd5e1", width=1, dash=True)
            if b < 3:
                body += arrow(x + 180, y + 48, x + 208, y + 48, GRAY, 1.6)
        body += text(60, y + 134, "黄格：存在显存里、等反向用的激活" if not recompute else "黄格：Block 的输入；虚线格：前向算完就扔，反向到这个 Block 时从输入重算", 13, GRAY, anchor="start")
    body += path("M900 410 H690 V330", RED, 2) if False else ""
    body += text(480, 460, "本章实测：激活省下九成多，梯度逐位相同，每步慢约三成（多了一次前向）", 14.5, INK, "bold")
    svg("activation-recompute.svg", "激活重计算",
        "上：普通训练时，每个 Block 内部的中间结果都要存着等反向用。下：激活重计算只存每个 Block 的输入，内部的中间结果算完就扔，反向传播到这个 Block 时从输入把前向重算一遍。"
        "第 25 章的实验里，激活显存省下九成多，梯度逐位相同，每步慢约三成。", 480, body)


def expert_parallel():
    """第 26 章：专家并行，token 经两次 all-to-all 去对应的卡再回来。"""
    body = text(500, 36, "专家并行：8 个专家放在 4 张卡上，token 要去专家所在的卡算完再回来", 19, weight="bold")
    colors = [BLUE, TEAL, ORANGE, PURPLE]
    toks = [[0, 5, 2, 7], [1, 1, 6, 3], [4, 0, 1, 5], [1, 2, 1, 6]]
    for g in range(4):
        x = 40 + g * 240
        c = colors[g]
        body += text(x + 105, 76, f"GPU {g}：专家 {2 * g}、{2 * g + 1}", 14, c, "bold")
        body += box(x, 88, 210, 44, "#ffffff", "#cbd5e1", width=1.2)
        for i, e in enumerate(toks[g]):
            ec = colors[e // 2]
            body += box(x + 8 + i * 50, 96, 44, 28, SOFT[ec], ec, width=1.2) + mtext(x + 30 + i * 50, 115, f"→E{e}", 12, ec)
        body += box(x, 230, 210, 50, SOFT[c], c, width=1.6)
        body += text(x + 105, 252, f"专家 {2 * g} 和 {2 * g + 1} 计算", 13.5, c, "bold")
        load = sum(1 for row in toks for e in row if e // 2 == g)
        body += text(x + 105, 271, f"收到 {load} 个 token", 12.5, GRAY)
        body += box(x, 360, 210, 44, "#ffffff", "#cbd5e1", width=1.2) + text(x + 105, 387, "结果回到原来的卡，按路由分数加权", 12, GRAY)
    body += cbox(40, 160, 920, 40, RED) + text(500, 186, "all-to-all（分发）：每个 token 发到它选中的专家所在的卡", 14, RED, "bold")
    body += cbox(40, 300, 920, 40, RED) + text(500, 326, "all-to-all（收回）：算完的结果发回 token 原来的卡", 14, RED, "bold")
    for g in range(4):
        x = 145 + g * 240
        body += arrow(x, 132, x, 158, GRAY, 1.6) + arrow(x, 200, x, 228, GRAY, 1.6) + arrow(x, 280, x, 298, GRAY, 1.6) + arrow(x, 340, x, 358, GRAY, 1.6)
    loads = [sum(1 for row in toks for e in row if e // 2 == g) for g in range(4)]
    body += text(500, 440, f"这一层要等最慢的那张卡：GPU 0 收到 {loads[0]} 个 token，其余各 {min(loads)} 个。负载越不均，其他卡空等越久", 14)
    body += text(500, 464, "（示意：每张卡 4 个 token、每个 token 只画第一选择；实际是 top-2，通信量更大）", 13, GRAY)
    svg("expert-parallel.svg", "专家并行与 all-to-all",
        "8 个专家分在 4 张卡上，每张卡两个。每张卡上的 token 先由路由器选出专家，第一次 all-to-all 把 token 发到专家所在的卡，各卡算完后第二次 all-to-all 把结果送回原来的卡。"
        "一层的时间由收到 token 最多的那张卡决定，这就是负载均衡要解决的问题。示意图，token 分配是举例。", 485, body, width=1000)


def sampling_pipeline():
    """第 27 章：从 logits 到下一个 token 的每一步。"""
    body = text(500, 36, "生成循环：从最后一个位置的 logits 到下一个 token", 21, weight="bold")
    steps = [("模型前向", "最后一个位置的 logits", GRAY, "第 12 章"),
             ("重复惩罚", "出现过的 token 降分", ORANGE, "第 8 节"),
             ("约束掩码", "不合格式的置为 −∞", RED, "第 9 节"),
             ("÷ 温度 T，softmax", "T 小更尖，T 大更平", BLUE, "第 1、5 节"),
             ("top-k / top-p 截断", "砍掉长尾，重新归一化", TEAL, "第 2 节"),
             ("按概率抽一个", "用固定的 generator", PURPLE, "第 6 节")]
    x = 20
    for i, (name, note, color, ref) in enumerate(steps):
        w = 146
        body += cbox(x, 80, w, 70, color) + text(x + w / 2, 106, name, 14, color, "bold") + text(x + w / 2, 126, note, 11, INK) + text(x + w / 2, 143, ref, 11, GRAY)
        if i < len(steps) - 1:
            body += arrow(x + w, 115, x + w + 14, 115, GRAY, 2)
        x += w + 14
    body += path("M675 150 V176 H770", BLUE, 1.6, dash=True) if False else ""
    body += box(560, 180, 410, 40, "#ffffff", PURPLE, width=1.4, dash=True)
    body += text(765, 205, "贪心：跳过温度、截断和抽样，直接取 argmax", 13, PURPLE)
    body += path("M904 150 V178", PURPLE, 1.4, dash=True)
    body += mod(380, 250, 240, 50, "是 <eos>，或到 max_new_tokens？", None, INK, 13.5)
    body += path("M880 150 V170 H975 V275 H624", GRAY, 2)
    body += text(640, 270, "否：接到序列末尾，回到模型前向", 13, GRAY, anchor="start") if False else ""
    body += path("M380 275 H20 V115 H26", GRAY, 2)
    body += text(200, 266, "否：新 token 接到末尾，再走一圈", 13, GRAY)
    body += arrow(500, 300, 500, 330, GRAY, 2)
    body += text(500, 350, "是：停止，把新 token 整段解码成文字", 13.5, INK, "bold")
    body += text(500, 390, "每一步都只改“这一次怎么选”，模型参数一个也不动；换采样方式不用重新训练", 14, GRAY)
    svg("sampling-pipeline.svg", "生成循环的每一步",
        "模型前向得到最后一个位置的 logits，依次经过重复惩罚、约束掩码、除以温度后 softmax、top-k 或 top-p 截断，再按概率抽一个 token；贪心解码跳过后三步直接取最大值。"
        "如果抽到 <eos> 或达到最大长度就停止，否则把新 token 接到序列末尾再走一圈。", 410, body, width=1000)


def roofline():
    """第 28 章：roofline，用 H100 的公布值画 prefill 与 decode 的位置。"""
    peak, bw = 989e12, 3.35e12            # H100 SXM：BF16 稠密张量算力、显存带宽（NVIDIA 公布值）
    ridge = peak / bw
    I = np.logspace(-0.3, 4, 200)
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    ax.plot(I, np.minimum(peak, bw * I) / 1e12, color=INK, lw=2.2)
    ax.axvline(ridge, color=GRAY, ls="--", lw=1)
    ax.text(ridge * 1.08, 30, f"拐点 ≈ {ridge:.0f} FLOP/字节", fontsize=10.5, color=GRAY)
    pts = [(1, "decode，batch 1", RED), (10, "prefill 10 个 token", ORANGE), (64, "decode，batch 64", BLUE), (2048, "prefill 2048 个 token", TEAL)]
    for x, label, color in pts:
        y = min(peak, bw * x) / 1e12
        ax.scatter([x], [y], color=color, s=60, zorder=3)
        ax.annotate(f"{label}\n≈ {y:.0f} TFLOP/s", (x, y), textcoords="offset points", xytext=(8, -26 if x < 100 else 8), fontsize=10, color=color)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(1, 4000)
    ax.set_xlabel("算术强度：每读 1 字节权重做多少次浮点运算（≈ 一次前向里同时处理的 token 数）")
    ax.set_ylabel("能达到的算力上限（TFLOP/s）")
    ax.text(2, peak / 1e12 * 0.55, "左边斜线：卡在带宽", fontsize=11, color=RED)
    ax.text(ridge * 3, peak / 1e12 * 0.55, "右边平线：卡在算力", fontsize=11, color=TEAL)
    ax.grid(alpha=0.25, which="both")
    save_plot(fig, "roofline.svg", "prefill 与 decode 在 roofline 上的位置",
              f"用 H100 SXM 的公布值（BF16 稠密 {peak / 1e12:.0f} TFLOP/s、显存带宽 3.35 TB/s）画出的 roofline，拐点约 {ridge:.0f} FLOP/字节。"
              "BF16 权重的矩阵乘里，每个权重 2 字节、每个 token 做 2 次运算，算术强度约等于一次处理的 token 数（只算权重读取的粗略估计）。"
              "decode batch 1 和 10 个 token 的 prefill 都在左边卡在带宽，2048 个 token 的 prefill 才到右边卡在算力。")


def chunked_prefill_timeline():
    """第 28 章：长提示词的 prefill 不分块与分块时，别人的 decode 怎样排队。"""
    body = text(480, 36, "chunked prefill：长提示词切成几块，正在生成的请求可以插进来", 20, weight="bold")

    def row(y, label, segs):
        out = text(118, y + 22, label, 14, INK, "bold", "end")
        for x, w, t, color in segs:
            out += box(x, y, w - 3, 34, SOFT[color], color, width=1.3) + text(x + (w - 3) / 2, y + 22, t, 12, color)
        return out

    body += text(130, 76, "不分块：一次前向做完新请求 C 的 2000 个 token", 14.5, RED, "bold", "start")
    segs = [(130, 50, "A、B", BLUE), (180, 50, "A、B", BLUE), (230, 330, "C 的 prefill（2000 个 token）", ORANGE), (560, 70, "A、B、C", BLUE), (630, 70, "A、B、C", BLUE)]
    body += row(92, "每次前向", segs)
    body += text(395, 150, "A、B 在这段时间里一个字也出不来：用户看到“卡了一下”", 13, RED)
    body += text(130, 196, "分块：C 的 prefill 切成 4 块，每次前向带上 A、B 的 decode", 14.5, TEAL, "bold", "start")
    segs2 = [(130, 50, "A、B", BLUE)] + [(180 + i * 110, 110, f"C 第 {i + 1} 块 + A、B", TEAL) for i in range(4)] + [(620, 70, "A、B、C", BLUE)]
    body += row(212, "每次前向", segs2)
    body += text(400, 270, "A、B 每次前向都多出一个字；C 的第一个字反而晚一点出来", 13, TEAL)
    body += text(480, 320, "分块不改变结果（本章第 9 节验证了误差为 0），改变的是谁等谁：别人的 ITL 变稳，C 自己的 TTFT 略长", 14)
    body += text(480, 344, "块越小，插得越勤，但每块都要重读一遍已经缓存的 KV，开销变大；块大小要按负载调", 13.5, GRAY)
    svg("chunked-prefill-timeline.svg", "chunked prefill 的调度",
        "上：不分块时，新请求 C 的 2000 个 token 一次前向做完，这段时间里正在生成的 A、B 一个字也出不来。下：把 C 的 prefill 切成 4 块，每次前向同时带上 A、B 的 decode，"
        "A、B 每次前向都能多出一个字，C 的首字稍晚。示意图，块的长短不代表实测时间。", 365, body)


def gpu_memory_hierarchy():
    """第 29 章：GPU 的存储层次（H100 SXM 公布值）。"""
    body = text(480, 36, "GPU 的存储层次：越靠近计算单元越快，也越小（H100 SXM）", 20, weight="bold")
    levels = [("HBM 显存", "80 GB", "约 3.35 TB/s", "权重、KV cache、激活都在这里", GRAY, 700),
              ("L2 缓存", "50 MB", "全卡共享", "自动缓存，程序管不了", BLUE, 600),
              ("每个 SM 的共享内存 / L1", "最多 228 KB（共 132 个 SM）", "程序显式管理", "FlashAttention 把 Q、K、V 的块放在这里", TEAL, 470),
              ("寄存器", "每个 SM 256 KB", "最快", "正在算的那几个数", ORANGE, 320)]
    y = 70
    for name, size, speed, note, color, w in levels:
        x = 480 - w / 2
        body += cbox(x, y, w, 62, color) + text(480, y + 24, f"{name}：{size}", 15, color, "bold") + text(480, y + 46, f"{speed}；{note}", 12.5, INK)
        y += 74
    body += text(480, y + 18, "朴素注意力把 T×T 的分数表写回 HBM 再读出来；分块内核让一个方块的计算从头到尾留在共享内存里，", 13.5)
    body += text(480, y + 40, "只把输出写回 HBM。块大小的上限就是这 228 KB（第 5 节）", 13.5)
    body += text(480, y + 68, "数据来自 NVIDIA Hopper 调优指南与 H100 产品说明；其他 GPU 的容量不同，A100 每个 SM 的共享内存最多 164 KB", 12.5, GRAY)
    svg("gpu-memory-hierarchy.svg", "GPU 的存储层次",
        "从下往上：H100 SXM 的 HBM 显存 80 GB、带宽约 3.35 TB/s，存权重、KV cache 和激活；L2 缓存 50 MB，全卡共享；每个 SM 的共享内存最多 228 KB，共 132 个 SM，"
        "由程序显式管理，FlashAttention 把 Q、K、V 的块放在这里；寄存器每个 SM 256 KB。分块注意力让计算留在共享内存里，只把输出写回 HBM。", y + 90, body)


def quant_grouping():
    """第 30 章：同一个矩阵，按张量、按通道、分组时，哪些权重共用一个缩放因子。"""
    body = text(500, 36, "量化粒度：同一种颜色的权重共用一个缩放因子", 21, weight="bold")
    rows, cols, cell = 6, 16, 16
    palette = ["#bfdbfe", "#99f6e4", "#fde68a", "#fecaca", "#ddd6fe", "#fbcfe8", "#bbf7d0", "#fed7aa"]
    configs = [("按张量：1 个缩放因子", lambda r, c: 0, "每个权重 + 0 位", "一个大数会拉低所有数的精度"),
               ("按通道（每行一个）：6 个", lambda r, c: r, "每个权重 + 16/16 = 1 位（这里每行只有 16 个数）", "TinyLLM 的行有 128～341 个数，约 + 0.1 位"),
               ("分组 g = 4：24 个", lambda r, c: r * 4 + c // 4, "每个权重 + 16/4 = 4 位", "实际常用 g = 32～128，+ 0.5～0.125 位")]
    for k, (title, gid, cost, note) in enumerate(configs):
        x0 = 40 + k * 320
        body += text(x0 + cols * cell / 2, 78, title, 15, INK, "bold")
        for r in range(rows):
            for c in range(cols):
                g = gid(r, c)
                body += f'<rect x="{x0 + c * cell}" y="{96 + r * cell}" width="{cell}" height="{cell}" fill="{palette[g % len(palette)]}" stroke="#ffffff" stroke-width="1"/>'
        if k == 2:
            for r in range(rows):
                for c in range(0, cols, 4):
                    body += f'<rect x="{x0 + c * cell}" y="{96 + r * cell}" width="{4 * cell}" height="{cell}" fill="none" stroke="{INK}" stroke-width="0.8"/>'
        body += text(x0 + cols * cell / 2, 216, cost, 12.5, BLUE)
        body += text(x0 + cols * cell / 2, 238, note, 12, GRAY)
    body += text(500, 282, "缩放因子 s = 这一组里绝对值最大的数 ÷ 7（INT4 对称）。组越小，s 越贴近组内的数，误差越小；", 14)
    body += text(500, 306, "每个缩放因子按 FP16 存，多花 16 位，摊到组内每个权重上就是 16/g 位（第 3 节的“每个权重几位”）", 14)
    svg("quant-grouping.svg", "量化粒度",
        "同一个 6 行 16 列的权重矩阵，颜色相同的格子共用一个缩放因子。按张量时整个矩阵一个；按通道时每行一个，共 6 个；分组 g=4 时每行每 4 个一组，共 24 个。"
        "组越小误差越小，但每个缩放因子要多存 16 位，摊到每个权重上是 16/g 位。", 325, body, width=1000)


def quant_mapping():
    """第 30 章：x → q → x̂ 的往返，对称与非对称。"""
    body = text(480, 36, "量化是把一段实数映射到一排整数刻度上（INT4）", 21, weight="bold")
    x0, x1 = 120, 860
    for k, (title, lo, hi, levels, color, note) in enumerate([
            ("对称：s = max|x| / 7，整数 −7…7", -1.0, 1.0, [i / 7 for i in range(-7, 8)], BLUE, "0 正好在刻度上；适合大致关于 0 对称的权重"),
            ("非对称：s = (max − min) / 15，零点 z 把 0 放在刻度上，整数 0…15", -0.3, 1.0, None, TEAL, "范围贴着数据：有偏的激活（比如 SiLU 输出）一个刻度也不浪费")]):
        y = 110 + k * 150
        body += text(x0, y - 26, title, 15, color, "bold", "start")
        body += line(x0, y, x1, y, "#94a3b8", 1.5)
        sx = lambda v: x0 + (v - (-1.0)) / 2.0 * (x1 - x0)
        if levels is None:
            s = (hi - lo) / 15
            levels = [lo + i * s for i in range(16)]
        for i, v in enumerate(levels):
            body += line(sx(v), y - 9, sx(v), y + 9, color, 1.6)
        body += f'<rect x="{sx(lo)}" y="{y - 4}" width="{sx(hi) - sx(lo)}" height="8" fill="{SOFT[color]}" stroke="none"/>' if k == 1 else ""
        xv = 0.53
        near = min(levels, key=lambda v: abs(v - xv))
        body += circle(sx(xv), y, 5, ORANGE, ORANGE) + text(sx(xv), y - 16, "x", 13, ORANGE, "bold")
        body += circle(sx(near), y, 5, "#ffffff", INK) + text(sx(near) + 8, y + 26, "还原值", 12.5, INK, "bold", "start")
        body += text(x1, y + 52, note, 12.5, GRAY, anchor="end")
        body += text(x0 - 10, y + 5, "−1" if k == 0 else "", 12, GRAY, anchor="end") + text(x1 + 10, y + 5, "1", 12, GRAY, anchor="start")
    body += text(480, 400, "x 先除以 s 再四舍五入成整数 q，存起来；用的时候还原成 s·(q − z)，落在最近的刻度上，误差最多半个刻度 s/2", 14)
    body += text(480, 424, "刻度间隔 s 决定误差：位数少一位，s 大一倍；一组里的最大值越大，s 越大（第 3 节为什么要分组）", 13.5, GRAY)
    svg("quant-mapping.svg", "量化的数值映射",
        "上：对称 INT4 量化，把 −max|x| 到 max|x| 均匀分成 15 个刻度，0 正好落在刻度上。下：非对称量化按最小值和最大值定范围，用零点把 0 放到刻度上，16 个刻度都落在数据范围内。"
        "一个数 x 量化后还原成最近的刻度，误差最多半个刻度。", 445, body)


def residual_scaling():
    """第 10 章：真实 Block 上，1/√(2L) 对残差流 RMS 和训练结果的影响。"""
    src = DATA / "tinyllm-initialization-residuals-log.json"
    if not src.exists():
        print("skip residual-scaling: run scripts/build-tinyllm-code.py initialization-and-residuals to create", src)
        return
    log = json.loads(src.read_text(encoding="utf-8"))
    rms, tr = log["rms"], log["train"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), layout="constrained", gridspec_kw={"width_ratios": [1.3, 1]})
    for key, color, ls, label in (("24|False", RED, "-", "24 层，不缩放"), ("24|True", TEAL, "-", "24 层，乘 1/√(2L)"),
                                  ("8|False", RED, "--", "8 层，不缩放"), ("8|True", TEAL, "--", "8 层，乘 1/√(2L)")):
        ys = rms[key]
        a1.plot(range(len(ys)), ys, color=color, ls=ls, lw=2, label=label)
        a1.annotate(f"{ys[-1]:.2f}", (len(ys) - 1, ys[-1]), textcoords="offset points", xytext=(5, -3), fontsize=10, color=color)
    a1.set_xlabel("第几个 Block 之后（0 是嵌入）")
    a1.set_ylabel("残差流的 RMS（初始化时，3 个种子平均）")
    a1.set_title("不缩放：越深涨得越多；缩放后几乎不随深度变", fontsize=12)
    a1.legend(fontsize=10)
    a1.grid(alpha=0.25)
    groups = [("1e-2", "0.01"), ("3e-3", "0.003")]
    for gi, (lab, key) in enumerate(groups):
        for k, (scaled, color) in enumerate((("False", RED), ("True", TEAL))):
            vals = tr[f"{key}|{scaled}"]
            x = gi * 1.0 + (k - 0.5) * 0.32
            a2.scatter([x] * 3, vals, color=color, s=28, zorder=3)
            m = sum(vals) / 3
            a2.scatter([x], [m], color=color, marker="D", s=70, zorder=4)
            a2.annotate(f"{m:.3f}", (x, m), textcoords="offset points", xytext=(8, -4), fontsize=10, color=color)
    a2.set_xticks([0, 1], ["峰值学习率 1e-2", "峰值学习率 3e-3"])
    a2.set_xlim(-0.6, 1.6)
    a2.set_ylabel("验证损失（8 层，240 步）")
    a2.set_title("训练后：两档学习率下都差约 0.33", fontsize=12)
    a2.scatter([], [], color=RED, label="不缩放")
    a2.scatter([], [], color=TEAL, label="乘 1/√(2L)")
    a2.legend(fontsize=10, loc="center right")
    a2.grid(alpha=0.25, axis="y")
    save_plot(fig, "residual-scaling.svg", "残差输出投影缩放的实测",
              f"左：TinyLLM 的 Pre-RMSNorm Block（宽度 64），初始化时残差流的 RMS 随层数的变化。不缩放时 24 层最后涨到 {rms['24|False'][-1]:.2f}，是嵌入的 {rms['24|False'][-1] / rms['24|False'][0]:.0f} 倍；"
              f"proj 和 down 乘 1/√(2L) 后，8 层和 24 层都停在 {rms['8|True'][-1]:.2f} 附近。右：8 层模型训练 240 步的验证损失，3 个种子（菱形是平均）："
              f"峰值 1e-2 时 {sum(tr['0.01|False']) / 3:.3f} 对 {sum(tr['0.01|True']) / 3:.3f}，峰值 3e-3 时 {sum(tr['0.003|False']) / 3:.3f} 对 {sum(tr['0.003|True']) / 3:.3f}。")


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


def qwen3_family():
    """快速体验附录：以 Qwen3-4B 为例，一个 base 模型怎样分出一族模型。
    训练阶段取自 Qwen3 技术报告（arXiv 2505.09388）第 3.2、4.5 节；模型名和派生关系取自
    Hugging Face 上 Qwen 组织各模型卡的 base_model 标注（2026-11 查询）。"""
    body = text(480, 36, "一个 base，一族模型：以 Qwen3-4B 为例", 21, weight="bold")
    stages = [
        (30, GRAY, "第 1 阶段 · 通用", ["30 万亿以上 token", "序列长度 4K", "学语言和世界知识"]),
        (250, TEAL, "第 2 阶段 · 推理", ["约 5 万亿高质量 token", "多放 STEM、代码、合成数据", "学习率加快衰减"]),
        (470, TEAL, "第 3 阶段 · 长上下文", ["数千亿 token，序列 32K", "RoPE base 1 万 → 100 万", "长文本占大头"]),
    ]
    for x, color, title, lines in stages:
        body += cbox(x, 66, 190, 108, color)
        body += text(x + 95, 92, title, 15, color, "bold")
        for i, s in enumerate(lines):
            body += text(x + 95, 116 + i * 20, s, 13, INK)
    for a, b in ((220, 250), (440, 470), (660, 700)):
        body += arrow(a + 2, 120, b - 3, 120, GRAY, 2.2)
    body += box(700, 66, 230, 108, "#ffffff", INK, width=2.4)
    body += text(815, 98, "Qwen3-4B-Base", 17, INK, "bold")
    body += text(815, 124, "发布：给它文字，它往下接", 13, INK)
    body += text(815, 146, "上下文 32K", 13, GRAY)
    # 阶段标注
    body += line(30, 188, 220, 188, GRAY, 1.6) + text(125, 206, "预训练", 14, GRAY, "bold")
    body += line(250, 188, 660, 188, TEAL, 1.6) + text(455, 206, "今天常说的“中训练”（报告里算预训练的后两阶段）", 14, TEAL, "bold")
    # 后训练
    body += arrow(815, 176, 815, 237, ORANGE, 2.4)
    body += cbox(700, 240, 230, 104, ORANGE)
    body += text(815, 266, "后训练：从大模型蒸馏", 15, ORANGE, "bold")
    body += text(815, 290, "老师是 Qwen3-32B / 235B-A22B", 13, INK)
    body += text(815, 310, "先学老师写的回答，", 13, INK)
    body += text(815, 330, "再让自己的分布贴近老师", 13, INK)
    body += arrow(815, 346, 815, 377, ORANGE, 2.4)
    body += box(700, 380, 230, 70, "#ffffff", INK, width=2.4)
    body += text(815, 408, "Qwen3-4B", 17, INK, "bold")
    body += text(815, 432, "发布：会对话，思考 / 不思考两种模式", 12.5, INK)
    # 从 base 派生：向量与打分模型
    body += path("M760 176 V222 H550 V240", PURPLE, 2.2)
    body += cbox(440, 243, 220, 92, PURPLE)
    body += text(550, 268, "Qwen3-Embedding-4B", 14.5, PURPLE, "bold")
    body += text(550, 290, "Qwen3-Reranker-4B", 14.5, PURPLE, "bold")
    body += text(550, 314, "从 Base 训成向量 / 打分模型", 13, INK)
    # 读名字
    body += cbox(30, 228, 398, 172, GRAY)
    body += text(48, 254, "名字怎么读", 15, INK, "bold", "start")
    legend = [
        ("-Base", "只做完预训练和中训练"),
        ("不带后缀", "做过后训练，能按对话格式回答"),
        ("-FP8/-AWQ/-GGUF", "同一个模型，换一种存储格式"),
        ("-Instruct/-Thinking", "只保留一种模式的对话模型"),
        ("-2507", "2025 年 7 月的更新版"),
    ]
    for i, (name, meaning) in enumerate(legend):
        y = 280 + i * 25
        body += mtext(48, y, name, 13, BLUE, "bold", "start")
        body += text(228, y, meaning, 13, INK, anchor="start")
    # 从对话模型派生
    body += path("M700 438 H135 V477", GRAY, 2) + path("M365 438 V477", GRAY, 2)
    body += cbox(30, 480, 210, 96, GRAY)
    body += text(135, 504, "量化版", 15, INK, "bold")
    body += mtext(135, 528, "-FP8  -AWQ  -GGUF", 13, BLUE)
    body += text(135, 552, "不再训练，只压缩权重", 13, INK)
    body += cbox(260, 480, 210, 96, RED)
    body += text(365, 504, "安全专项", 15, RED, "bold")
    body += mtext(365, 528, "Qwen3Guard-*-4B", 13, BLUE)
    body += text(365, 552, "再做一轮后训练，判断或拒绝", 13, INK)
    body += path("M815 452 V477", GRAY, 2, dash=True)
    body += box(700, 480, 230, 96, "#ffffff", GRAY, dash=True, width=1.6)
    body += text(815, 504, "Qwen3-4B-Instruct-2507", 13.5, INK, "bold")
    body += text(815, 524, "Qwen3-4B-Thinking-2507", 13.5, INK, "bold")
    body += text(815, 550, "官方称作两种模式各自的更新版", 12.5, GRAY)
    body += text(815, 568, "模型卡没写从哪个检查点出发", 12.5, GRAY)
    body += text(480, 612, "训练阶段来自 Qwen3 技术报告；模型之间的实线取自 Hugging Face 模型卡的 base_model 标注，虚线只有官方文字说明。", 13, GRAY)
    svg("qwen3-family.svg", "以 Qwen3-4B 为例的模型族谱",
        "上排是训练阶段：第 1 阶段在 30 万亿以上 token 上用 4K 序列学语言和知识（预训练）；第 2 阶段用约 5 万亿高质量 token 加强推理、学习率加快衰减；"
        "第 3 阶段用 32K 长序列、把 RoPE base 从 1 万调到 100 万（这两段就是今天常说的中训练）；三段做完发布 Qwen3-4B-Base。"
        "Base 经过从 Qwen3-32B、235B-A22B 的蒸馏式后训练，得到能对话、有思考和不思考两种模式的 Qwen3-4B。"
        "Qwen3-Embedding-4B 和 Qwen3-Reranker-4B 从 Base 训出；FP8、AWQ、GGUF 是 Qwen3-4B 的量化版；Qwen3Guard 在 Qwen3-4B 上再做安全专项训练；"
        "Instruct-2507 与 Thinking-2507 是官方所说的两种模式各自的更新版。", 640, body)


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
    quickstart_loss()
    quickstart_flow()
    quickstart_position_add()
    qwen3_family()
    # 第 10、8、4、5、16、19 章；数据图需要先运行 scripts/tinyllm-figure-data.py
    for fn in (init_fan_in, residual_depth, residual_path, activation_fit, swiglu_vs_ffn, utf8_lengths, bpe_merges,
               label_shift, embedding_lookup, tied_output, kv_cache, optimizer_paths, optimizer_curves, adamw_vs_l2,
               float_formats, float_spacing, autocast_flow, knowledge_sources, agent_loop, transformer_to_gpt, gpt_scale, modern_block, autograd_cost, vjp_matmul, attention_steps, multihead_shapes, attention_ablation,
               position_methods, sinusoidal_heatmap, rope_rotation, position_ablation, block_anatomy, block_depth, architecture_timeline, architecture_cost,
               tinyllm_model_shapes, tinyllm_model_loss, sampling_truncate, sampling_difficulty, guided_decoding,
               kv_cache_size, latency_metrics, gpu_step_anatomy,
               data_pipeline_funnel, data_pipeline_near_dup, data_pipeline_leak, data_pipeline_packing, data_pipeline_coverage,
               lm_loss_poem, lm_loss_units, lm_loss_breakdown, lm_loss_calibration, lm_loss_denominator,
               lr_schedules, lr_compare, lr_curves, lr_warmup,
               reg_dropout_positions, reg_overfit, reg_data_size, reg_weight_decay, reg_dropout, reg_compare,
               grad_norm_trace, grad_clip_geometry, grad_spike, grad_compare, grad_accum_loop, grad_fp16_hist,
               loop_structure, ckpt_contents, ckpt_resume,
               eval_pretty_curves, eval_matrix, eval_causality, eval_bootstrap, eval_quality,
               hp_sensitivity, hp_search, hp_halving, hp_peek,
               sl_six_nd, sl_isoflop, sl_extrapolate, sl_kaplan, sl_inference,
               scale_instability, scale_mup, scale_memory, scale_parallel,
               moe_structure, moe_compare, moe_routing, moe_upcycle, moe_serving,
               kernels_memory, kernels_online, kernels_tiling, kernels_fusion,
               quant_levels, quant_granularity, quant_outliers,
               spec_round, spec_rejection, spec_gamma,
               batch_layouts, batch_timeline, batch_chunked, batch_tradeoff,
               kv_layouts, kv_sharing, kv_waste, kv_prefix_eviction,
               io_ablation, io_routing, io_server,
               first_run_shapes, reshape_vs_transpose, mask_patterns, attention_dataflow, gqa_heads, tinyllm_architecture,
               tokenizer_pipeline, ffn_vs_attention, norm_axes, data_eval_protocol, gpu_async_timeline, near_dup_index,
               lm_targets_mask, adam_step, wsd_branches, bf16_rounding, rng_timeline,
               eval_checklist_flow, tensor_parallel_swiglu, activation_recompute, expert_parallel, sampling_pipeline,
               roofline, chunked_prefill_timeline, gpu_memory_hierarchy, quant_grouping, quant_mapping,
               residual_scaling):
        fn()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
