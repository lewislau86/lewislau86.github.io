# %% [markdown]
# # 第 6 章：位置表示
#
# 配套教案：https://lewislau86.github.io/tinyllm/position-encoding
#
# 从上到下运行即可（`python position-encoding.py`），CPU 上约两分钟（最后要训练三个小模型）。只需要安装 PyTorch。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

# %%
import math

import torch
from torch import nn
from torch.nn import functional as F

torch.manual_seed(0)
print("PyTorch", torch.__version__)

# %% [markdown]
# ## 1. 没有位置信息时，注意力分不出先后
#
# 用第 5 章的因果注意力处理两句话：“我 在 学习”和“在 我 学习”。
# 最后一个位置都是“学习”，它能看见的都是同样三个字，只是先后不同。

# %%
# region order-blind
torch.manual_seed(0)
d = 8
embedding = nn.Embedding(6, d)
w_q, w_k, w_v = (nn.Linear(d, d, bias=False) for _ in range(3))

def causal_attention(x):
    q, k, v = w_q(x), w_k(x), w_v(x)
    return F.scaled_dot_product_attention(q, k, v, is_causal=True)

a = causal_attention(embedding(torch.tensor([[2, 3, 4]])))   # 我 在 学习
b = causal_attention(embedding(torch.tensor([[3, 2, 4]])))   # 在 我 学习
print("最后一个位置的输出相同吗？", torch.allclose(a[0, -1], b[0, -1], atol=1e-6))
# endregion order-blind
assert torch.allclose(a[0, -1], b[0, -1], atol=1e-6)

# %% [markdown]
# ## 2. 最简单的办法：给每个位置一个可学习向量
#
# 第 1 章就是这么做的：再准备一张 [最大长度, d] 的表，按位置查一行，加到词向量上。

# %%
# region learned
position = nn.Embedding(24, d)                       # 最多支持 24 个位置
def with_position(ids):
    return embedding(ids) + position(torch.arange(ids.shape[1]))

a = causal_attention(with_position(torch.tensor([[2, 3, 4]])))
b = causal_attention(with_position(torch.tensor([[3, 2, 4]])))
print("加上位置向量后还相同吗？", torch.allclose(a[0, -1], b[0, -1], atol=1e-6))
# endregion learned
assert not torch.allclose(a[0, -1], b[0, -1], atol=1e-6)

# %%
# region learned-limit
try:
    with_position(torch.zeros(1, 30, dtype=torch.long))   # 第 25 个位置在表里没有
except IndexError as error:
    print("超过 24 个位置：IndexError:", error)
# endregion learned-limit

# %% [markdown]
# ## 3. 原始 Transformer 的正弦位置编码
#
# 不用学习，直接用不同频率的正弦、余弦算出每个位置的向量：低维变化快，高维变化慢。

# %%
# region sinusoidal
def sinusoidal(T, d, base=10000.0):
    pos = torch.arange(T).float()[:, None]                    # [T, 1]
    freq = base ** (-torch.arange(0, d, 2).float() / d)       # [d/2]，从 1 逐渐变小
    pe = torch.zeros(T, d)
    pe[:, 0::2] = torch.sin(pos * freq)
    pe[:, 1::2] = torch.cos(pos * freq)
    return pe

pe = sinusoidal(100, 16)
print(tuple(pe.shape), "位置 0 的前 4 维:", pe[0, :4].tolist())
# endregion sinusoidal

# %% [markdown]
# ## 4. RoPE：把位置变成旋转
#
# 把 q、k 的每两维看成平面上的一个点，位置 m 就把它旋转 m·θ 角。不同的两维用不同的 θ。
# 只旋转 q 和 k，不动 v。

# %%
# region rope
def rope(x, base=10000.0):
    """x: [..., T, d]，d 为偶数。第 i 对维度在位置 m 上旋转 m * θ_i。"""
    T, d = x.shape[-2], x.shape[-1]
    theta = base ** (-torch.arange(0, d, 2).float() / d)      # [d/2]：每对维度的转速
    angle = torch.arange(T).float()[:, None] * theta          # [T, d/2]：位置 m 转 m·θ
    cos, sin = angle.cos(), angle.sin()
    x1, x2 = x[..., 0::2], x[..., 1::2]                        # 每两维一对
    return torch.stack([x1 * cos - x2 * sin,                   # 平面旋转
                        x1 * sin + x2 * cos], dim=-1).flatten(-2)
