---
title: "第 8 章：Transformer Block（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/transformer-block) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/transformer-block.ipynb) · <a href="/tinyllm/notebooks/transformer-block.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/transformer-block.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/transformer-block.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 8 章：Transformer Block

配套教案：https://lewislau86.github.io/tinyllm/transformer-block

从上到下运行即可（`python transformer-block.py`），CPU 上约两分钟（要训练 25 个小模型）。只需要安装 PyTorch。
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
## 1. 三个零件：注意力（带 RoPE）、SwiGLU 前馈层

第 5、6、7 章分别写过，这里原样搬过来。注意力让 token 之间交换信息，前馈层让每个 token 自己加工。
:::

<p class="nb-label">In [2]</p>

```python
def rope(x, base=10000.0):                     # 第 6 章：按位置旋转 q、k
    T, d = x.shape[-2], x.shape[-1]
    theta = base ** (-torch.arange(0, d, 2).float() / d)
    angle = torch.arange(T).float()[:, None] * theta
    cos, sin = angle.cos(), angle.sin()
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)


class Attention(nn.Module):                    # 第 5 章：多头因果注意力
    def __init__(self, d, n_heads):
        super().__init__()
        self.h = n_heads
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.proj = nn.Linear(d, d, bias=False)

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.h, D // self.h).transpose(1, 2) for t in self.qkv(x).split(D, -1))
        y = F.scaled_dot_product_attention(rope(q), rope(k), v, is_causal=True)
        return self.proj(y.transpose(1, 2).reshape(B, T, D))


class SwiGLU(nn.Module):                       # 第 7 章：门控前馈层
    def __init__(self, d):
        super().__init__()
        hidden = 8 * d // 3
        self.gate = nn.Linear(d, hidden, bias=False)
        self.value = nn.Linear(d, hidden, bias=False)
        self.down = nn.Linear(hidden, d, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.value(x))
```

::: v-pre
## 2. 最直接的装法：先注意力，再前馈层
:::

<p class="nb-label">In [3]</p>

```python
class NaiveBlock(nn.Module):
    def __init__(self, d, n_heads):
        super().__init__()
        self.attn = Attention(d, n_heads)
        self.ffn = SwiGLU(d)

    def forward(self, x):
        x = self.attn(x)        # token 之间交换信息
        return self.ffn(x)      # 每个 token 各自加工
```

<p class="nb-label">In [4]</p>

```python
x = torch.randn(2, 24, 64)                     # [batch, 序列长度, 每个 token 的维度]
block = NaiveBlock(64, n_heads=4)
print("进入 Block:", tuple(x.shape), " 出来:", tuple(block(x).shape))

stack = nn.Sequential(*[NaiveBlock(64, 4) for _ in range(3)])
print("叠 3 个 Block 之后:", tuple(stack(x).shape))
```

```text
进入 Block: (2, 24, 64)  出来: (2, 24, 64)
叠 3 个 Block 之后: (2, 24, 64)
```

::: v-pre
## 3. 正式的 Block：加上残差和 Pre-Norm

每个子层前先做一次 RMSNorm，子层的结果加回原来的 x（残差）。它们为什么必不可少，第 9、10 章细讲。
:::

<p class="nb-label">In [5]</p>

```python
class Block(nn.Module):
    def __init__(self, d, n_heads):
        super().__init__()
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.attn = Attention(d, n_heads)
        self.ffn = SwiGLU(d)

    def forward(self, x):
        x = x + self.attn(self.norm1(x))    # 读一份归一化后的副本，算完加回去
        x = x + self.ffn(self.norm2(x))
        return x
```

<p class="nb-label">In [6]</p>

```python
d = 64
blk = Block(d, 4)
for name, part in [("注意力", blk.attn), ("SwiGLU", blk.ffn), ("两个 RMSNorm", nn.ModuleList([blk.norm1, blk.norm2]))]:
    print(f"{name:<10} {sum(p.numel() for p in part.parameters()):>6,}")
total = sum(p.numel() for p in blk.parameters())
print(f"一个 Block 合计 {total:,}，约等于 12·d² = {12 * d * d:,}")
```

```text
注意力        16,384
SwiGLU     32,640
两个 RMSNorm    128
一个 Block 合计 49,152，约等于 12·d² = 49,152
```

::: v-pre
## 4. 叠起来训练：两种 Block，1 到 8 层

用第 1 章的唐诗，前 35 首训练、最后 4 首验证。模型只差在 Block 的写法和层数：输入嵌入 → N 个 Block → 最后的 RMSNorm → 输出层。
所有模型按同一组预先抽好的 batch 训练 150 步；每种设置用 3 个随机种子（只影响初始参数），报告平均值和范围。
线性层都用 PyTorch 的默认初始化，还没有用第 9 章的初始化配方。
:::

<p class="nb-label">In [7]</p>

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
text = "\n".join(POEMS.splitlines()) + "\n"
chars = sorted(set(text))
stoi = {ch: i for i, ch in enumerate(chars)}
vocab_size, block_size = len(chars), 24

