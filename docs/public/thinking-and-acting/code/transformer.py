# 第 1 章：Transformer——重读《Attention Is All You Need》
#
# 配套正文：https://lewislau86.github.io/thinking-and-acting/transformer
#
# 只用 Python 标准库，`python transformer.py` 一秒内跑完，输出固定（随机种子固定）。
# 正文中的代码片段由 `# region 名字` / `# endregion 名字` 标记的区域直接引用。
# 这里不训练任何模型：两段代码只把论文里的两处“纸面推理”算成数字。

import math
import random

# region cost
# 论文第 4 节表 1：自注意力每层 O(n²·d)，循环层每层 O(n·d²)，两者之比正好是 n/d。
# 再把一整层 Transformer 的乘加数摊开（按 2 FLOPs/乘加，忽略 softmax、归一化等小项）：
#   Q、K、V、输出四个投影  4·n·d²  乘加
#   前馈层（d_ff = 4d）    8·n·d²  乘加
#   QKᵀ 和 权重×V          2·n²·d  乘加   ← 只有这一项随 n 平方增长
# n² 项占整层的比例 = 2n²d / (2n²d + 12nd²) = n / (n + 6d)。
# 上式也是逐 token 解码时每个新 token 的比例（2nd 对 12d²）。
# 训练或预填充时用因果掩码，理想的内核可以跳过一半分数，比例约为 n / (n + 12d)。


def attention_share(n, d, causal=False):
    """一层里花在 n² 项（打分和加权求和）上的计算比例。"""
    return n / (n + (12 if causal else 6) * d)


cases = [
    ("2017 base，约 30 个 token 的句子", 30, 512),
    ("2017 big，约 30 个 token 的句子", 30, 1024),
    ("2017 base，n 正好等于 d", 512, 512),
    ("d=8192 的大模型，8K 上下文", 8_192, 8_192),
    ("同一模型，128K 上下文", 131_072, 8_192),
    ("同一模型，1M 上下文", 1_048_576, 8_192),
]
for name, n, d in cases:
    print(f"n={n:>9,}  d={d:>5,}  n/d={n / d:>6.2f}  n² 项占比 {attention_share(n, d):>5.1%}"
          f"（因果 {attention_share(n, d, causal=True):>5.1%}）  {name}")
# endregion cost

# region scale
# 论文脚注 4：若 q、k 各分量独立、均值 0、方差 1，则 q·k 的方差是 d_k。
# 下面在这个假设下取 1 个查询、16 个键，看点积的标准差和 softmax 最大权重。
rng = random.Random(0)
TRIALS, KEYS = 400, 16


def softmax(xs):
    m = max(xs)
    es = [math.exp(x - m) for x in xs]
    s = sum(es)
    return [e / s for e in es]


for d_k in (4, 16, 64, 256, 1024):
    dots, top_raw, top_scaled = [], 0.0, 0.0
    for _ in range(TRIALS):
        q = [rng.gauss(0, 1) for _ in range(d_k)]
        scores = [sum(qi * rng.gauss(0, 1) for qi in q) for _ in range(KEYS)]
        dots += scores
        top_raw += max(softmax(scores)) / TRIALS
        top_scaled += max(softmax([s / math.sqrt(d_k) for s in scores])) / TRIALS
    std = math.sqrt(sum(x * x for x in dots) / len(dots))
    print(f"d_k={d_k:>4}  点积标准差 {std:>4.1f}（√d_k={math.sqrt(d_k):>4.1f}）"
          f"  最大权重：不缩放 {top_raw:.3f}，除以 √d_k 后 {top_scaled:.3f}")
# 16 个键平均分配时每个权重是 1/16 ≈ 0.063；最大权重接近 1 说明 softmax 已经接近 one-hot，
# 此时除最大项以外的梯度几乎为 0。
# endregion scale
