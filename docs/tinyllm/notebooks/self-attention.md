---
title: "第 6 章：自注意力（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/self-attention) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/self-attention.ipynb) · <a href="/tinyllm/notebooks/self-attention.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/self-attention.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/self-attention.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 6 章：自注意力

配套教案：https://lewislau86.github.io/tinyllm/self-attention

从上到下运行即可（`python self-attention.py`），CPU 上约一分钟（最后的对照实验要训练两个小模型）。只需要安装 PyTorch。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
:::

<p class="nb-label">In [1]</p>

```python
import math
import time

import torch
from torch import nn
from torch.nn import functional as F

torch.manual_seed(0)
print("PyTorch", torch.__version__)
```

```text
PyTorch 2.14.1+cpu
```

::: v-pre
## 1. 查完表，每个字还是孤立的

第 5 章的嵌入层只按 ID 取一行：同一个字出现在哪句话里，查到的向量都一样。
:::

<p class="nb-label">In [2]</p>

```python
embedding = nn.Embedding(6, 4)                      # 第 5 章的六项教学词表
a = embedding(torch.tensor([2, 3, 4]))              # “我 在 学习”
b = embedding(torch.tensor([5, 3, 4]))              # “数学 在 学习”
print(torch.equal(a[2], b[2]))                      # True：两句话里的“学习”一模一样
assert torch.equal(a[2], b[2])
```

```text
True
```

::: v-pre
## 2. 手算一次注意力

三个位置，每个向量只有 2 维。数字故意取得很简单，可以拿纸笔核对。
:::

<p class="nb-label">In [3]</p>

```python
Q = torch.tensor([[1.0, 0.0],      # 位置 0（我）想找什么
                  [0.0, 1.0],      # 位置 1（在）
                  [1.0, 1.0]])     # 位置 2（学习）
K = torch.tensor([[1.0, 0.0],      # 位置 0 供别人匹配的特征
                  [0.0, 1.0],
                  [1.0, 1.0]])
V = torch.tensor([[1.0, 0.0],      # 位置 0 被选中后交出的内容
                  [0.0, 2.0],
                  [3.0, 3.0]])

scores = Q @ K.T / math.sqrt(2)                     # 每个位置和每个位置打分，再除以 √d
weights = scores.softmax(dim=-1)                    # 每一行变成和为 1 的权重
out = weights @ V                                   # 按权重把 V 加起来
print("scores:\n", scores.round(decimals=3))
print("weights:\n", weights.round(decimals=3))
print("out:\n", out.round(decimals=3))
assert torch.allclose(weights.sum(dim=-1), torch.ones(3))
```

```text
scores:
 tensor([[0.7070, 0.0000, 0.7070],
        [0.0000, 0.7070, 0.7070],
        [0.7070, 0.7070, 1.4140]])
weights:
 tensor([[0.4010, 0.1980, 0.4010],
        [0.1980, 0.4010, 0.4010],
        [0.2480, 0.2480, 0.5030]])
out:
 tensor([[1.6040, 1.5990],
        [1.4010, 2.0060],
        [1.7590, 2.0070]])
```

::: v-pre
## 3. 因果掩码：只许看自己和前面

生成时位置 t 还看不到 t+1 以后的字，训练时也必须遮住，否则模型会“偷看答案”。
把未来位置的分数改成 -inf，softmax 之后它们的权重正好是 0。
:::

<p class="nb-label">In [4]</p>

```python
future = torch.triu(torch.ones(3, 3, dtype=torch.bool), diagonal=1)   # 对角线以上 = 未来
masked = scores.masked_fill(future, float("-inf"))
causal_weights = masked.softmax(dim=-1)
causal_out = causal_weights @ V
print("causal weights:\n", causal_weights.round(decimals=3))
print("causal out:\n", causal_out.round(decimals=3))
attention_steps = {                                  # 网站上的逐行单步动画用这份记录
    "names": ["我", "在", "学习"], "Q": Q.tolist(), "K": K.tolist(), "V": V.tolist(),
    "scores": scores.tolist(), "future": future.tolist(),
    "weights": causal_weights.tolist(), "out": causal_out.tolist()}
assert torch.allclose(causal_weights[0], torch.tensor([1.0, 0.0, 0.0]))
```

```text
causal weights:
 tensor([[1.0000, 0.0000, 0.0000],
        [0.3300, 0.6700, 0.0000],
        [0.2480, 0.2480, 0.5030]])
causal out:
 tensor([[1.0000, 0.0000],
        [0.3300, 1.3400],
        [1.7590, 2.0070]])
```

::: v-pre
## 4. 带投影的单头注意力，并和 PyTorch 对照

真实模型里 Q、K、V 都由同一份输入 x 经过三个不同的线性层得到。
:::

<p class="nb-label">In [5]</p>