lines = POEMS.splitlines()
encode = lambda t: torch.tensor([stoi[c] for c in t], dtype=torch.long)
train_data = encode("\n".join(lines[:-4]) + "\n")       # 前 35 首训练
val_data = encode("\n".join(lines[-4:]) + "\n")         # 最后 4 首只用来验证（和第 1 章一样）

steps, batch_size = 150, 32
g = torch.Generator().manual_seed(1234)                 # 单独的随机数发生器，只管抽 batch
train_starts = torch.randint(len(train_data) - block_size - 1, (steps, batch_size), generator=g)
val_starts = torch.arange(0, len(val_data) - block_size - 1, 4)

def batch_at(data, starts):
    x = torch.stack([data[s : s + block_size] for s in starts])
    y = torch.stack([data[s + 1 : s + block_size + 1] for s in starts])
    return x, y
```

<p class="nb-label">In [8]</p>

```python
class TinyLLM(nn.Module):
    def __init__(self, block_cls, n_layers, d=64, n_heads=4):
        super().__init__()
        self.tok = nn.Embedding(vocab_size, d)
        self.blocks = nn.ModuleList(block_cls(d, n_heads) for _ in range(n_layers))
        self.norm = nn.RMSNorm(d)
        self.head = nn.Linear(d, vocab_size, bias=False)
        self.head.weight = self.tok.weight             # 输入输出共享一张表（第 4 章）
        nn.init.normal_(self.tok.weight, std=d ** -0.5)

    def forward(self, idx):
        h = self.tok(idx)                              # 位置信息由每层注意力里的 RoPE 提供
        for block in self.blocks:
            h = block(h)
        return self.head(self.norm(h))
