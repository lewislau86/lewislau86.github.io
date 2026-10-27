"""Run the small PyTorch experiments behind the TinyLLM figures and save their results.

Run from any directory: python scripts/tinyllm-figure-data.py   (needs torch, CPU is enough)
Output: scripts/data/tinyllm-*.json, read by scripts/generate-tinyllm-figures.py.
Every experiment uses a fixed seed; the numbers quoted in the chapters come from these files.
"""

from pathlib import Path
import copy
import json
import math

import torch
from torch import nn
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts/data"


def save(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", name)


# ---------- 第 3 章：初始化与残差 ----------

def init_fan_in():
    """固定 std 与 Xavier/He 在不同输入宽度下，线性层输出的标准差。"""
    torch.manual_seed(0)
    widths = [16, 32, 64, 128, 256, 512, 1024]
    out = {"widths": widths, "fixed_0.02": [], "fixed_1": [], "xavier": [], "he": []}
    for n in widths:
        x = torch.randn(4096, n)
        for key, std in [("fixed_0.02", 0.02), ("fixed_1", 1.0), ("xavier", math.sqrt(2 / (n + n))), ("he", math.sqrt(2 / n))]:
            w = torch.randn(n, n) * std
            out[key].append((x @ w).std().item())
    save("tinyllm-init-fan-in.json", out)


def residual_depth():
    """32 层：纯堆叠、无归一化残差、Pre-LN、Post-LN，记录每层输出 RMS 与输入梯度范数。"""
    d, depth = 64, 32
    variants = ["plain", "residual", "pre_ln", "post_ln"]
    result = {"depth": depth, "rms": {}, "grad": {}}
    for v in variants:
        torch.manual_seed(1)
        layers = [nn.Linear(d, d, bias=False) for _ in range(depth)]
        for layer in layers:
            nn.init.xavier_normal_(layer.weight)
        norms = [nn.LayerNorm(d, elementwise_affine=False) for _ in range(depth)]
        x = torch.randn(256, d, requires_grad=True)
        h, hidden = x, []
        for layer, norm in zip(layers, norms):
            f = lambda t: torch.tanh(layer(t))
            if v == "plain":
                h = f(h)
            elif v == "residual":
                h = h + f(h)
            elif v == "pre_ln":
                h = h + f(norm(h))
            else:
                h = norm(h + f(h))
            h.retain_grad()
            hidden.append(h)
        # 用固定的随机投影作损失：对 LayerNorm 输出取均方会恒等于约 1，梯度近乎为零，测不出差别。
        probe = torch.randn(d, generator=torch.Generator().manual_seed(2))
        (h @ probe).mean().backward()
        result["rms"][v] = [t.detach().square().mean().sqrt().item() for t in hidden]
        result["grad"][v] = [t.grad.norm().item() for t in hidden]
    save("tinyllm-residual-depth.json", result)


# ---------- 第 5 章：激活函数 ----------

def activation_fit():
    """两层网络拟合 sin：中间没有激活时只能学到直线。"""
    torch.manual_seed(0)
    x = torch.linspace(-math.pi, math.pi, 200).unsqueeze(1)
    y = torch.sin(x)
    preds = {}
    for name, act in [("linear", nn.Identity()), ("gelu", nn.GELU())]:
        torch.manual_seed(0)
        model = nn.Sequential(nn.Linear(1, 32), act, nn.Linear(32, 1))
        opt = torch.optim.Adam(model.parameters(), lr=0.01)
        for _ in range(1500):
            loss = F.mse_loss(model(x), y)
            opt.zero_grad()
            loss.backward()
            opt.step()
        preds[name] = {"pred": model(x).detach().squeeze(1).tolist(), "loss": loss.item()}
    save("tinyllm-activation-fit.json", {"x": x.squeeze(1).tolist(), "y": y.squeeze(1).tolist(), **preds})


# ---------- 第 14 章：优化器 ----------

def optimizer_curves():
    """与第 14 章“动手”一节完全相同的实验：两层网络拟合正弦，四种优化器各 300 步。"""
    torch.manual_seed(7)
    x = torch.linspace(-math.pi, math.pi, 128).unsqueeze(1)
    y = torch.sin(x)
    base = nn.Sequential(nn.Linear(1, 16), nn.Tanh(), nn.Linear(16, 1))
    initial = copy.deepcopy(base.state_dict())
    makers = {
        "SGD": lambda p: torch.optim.SGD(p, lr=0.05),
        "Momentum": lambda p: torch.optim.SGD(p, lr=0.05, momentum=0.9),
        "Adam": lambda p: torch.optim.Adam(p, lr=0.01),
        "AdamW": lambda p: torch.optim.AdamW(p, lr=0.01, weight_decay=1e-3),
    }
    results = {}
    for name, make in makers.items():
        model = copy.deepcopy(base)
        model.load_state_dict(initial)
        opt = make(model.parameters())
        history = []
        for _ in range(300):
            loss = (model(x) - y).square().mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            history.append(loss.item())
        results[name] = history
    save("tinyllm-optimizer-curves.json", results)


def optimizer_paths():
    """狭长碗形 f(a,b) = 0.5·(a² + 25·b²) 上，四种优化器从同一点出发走 40 步的轨迹。"""
    makers = {
        "SGD (lr=0.075)": lambda p: torch.optim.SGD(p, lr=0.075),
        "Momentum (lr=0.01, 0.9)": lambda p: torch.optim.SGD(p, lr=0.01, momentum=0.9),
        "RMSProp (lr=0.1)": lambda p: torch.optim.RMSprop(p, lr=0.1),
        "Adam (lr=0.2)": lambda p: torch.optim.Adam(p, lr=0.2),
    }
    paths = {}
    for name, make in makers.items():
        p = torch.tensor([-4.5, 1.6], requires_grad=True)
        opt = make([p])
        trace = [p.detach().tolist()]
        for _ in range(40):
            loss = 0.5 * (p[0] ** 2 + 25 * p[1] ** 2)
            opt.zero_grad()
            loss.backward()
            opt.step()
            trace.append(p.detach().tolist())
        paths[name] = trace
    save("tinyllm-optimizer-paths.json", {"curvature": [1, 25], "paths": paths})


# ---------- 第 17 章：数值精度 ----------

def float_spacing():
    """各格式在不同数量级上相邻可表示数的间距（ulp）。"""
    values = [2.0 ** k for k in range(-14, 17)]
    out = {"values": values}
    for name, dtype in [("FP32", torch.float32), ("FP16", torch.float16), ("BF16", torch.bfloat16)]:
        info = torch.finfo(dtype)
        spacing = []
        for v in values:
            t = torch.tensor(v, dtype=dtype)
            if not torch.isfinite(t) or v > info.max:
                spacing.append(None)
                continue
            nxt = torch.nextafter(t, torch.tensor(float("inf"), dtype=dtype))
            spacing.append((nxt.float() - t.float()).item())
        out[name] = {"spacing": spacing, "eps": info.eps, "tiny": info.tiny, "max": info.max}
    save("tinyllm-float-spacing.json", out)


if __name__ == "__main__":
    init_fan_in()
    residual_depth()
    activation_fit()
    optimizer_curves()
    optimizer_paths()
    float_spacing()