```python
torch.manual_seed(1)
T, d = 5, 8
x = torch.randn(1, T, d)                            # [batch, T, d]
w_q, w_k, w_v = (nn.Linear(d, d, bias=False) for _ in range(3))
q, k, v = w_q(x), w_k(x), w_v(x)

def causal_attention(q, k, v):
    scores = q @ k.transpose(-2, -1) / math.sqrt(q.shape[-1])
    T = q.shape[-2]
    future = torch.triu(torch.ones(T, T, dtype=torch.bool), diagonal=1)
    return scores.masked_fill(future, float("-inf")).softmax(dim=-1) @ v

mine = causal_attention(q, k, v)
official = F.scaled_dot_product_attention(q, k, v, is_causal=True)
print("最大差:", (mine - official).abs().max().item())
assert torch.allclose(mine, official, atol=1e-6)
```

```text
最大差: 1.4901161193847656e-07
```

::: v-pre
## 5. 多头：把 d 维拆成几份，各自做一次注意力

形状变化：[B, T, D] → view [B, T, H, D/H] → transpose [B, H, T, D/H] → 注意力 → 拼回 [B, T, D]。
:::

<p class="nb-label">In [6]</p>

```python
class MultiHeadAttention(nn.Module):
    def __init__(self, d, n_heads):
        super().__init__()
        assert d % n_heads == 0
        self.h = n_heads
        self.qkv = nn.Linear(d, 3 * d, bias=False)  # 一次算出 Q、K、V
        self.proj = nn.Linear(d, d, bias=False)     # 各头结果拼回后再混合一次

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = self.qkv(x).split(D, dim=-1)      # 各 [B, T, D]
        split = lambda t: t.view(B, T, self.h, D // self.h).transpose(1, 2)
        q, k, v = split(q), split(k), split(v)      # 各 [B, H, T, D/H]
        y = causal_attention(q, k, v)               # [B, H, T, D/H]
        y = y.transpose(1, 2).reshape(B, T, D)      # 拼回 [B, T, D]
        return self.proj(y)

mha = MultiHeadAttention(d=8, n_heads=2)
print(tuple(mha(x).shape))                          # (1, 5, 8)
assert mha(x).shape == x.shape
```

```text
(1, 5, 8)
```

<p class="nb-label">In [7]</p>

```python
# 与 PyTorch 的 SDPA 版本逐数对照：同样的权重，只把 causal_attention 换成官方函数
q_, k_, v_ = (t.view(1, T, 2, 4).transpose(1, 2) for t in mha.qkv(x).split(8, dim=-1))
ref = mha.proj(F.scaled_dot_product_attention(q_, k_, v_, is_causal=True).transpose(1, 2).reshape(1, T, 8))
print("多头版本与 SDPA 最大差:", (mha(x) - ref).abs().max().item())
assert torch.allclose(mha(x), ref, atol=1e-6)
```

```text
多头版本与 SDPA 最大差: 5.960464477539063e-08
```

::: v-pre
## 6. 代价：分数矩阵随长度平方增长

每个头都有一张 T × T 的分数表。只算这张表本身（FP32）要多少内存：
:::

<p class="nb-label">In [8]</p>

```python
for T_len in [1_000, 4_000, 32_000, 128_000]:
    n = 32 * T_len * T_len                          # 32 个头，每个头一张 T×T 的表
    print(f"T = {T_len:>7,}  分数矩阵 {n * 4 / 1e9:10.2f} GB")
```

```text
T =   1,000  分数矩阵       0.13 GB
T =   4,000  分数矩阵       2.05 GB
T =  32,000  分数矩阵     131.07 GB
T = 128,000  分数矩阵    2097.15 GB
```

::: v-pre
## 7. 对照实验：去掉注意力，模型还能写诗吗？

用第 1 章的同一份语料、同一个模型、同样的 600 步训练，只改一处：注意力层的输出换成全 0。
这样每个位置只能看到自己这个字（和位置），没法看前面的字。
:::

<p class="nb-label">In [9]</p>

