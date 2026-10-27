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
        for c in (BLUE, TEAL, ORANGE, RED, GRAY, INK)))
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


# ---------- 第 4 章：归一化 ----------

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
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