```

<p class="nb-label">In [9]</p>

```python
def train(block_cls, n_layers, seed, n_steps=steps):
    torch.manual_seed(seed)                            # 种子只决定初始参数
    model = TinyLLM(block_cls, n_layers)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    history = []
    for step in range(n_steps):
        xb, yb = batch_at(train_data, train_starts[step % steps])   # 第 step 步：所有模型用同一个 batch
        loss = F.cross_entropy(model(xb).reshape(-1, vocab_size), yb.reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        if step == 0:                                  # 第一步时，第 1 个 Block 收到的梯度
            grad0 = model.blocks[0].attn.qkv.weight.grad.norm().item()
        opt.step()
        history.append(loss.item())
    return model, history, grad0

@torch.no_grad()
def val_loss(model):
    xb, yb = batch_at(val_data, val_starts)
    return F.cross_entropy(model(xb).reshape(-1, vocab_size), yb.reshape(-1)).item()

runs = {}
for kind, block_cls in [("直接堆叠", NaiveBlock), ("Pre-Norm 残差", Block)]:
    for n_layers in (1, 2, 4, 8):
        results = [train(block_cls, n_layers, seed) for seed in (0, 1, 2)]
        tr = [sum(h[-30:]) / 30 for _, h, _ in results]
        va = [val_loss(m) for m, _, _ in results]
        gr = sorted(g0 for *_, g0 in results)
        runs[f"{kind} {n_layers}"] = {"kind": kind, "layers": n_layers, "train": tr, "val": va, "grad0": gr,
                                      "loss": [h for _, h, _ in results]}
        print(f"{kind:<10} {n_layers} 层：训练 {sum(tr) / 3:.2f}（{min(tr):.2f}～{max(tr):.2f}）"
              f"  验证 {sum(va) / 3:.2f}（{min(va):.2f}～{max(va):.2f}）  第 1 个 Block 的梯度 {gr[1]:.0e}")
print(f"完全乱猜的损失 ln({vocab_size}) = {math.log(vocab_size):.3f}")
```

```text
直接堆叠       1 层：训练 3.54（3.53～3.54）  验证 6.76（6.56～6.89）  第 1 个 Block 的梯度 9e-02
```

```text
直接堆叠       2 层：训练 5.22（5.10～5.44）  验证 6.65（6.53～6.88）  第 1 个 Block 的梯度 2e-07
```

```text
直接堆叠       4 层：训练 6.32（6.32～6.32）  验证 6.32（6.32～6.32）  第 1 个 Block 的梯度 0e+00
```

```text
直接堆叠       8 层：训练 6.32（6.32～6.32）  验证 6.32（6.32～6.32）  第 1 个 Block 的梯度 0e+00
```

```text
Pre-Norm 残差 1 层：训练 1.25（1.23～1.26）  验证 6.87（6.81～6.91）  第 1 个 Block 的梯度 6e-01
```

```text
Pre-Norm 残差 2 层：训练 0.79（0.78～0.82）  验证 6.96（6.78～7.16）  第 1 个 Block 的梯度 7e-01
```

```text
Pre-Norm 残差 4 层：训练 0.66（0.64～0.68）  验证 7.09（6.96～7.25）  第 1 个 Block 的梯度 8e-01
```

```text
Pre-Norm 残差 8 层：训练 0.57（0.56～0.58）  验证 6.90（6.79～6.98）  第 1 个 Block 的梯度 7e-01
完全乱猜的损失 ln(556) = 6.321
```

::: v-pre
直接堆叠为什么越深越糟？看一眼训练开始前，同一批输入穿过 8 个 Block 时，每个 token 向量的大小（RMS）怎样变化。
:::

<p class="nb-label">In [10]</p>

```python
xb, _ = batch_at(train_data, train_starts[0])
signal = {}
for kind, block_cls in [("直接堆叠", NaiveBlock), ("Pre-Norm 残差", Block)]:
    signal[kind] = []
    for seed in (0, 1, 2):
        torch.manual_seed(seed)
        probe = TinyLLM(block_cls, 8)
        h = probe.tok(xb)
        sizes = [h.pow(2).mean().sqrt().item()]
        with torch.no_grad():
            for block in probe.blocks:
                h = block(h)
                sizes.append(h.pow(2).mean().sqrt().item())
        signal[kind].append(sizes)
    print(f"{kind:<10}", " ".join(f"{s:.0e}" for s in signal[kind][0]), "（种子 0）")
```

```text
直接堆叠       1e-01 4e-05 8e-11 4e-22 0e+00 0e+00 0e+00 0e+00 0e+00 （种子 0）
Pre-Norm 残差 1e-01 2e-01 3e-01 4e-01 5e-01 6e-01 7e-01 8e-01 8e-01 （种子 0）
```

::: v-pre
## 5. 残差流：每一层往同一条“流”上加东西

Pre-Norm Block 从不覆盖 x，只往上加。所以可以在任何一层之后，直接用最后的 RMSNorm 和输出层“读”一下当前的 x，
看模型此刻会猜哪个字。下面用 4 层的 Pre-Norm 模型，读出每个子层之后的预测。
:::

<p class="nb-label">In [11]</p>

```python
model, _, _ = train(Block, 4, seed=0, n_steps=300)   # 多训练一会儿再读：4 层 Pre-Norm，300 步

@torch.no_grad()
def read_stream(prompt, k=5):
    """返回每一站的 top-k 预测、残差流长度、这一站加上去的更新长度，以及注意力权重。"""
    def decode(h):
        probs = F.softmax(model.head(model.norm(h))[0, -1], dim=-1)
        top = torch.topk(probs, k)
        return [[chars[i], round(p, 4)] for p, i in zip(top.values.tolist(), top.indices.tolist())]
    rms = lambda t: t[0, -1].pow(2).mean().sqrt().item()

    h = model.tok(torch.tensor([[stoi[c] for c in prompt]]))
    stops = [{"where": "嵌入", "top": decode(h), "rms": rms(h)}]
    for i, block in enumerate(model.blocks):
        a = block.norm1(h)                              # 注意力权重：重算最后一个位置的 q 与所有 k
        B, T, D = a.shape
        q, k_, _ = (t.view(B, T, block.attn.h, D // block.attn.h).transpose(1, 2) for t in block.attn.qkv(a).split(D, -1))
        weights = (rope(q)[..., -1:, :] @ rope(k_).transpose(-1, -2) / math.sqrt(D // block.attn.h)).softmax(-1)[0, :, 0]
        update = block.attn(a)
        h = h + update
        stops.append({"where": f"第 {i + 1} 层 注意力", "top": decode(h), "rms": rms(h), "update": rms(update),
                      "attn": [[round(w, 3) for w in head] for head in weights.tolist()]})
        update = block.ffn(block.norm2(h))
        h = h + update
        stops.append({"where": f"第 {i + 1} 层 前馈", "top": decode(h), "rms": rms(h), "update": rms(update)})
    return stops

for stop in read_stream("举头望明月，低头思故"):
    print(f"{stop['where']:<10}", " ".join(f"{c}{p:.0%}" for c, p in stop["top"][:3]))
assert read_stream("举头望明月，低头思故")[-1]["top"][0][0] == "乡"
```

```text
嵌入         故100% 海0% 雨0%
第 1 层 注意力  故98% 圆0% 辛0%
第 1 层 前馈   乡13% 开3% 眠3%
第 2 层 注意力  乡26% 故3% 阳2%
第 2 层 前馈   乡64% 三2% 晓1%
第 3 层 注意力  乡68% 三2% 晓1%
第 3 层 前馈   乡81% 三1% 人1%
第 4 层 注意力  乡85% 不1% 三1%
第 4 层 前馈   乡97% 人0% 归0%
```

::: v-pre
## 6. 保存记录（可选）

网站上的对照实验图和残差流动画就是用这份记录画的。
:::

<p class="nb-label">In [12]</p>

```python
import json
lens = {prompt: {"answer": answer, "stops": read_stream(prompt)}
        for prompt, answer in [("举头望明月，低头思故", "乡"), ("床前明月光，疑是地上", "霜"), ("春眠不觉晓，处处闻啼", "鸟")]}
with open("block_depth.json", "w", encoding="utf-8") as f:
    json.dump({"runs": runs, "uniform": math.log(vocab_size), "lens": lens, "signal": signal,
               "params": {"attn": sum(p.numel() for p in blk.attn.parameters()), "ffn": sum(p.numel() for p in blk.ffn.parameters()),
                          "norm": 2 * d, "d": d}}, f, ensure_ascii=False)
```