# endregion rope

# %%
# region rope-relative
torch.manual_seed(3)
q_vec, k_vec = torch.randn(8), torch.randn(8)

def score(m, n, T=64):
    """把同一个 q 放在位置 m、同一个 k 放在位置 n，旋转后算点积。"""
    q = torch.zeros(T, 8); q[m] = q_vec
    k = torch.zeros(T, 8); k[n] = k_vec
    return (rope(q)[m] @ rope(k)[n]).item()

print(f"(m=3,  n=1)  的分数: {score(3, 1):.4f}")
print(f"(m=13, n=11) 的分数: {score(13, 11):.4f}")   # 相差同样 2 个位置
print(f"(m=40, n=38) 的分数: {score(40, 38):.4f}")
print(f"(m=3,  n=0)  的分数: {score(3, 0):.4f}")     # 相差 3 个位置，分数不同
# endregion rope-relative
assert abs(score(3, 1) - score(40, 38)) < 1e-4 and abs(score(3, 1) - score(3, 0)) > 1e-3

# %%
# region rope-order
def rope_attention(x):
    q, k, v = w_q(x), w_k(x), w_v(x)
    return F.scaled_dot_product_attention(rope(q), rope(k), v, is_causal=True)   # 只转 q、k

a = rope_attention(embedding(torch.tensor([[2, 3, 4]])))
b = rope_attention(embedding(torch.tensor([[3, 2, 4]])))
print("用 RoPE 之后还相同吗？", torch.allclose(a[0, -1], b[0, -1], atol=1e-6))
# endregion rope-order
assert not torch.allclose(a[0, -1], b[0, -1], atol=1e-6)

# %% [markdown]
# ## 5. 对照实验一：背唐诗
#
# 用第 1 章同一份唐诗和同一个模型，各训练 400 步，只换位置表示的方式：没有位置 / 可学习绝对位置 / RoPE。

# %%
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
itos = {i: ch for ch, i in stoi.items()}
data = torch.tensor([stoi[c] for c in text], dtype=torch.long)
vocab_size, block_size = len(chars), 24


def get_batch(T=block_size, batch_size=32):
    starts = torch.randint(len(data) - T - 1, (batch_size,))
    x = torch.stack([data[s : s + T] for s in starts])
    y = torch.stack([data[s + 1 : s + T + 1] for s in starts])
    return x, y


class SwiGLU(nn.Module):
    def __init__(self, d, hidden):
        super().__init__()
        self.gate, self.value = nn.Linear(d, hidden, bias=False), nn.Linear(d, hidden, bias=False)
        self.down = nn.Linear(hidden, d, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.value(x))


# region pos-attention
class Attention(nn.Module):
    def __init__(self, d, n_heads, use_rope):
        super().__init__()
        self.h, self.use_rope = n_heads, use_rope
        self.qkv, self.proj = nn.Linear(d, 3 * d, bias=False), nn.Linear(d, d, bias=False)

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.h, D // self.h).transpose(1, 2) for t in self.qkv(x).split(D, -1))
        if self.use_rope:                       # RoPE 在每一层、每个头里旋转 q 和 k
            q, k = rope(q), rope(k)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.proj(y.transpose(1, 2).reshape(B, T, D))
# endregion pos-attention


