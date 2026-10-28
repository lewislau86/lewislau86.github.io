# %% [markdown]
# # 第 3 章：架构演进：从 Transformer 到 GPT 再到今天
#
# 配套教案：https://lewislau86.github.io/tinyllm/architecture-evolution
#
# 从上到下运行即可（`python architecture-evolution.py`），CPU 上几秒钟。只需要安装 PyTorch。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本章不训练模型，只用很小的张量把三代架构最关键的区别算给你看。

# %%
import json
import math

import torch
from torch import nn
from torch.nn import functional as F

torch.manual_seed(0)
print("PyTorch", torch.__version__)

# %% [markdown]
# ## 1. 2017 年的 Transformer：三种注意力，三种“谁能看谁”
#
# 编码器里每个词能看整句原文；解码器里每个词只能看已经写出的译文；交叉注意力让译文的每个词去看原文。

# %%
# region masks
src = ["the", "book", "on", "the", "table"]          # 原文 5 个词
tgt = ["桌子", "上", "的", "书"]                       # 译文 4 个词

encoder_mask = torch.ones(len(src), len(src), dtype=torch.bool)               # 原文：谁都能看谁
decoder_mask = torch.tril(torch.ones(len(tgt), len(tgt), dtype=torch.bool))   # 译文：只能看前面
cross_mask = torch.ones(len(tgt), len(src), dtype=torch.bool)                 # 译文的每个词看整句原文

for name, m in [("编码器自注意力", encoder_mask), ("解码器自注意力", decoder_mask), ("交叉注意力", cross_mask)]:
    print(f"{name}: 形状 {tuple(m.shape)}，能看的位置 {int(m.sum())} / {m.numel()}")
print(decoder_mask.int())
# endregion masks

# %% [markdown]
# ## 2. GPT：去掉编码器，任何文本都能当训练数据
#
# 翻译模型要“原文 → 译文”成对的数据；GPT 只要一段普通文本，把它错开一位就是输入和答案。

# %%
# region data-format
pair = ("the book on the table", "桌子上的书")          # 翻译：一条数据 = 一对句子，需要人工准备
text = "床前明月光，疑是地上霜。"                        # GPT：随便一段文字
x, y = text[:-1], text[1:]                               # 输入和答案只差一位
for i in range(4):
    print(f"看到 “{x[: i + 1]}” → 预测 “{y[i]}”")
print(f"这一句 {len(text)} 个字，自动得到 {len(x)} 道“预测下一个字”的练习题")
# endregion data-format

# %% [markdown]
# ## 3. 完整注意力的代价：KV cache 随上下文线性增长
#
# 生成时，完整注意力要把前面每个 token 的 K、V 都留着（第 25 章的 KV cache）。
# 下面按一个 32 层、每层 8 个 KV 头、每头 128 维、BF16 的模型估算缓存大小。

# %%
# region kv-cost
layers, kv_heads, head_dim, bytes_per = 32, 8, 128, 2

def kv_cache_gb(T, full_layers=layers):
    return 2 * full_layers * kv_heads * head_dim * T * bytes_per / 1e9   # 2 = K 和 V

def linear_state_gb(linear_layers):
    return linear_layers * kv_heads * head_dim * head_dim * bytes_per / 1e9  # 每层一个 d×d 的状态，与 T 无关

lengths = [4_096, 32_768, 131_072, 1_048_576]
cost = {"T": lengths, "full": [], "hybrid": []}
for T in lengths:
    full = kv_cache_gb(T)
    hybrid = kv_cache_gb(T, full_layers=layers // 4) + linear_state_gb(layers - layers // 4)   # 3 层线性 + 1 层完整
    cost["full"].append(full)
    cost["hybrid"].append(hybrid)
    print(f"上下文 {T:>9,}：全部完整注意力 {full:7.2f} GB    3:1 混合 {hybrid:7.2f} GB")
# endregion kv-cost

# %% [markdown]
# ## 4. 线性注意力：把前文压成一个固定大小的状态
#
# 最朴素的线性注意力去掉 softmax，用 φ(q)·φ(k) 代替 exp(q·k)。这样可以边读边把 φ(k)ᵀv 累加进一个 d×d 的状态，
# 每读一个 token 只做一次更新，不再需要保留全部 K、V。下面验证“逐个累加”和“一次性算整张表”结果相同。
# （Kimi K3 用的 KDA 在此基础上加了按通道的遗忘门和 delta 更新规则，思路相同：状态大小固定。）

# %%
# region linear-attention
T, d = 6, 4
q, k, v = torch.randn(T, d), torch.randn(T, d), torch.randn(T, d)
phi = lambda t: F.elu(t) + 1                            # 让特征为正，充当“相似度”

# 写法一：像普通注意力一样算整张 T×T 的表（只看自己和前面）
scores = (phi(q) @ phi(k).T).tril()
out_table = (scores @ v) / scores.sum(-1, keepdim=True)

# 写法二：从左往右读，只保留一个 d×d 的状态 S 和一个长度 d 的归一化向量 z
S, z, out_stream = torch.zeros(d, d), torch.zeros(d), []
for t in range(T):
    S = S + phi(k[t])[:, None] * v[t][None, :]          # 把这个 token 的信息“写”进状态
    z = z + phi(k[t])
    out_stream.append((phi(q[t]) @ S) / (phi(q[t]) @ z))
out_stream = torch.stack(out_stream)

print("两种写法最大差异:", (out_table - out_stream).abs().max().item())
print("状态 S 的形状:", tuple(S.shape), "—— 读了", T, "个 token，读 100 万个也还是这么大")
# endregion linear-attention
assert torch.allclose(out_table, out_stream, atol=1e-5)

# %% [markdown]
# ## 5. MoE：参数很多，每个 token 只用一小部分
#
# 把一个大前馈层换成很多个小“专家”，路由器给每个 token 挑几个。先用一个玩具层数一数，再看 Kimi K3 的公开数字。

# %%
# region moe-count
d, hidden, n_experts, top_k = 64, 128, 8, 2
experts = nn.ModuleList(nn.Sequential(nn.Linear(d, hidden), nn.SiLU(), nn.Linear(hidden, d)) for _ in range(n_experts))
router = nn.Linear(d, n_experts, bias=False)

x = torch.randn(5, d)                                   # 5 个 token
weights, chosen = router(x).softmax(-1).topk(top_k, dim=-1)
print("每个 token 选中的专家:", chosen.tolist())

per_expert = sum(p.numel() for p in experts[0].parameters())
total = per_expert * n_experts + router.weight.numel()
active = per_expert * top_k + router.weight.numel()
print(f"玩具 MoE：总参数 {total:,}，每个 token 用到 {active:,}（{active / total:.0%}）")
print(f"Kimi K3：总参数 2.8 万亿，每个 token 用到 1040 亿（{104 / 2800:.1%}）")
# endregion moe-count

# %% [markdown]
# ## 6. 保存记录（可选）
#
# 网站上的“缓存大小随上下文增长”图就是用这份记录画的。

# %%
with open("architecture_cost.json", "w", encoding="utf-8") as f:
    json.dump({"config": {"layers": layers, "kv_heads": kv_heads, "head_dim": head_dim, "bytes": bytes_per}, **cost}, f)