```python
POEMS = """
床前明月光，疑是地上霜。举头望明月，低头思故乡。
春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。
白日依山尽，黄河入海流。欲穷千里目，更上一层楼。
红豆生南国，春来发几枝。愿君多采撷，此物最相思。
空山不见人，但闻人语响。返景入深林，复照青苔上。
千山鸟飞绝，万径人踪灭。孤舟蓑笠翁，独钓寒江雪。
锄禾日当午，汗滴禾下土。谁知盘中餐，粒粒皆辛苦。
春种一粒粟，秋收万颗子。四海无闲田，农夫犹饿死。
松下问童子，言师采药去。只在此山中，云深不知处。
向晚意不适，驱车登古原。夕阳无限好，只是近黄昏。
移舟泊烟渚，日暮客愁新。野旷天低树，江清月近人。
独坐幽篁里，弹琴复长啸。深林人不知，明月来相照。
君自故乡来，应知故乡事。来日绮窗前，寒梅著花未。
山中相送罢，日暮掩柴扉。春草明年绿，王孙归不归。
众鸟高飞尽，孤云独去闲。相看两不厌，只有敬亭山。
功盖三分国，名成八阵图。江流石不转，遗恨失吞吴。
绿蚁新醅酒，红泥小火炉。晚来天欲雪，能饮一杯无。
日暮苍山远，天寒白屋贫。柴门闻犬吠，风雪夜归人。
人闲桂花落，夜静春山空。月出惊山鸟，时鸣春涧中。
危楼高百尺，手可摘星辰。不敢高声语，恐惊天上人。
离离原上草，一岁一枯荣。野火烧不尽，春风吹又生。远芳侵古道，晴翠接荒城。又送王孙去，萋萋满别情。
国破山河在，城春草木深。感时花溅泪，恨别鸟惊心。烽火连三月，家书抵万金。白头搔更短，浑欲不胜簪。
空山新雨后，天气晚来秋。明月松间照，清泉石上流。竹喧归浣女，莲动下渔舟。随意春芳歇，王孙自可留。
好雨知时节，当春乃发生。随风潜入夜，润物细无声。野径云俱黑，江船火独明。晓看红湿处，花重锦官城。
青山横北郭，白水绕东城。此地一为别，孤蓬万里征。浮云游子意，落日故人情。挥手自兹去，萧萧班马鸣。
海上生明月，天涯共此时。情人怨遥夜，竟夕起相思。灭烛怜光满，披衣觉露滋。不堪盈手赠，还寝梦佳期。
城阙辅三秦，风烟望五津。与君离别意，同是宦游人。海内存知己，天涯若比邻。无为在歧路，儿女共沾巾。
客路青山外，行舟绿水前。潮平两岸阔，风正一帆悬。海日生残夜，江春入旧年。乡书何处达，归雁洛阳边。
故人具鸡黍，邀我至田家。绿树村边合，青山郭外斜。开轩面场圃，把酒话桑麻。待到重阳日，还来就菊花。
单车欲问边，属国过居延。征蓬出汉塞，归雁入胡天。大漠孤烟直，长河落日圆。萧关逢候骑，都护在燕然。
渡远荆门外，来从楚国游。山随平野尽，江入大荒流。月下飞天镜，云生结海楼。仍怜故乡水，万里送行舟。
戍鼓断人行，边秋一雁声。露从今夜白，月是故乡明。有弟皆分散，无家问死生。寄书长不达，况乃未休兵。
细草微风岸，危樯独夜舟。星垂平野阔，月涌大江流。名岂文章著，官应老病休。飘飘何所似，天地一沙鸥。
昔闻洞庭水，今上岳阳楼。吴楚东南坼，乾坤日夜浮。亲朋无一字，老病有孤舟。戎马关山北，凭轩涕泗流。
清晨入古寺，初日照高林。曲径通幽处，禅房花木深。山光悦鸟性，潭影空人心。万籁此都寂，但余钟磬音。
岱宗夫如何，齐鲁青未了。造化钟神秀，阴阳割昏晓。荡胸生曾云，决眦入归鸟。会当凌绝顶，一览众山小。
楚塞三湘接，荆门九派通。江流天地外，山色有无中。郡邑浮前浦，波澜动远空。襄阳好风日，留醉与山翁。
北阙休上书，南山归敝庐。不才明主弃，多病故人疏。白发催年老，青阳逼岁除。永怀愁不寐，松月夜窗虚。
八月湖水平，涵虚混太清。气蒸云梦泽，波撼岳阳城。欲济无舟楫，端居耻圣明。坐观垂钓者，徒有羡鱼情。
""".strip()
lines = POEMS.splitlines()
text = "\n".join(lines) + "\n"
chars = sorted(set(text))
stoi = {ch: i for i, ch in enumerate(chars)}
itos = {i: ch for ch, i in stoi.items()}
data = torch.tensor([stoi[c] for c in text], dtype=torch.long)
vocab_size, block_size = len(chars), 24


def get_batch(batch_size=32):
    starts = torch.randint(len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[s : s + block_size] for s in starts])
    y = torch.stack([data[s + 1 : s + block_size + 1] for s in starts])
    return x, y


class SwiGLU(nn.Module):
    def __init__(self, d, hidden):
        super().__init__()
        self.gate, self.value = nn.Linear(d, hidden, bias=False), nn.Linear(d, hidden, bias=False)
        self.down = nn.Linear(hidden, d, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.value(x))


class Block(nn.Module):
    def __init__(self, d, n_heads, use_attention=True):
        super().__init__()
        self.use_attention = use_attention
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.attn = MultiHeadAttention(d, n_heads)
        self.ffn = SwiGLU(d, 8 * d // 3)

    def forward(self, x):
        if self.use_attention:                      # 对照组：不经过注意力，各位置互不相通
            x = x + self.attn(self.norm1(x))
        return x + self.ffn(self.norm2(x))


class TinyLLM(nn.Module):
    def __init__(self, use_attention, d=96, n_layers=3, n_heads=4):
        super().__init__()
        self.tok, self.pos = nn.Embedding(vocab_size, d), nn.Embedding(block_size, d)
        self.blocks = nn.ModuleList(Block(d, n_heads, use_attention) for _ in range(n_layers))
        self.norm = nn.RMSNorm(d)
        self.head = nn.Linear(d, vocab_size, bias=False)
        self.head.weight = self.tok.weight
        nn.init.normal_(self.tok.weight, std=d ** -0.5)
        nn.init.normal_(self.pos.weight, std=d ** -0.5)

    def forward(self, idx):
        h = self.tok(idx) + self.pos(torch.arange(idx.shape[1]))
        for block in self.blocks:
            h = block(h)
        return self.head(self.norm(h))


@torch.no_grad()
def generate(model, prompt, max_new_tokens=48, temperature=0.8):
    idx = torch.tensor([[stoi[c] for c in prompt]])
    for _ in range(max_new_tokens):
        logits = model(idx[:, -block_size:])[:, -1, :] / temperature
        nxt = torch.multinomial(F.softmax(logits, dim=-1), 1)
        idx = torch.cat([idx, nxt], dim=1)
        if itos[nxt.item()] == "\n":
            break
    return "".join(itos[i] for i in idx[0].tolist()).strip()


results = {}
for name, use_attention in [("有注意力", True), ("没有注意力", False)]:
    torch.manual_seed(0)
    model = TinyLLM(use_attention)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    history = []
    for step in range(600):
        xb, yb = get_batch()
        loss = F.cross_entropy(model(xb).reshape(-1, vocab_size), yb.reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        history.append(loss.item())
    torch.manual_seed(1)
    sample = generate(model, "床前")
    results[name] = (sum(history[-50:]) / 50, sample, history)
    print(f"{name}：最后 50 步平均训练损失 {results[name][0]:.3f}，以“床前”开头生成：{sample}")
```

