# %% [markdown]
# # 第 24 章：推理效率（已成文部分：KV cache）
#
# 配套教案：https://lewislau86.github.io/tinyllm/inference-efficiency
#
# 从上到下运行即可（`python inference-efficiency.py`），CPU 上不到一秒。只需要安装 PyTorch。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本章还在规划中，目前只有“KV cache 保存的是什么”一节；例子沿用第 4 章的六项教学词表。

# %%
import math

import torch
from torch import nn

# %% [markdown]
# ## 1. 一次性算出三个位置的因果注意力
#
# “我 在 学习”三个 token 查表、加上教学用的绝对位置向量，再做一头、四维的因果注意力。
# 权重随机，注意力数值没有语义，只用来对照“一次性计算”和“逐步缓存”是否一致。

# %%
# region setup
torch.manual_seed(7)
embedding = nn.Embedding(6, 4)              # 第 4 章的六项教学词表
position = nn.Embedding(3, 4)               # 教学用的绝对位置向量
x = embedding(torch.tensor([2, 3, 4])) + position(torch.arange(3))  # “我 在 学习” → [3, 4]

q_proj, k_proj, v_proj = (nn.Linear(4, 4, bias=False) for _ in range(3))
q, k, v = q_proj(x), k_proj(x), v_proj(x)
scores = q @ k.T / math.sqrt(4)
future = torch.triu(torch.ones(3, 3, dtype=torch.bool), diagonal=1)   # 不许看未来
weights = scores.masked_fill(future, float("-inf")).softmax(dim=-1)
context = weights @ v                       # 一次性算出 3 个位置的输出
# endregion setup
print("context 形状:", tuple(context.shape))
print("注意力权重:\n", weights)

# %% [markdown]
# ## 2. KV cache：逐个位置生成，复用旧的 K/V
#
# 每来一个新位置，只算它自己的 Q、K、V，把 K、V 追加进缓存；新 Q 与缓存里所有 K 打分，再对所有 V 加权求和。

# %%
# region kv-cache
cached_k, cached_v, incremental = [], [], []
for t in range(len(x)):
    q_t = q_proj(x[t:t+1])                  # 只为新位置算 Q
    cached_k.append(k_proj(x[t:t+1]))       # 新位置的 K、V 追加进缓存
    cached_v.append(v_proj(x[t:t+1]))
    all_k, all_v = torch.cat(cached_k), torch.cat(cached_v)
    attention_t = (q_t @ all_k.T / math.sqrt(4)).softmax(dim=-1)   # 权重每步重算
    incremental.append(attention_t @ all_v)
assert torch.allclose(torch.cat(incremental), context, atol=1e-6)
# endregion kv-cache
print("一次性计算与逐步缓存的最大误差:", (torch.cat(incremental) - context).abs().max().item())
print("缓存了", len(cached_k), "个位置的 K 和 V；缓存的是 K/V，不是注意力分数")