class Block(nn.Module):
    def __init__(self, d, n_heads, use_rope):
        super().__init__()
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.attn, self.ffn = Attention(d, n_heads, use_rope), SwiGLU(d, 8 * d // 3)

    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        return x + self.ffn(self.norm2(x))


class TinyLLM(nn.Module):
    def __init__(self, kind, d=64, n_layers=3, n_heads=4):
        super().__init__()
        self.kind = kind                        # "none" / "learned" / "rope"
        self.tok = nn.Embedding(vocab_size, d)
        self.pos = nn.Embedding(block_size, d) if kind == "learned" else None
        self.blocks = nn.ModuleList(Block(d, n_heads, kind == "rope") for _ in range(n_layers))
        self.norm = nn.RMSNorm(d)
        self.head = nn.Linear(d, vocab_size, bias=False)
        self.head.weight = self.tok.weight
        nn.init.normal_(self.tok.weight, std=d ** -0.5)
        if self.pos is not None:
            nn.init.normal_(self.pos.weight, std=d ** -0.5)

    def forward(self, idx):
        h = self.tok(idx)
        if self.pos is not None:                # 绝对位置：只在输入处加一次
            h = h + self.pos(torch.arange(idx.shape[1]))
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


@torch.no_grad()
def eval_loss(model, T, n=20):
    torch.manual_seed(123)
    losses = [F.cross_entropy(model(x).reshape(-1, vocab_size), y.reshape(-1)).item()
              for x, y in (get_batch(T) for _ in range(n))]
    return sum(losses) / n


# region poem-ablation
results, models = {}, {}
for kind, name in [("none", "没有位置"), ("learned", "可学习绝对位置"), ("rope", "RoPE")]:
    torch.manual_seed(0)
    model = TinyLLM(kind)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    history = []
    for step in range(400):
        xb, yb = get_batch()
        loss = F.cross_entropy(model(xb).reshape(-1, vocab_size), yb.reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        history.append(loss.item())
    torch.manual_seed(1)
    sample = generate(model, "床前")
    results[name] = {"loss": history, "final": sum(history[-50:]) / 50, "sample": sample}
    models[kind] = model
    print(f"{name}：最后 50 步平均训练损失 {results[name]['final']:.3f}")
# endregion poem-ablation

# %% [markdown]
# ## 6. 对照实验二：一个必须知道“隔了几个字”的任务
#
# 输入一串随机符号，每个位置的目标是“往前数第 3 个符号”。这个任务和语义无关，只考位置。

# %%
# region offset-task
V_TASK = 32
def offset_batch(T=24, batch_size=64):
    x = torch.randint(0, V_TASK, (batch_size, T))
    y = torch.roll(x, shifts=3, dims=1)             # 目标：往前数第 3 个符号
    y[:, :3] = -100                                 # 前 3 个位置没有答案，不计损失
    return x, y

@torch.no_grad()
def offset_accuracy(model, T):
    torch.manual_seed(5)
    x, y = offset_batch(T, batch_size=256)
    pred, mask = model(x).argmax(-1), y != -100
    return (pred[mask] == y[mask]).float().mean().item()

vocab_size = V_TASK                                 # 这个任务用 32 个符号的小词表
task_models = {}
for kind, name in [("none", "没有位置"), ("learned", "可学习绝对位置"), ("rope", "RoPE")]:
    torch.manual_seed(0)
    model = TinyLLM(kind, d=32, n_layers=2, n_heads=4)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    for step in range(300):
        x, y = offset_batch()
        loss = F.cross_entropy(model(x).reshape(-1, V_TASK), y.reshape(-1), ignore_index=-100)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    task_models[kind] = model
    print(f"{name}：长度 24 上的准确率 {offset_accuracy(model, 24):.3f}")
# endregion offset-task
vocab_size = len(chars)                             # 换回唐诗的词表

# %% [markdown]
# ## 7. 比训练时更长：RoPE 能直接用吗？
#
# 训练时每段只有 24 个位置。可学习绝对位置的表只有 24 行，更长的输入根本跑不了；
# RoPE 可以对任何位置算出旋转角度。分别在位置任务和唐诗上，把长度加到训练时的 2 倍、4 倍。

# %%
# region extrapolate
for T in (24, 48, 96):
    print(f"位置任务，RoPE，长度 {T}：准确率 {offset_accuracy(task_models['rope'], T):.3f}")
rope_model = models["rope"]
print(f"RoPE 模型，长度 24（训练长度）：损失 {eval_loss(rope_model, 24):.3f}")
print(f"RoPE 模型，长度 48（训练长度的两倍）：损失 {eval_loss(rope_model, 48):.3f}")
# endregion extrapolate
extrap = {"t24": eval_loss(rope_model, 24), "t48": eval_loss(rope_model, 48),
          "task": {k: offset_accuracy(m, 24) for k, m in task_models.items()},
          "task_rope_long": {T: offset_accuracy(task_models["rope"], T) for T in (24, 48, 96)}}

# %% [markdown]
# ## 8. 保存对照实验的记录（可选）

# %%
import json
with open("position_ablation.json", "w", encoding="utf-8") as f:
    json.dump({"runs": {k: {"loss": v["loss"], "sample": v["sample"]} for k, v in results.items()},
               "extrapolate": extrap}, f, ensure_ascii=False)