```text
有注意力：最后 50 步平均训练损失 0.115，以“床前”开头生成：床前明月光，疑是地上霜。举头望明月，低头思故乡。
```

```text
没有注意力：最后 50 步平均训练损失 1.589，以“床前”开头生成：床前，清晨入旧年绿树村边。征。随风潜入大荒城。
```

::: v-pre
## 8. 延伸：QK Norm

在点积之前分别把 Q、K 归一化，控制注意力分数的尺度。下面是原始论文的逐头 L2 版本。
:::

<p class="nb-label">In [10]</p>

```python
torch.manual_seed(2)
q = torch.randn(1, 2, 5, 4) * 10                    # 故意放大：[batch, heads, seq, head_dim]
k = torch.randn(1, 2, 5, 4) * 10
v = torch.randn(1, 2, 5, 4)
g = nn.Parameter(torch.tensor(4.0))                 # 可学习尺度，取代固定的 1/√d

q_unit = F.normalize(q, p=2, dim=-1, eps=1e-6)      # 一定写 dim=-1：每个头的 head_dim
k_unit = F.normalize(k, p=2, dim=-1, eps=1e-6)
out = F.scaled_dot_product_attention(
    q_unit * g,     # scale 参数不接受 Parameter，所以把 g 先乘到 q 上
    k_unit, v,
    is_causal=True,
    scale=1.0,      # 关掉默认的 1/sqrt(head_dim)，避免重复缩放
)
raw_max = (q @ k.transpose(-2, -1) / 2).abs().max().item()
normed_max = ((q_unit * g) @ k_unit.transpose(-2, -1)).abs().max().item()
print(f"分数绝对值最大：原始 {raw_max:.1f}，QK Norm 后 {normed_max:.1f}（不超过 g = 4）")
assert normed_max <= 4.0 + 1e-5
```

```text
分数绝对值最大：原始 228.0，QK Norm 后 3.4（不超过 g = 4）
```

::: v-pre
## 9. 保存对照实验的损失记录（可选）

网站上的对照曲线图就是用这份记录画的。
:::

<p class="nb-label">In [11]</p>

```python
import json
with open("attention_ablation.json", "w", encoding="utf-8") as f:
    json.dump({name: {"loss": r[2], "sample": r[1]} for name, r in results.items()}, f, ensure_ascii=False)
with open("attention_steps.json", "w", encoding="utf-8") as f:
    json.dump(attention_steps, f, ensure_ascii=False)
```

