# %% [markdown]
# # 第 1 章：先跑通一个最小 TinyLLM
#
# 配套教案：https://lewislau86.github.io/tinyllm/first-run
#
# 从上到下运行即可，CPU 上约半分钟。只需要安装 PyTorch。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 这一章先把整条流水线跑通：文本 → 编号 → 模型 → 损失 → 更新 → 生成。
# 每个零件的原理留给后面的章节，代码注释里标出了对应章节号。

# %%
# region imports
import math
import time

import torch
from torch import nn
from torch.nn import functional as F
# endregion imports

torch.manual_seed(0)
print("PyTorch", torch.__version__)

# %% [markdown]
# ## 1. 准备语料
#
# 用几十首五言唐诗当训练数据。语料很小，模型会大量“背诵”，
# 但足以看清训练前后的差别。

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
# region split
lines = POEMS.splitlines()
train_text = "\n".join(lines[:-4]) + "\n"   # 前 35 首用来训练
val_text = "\n".join(lines[-4:]) + "\n"     # 最后 4 首不参与训练，只用来检查
# endregion split
text = train_text + val_text
print("诗的数量：", len(lines), "  训练字符数：", len(train_text), "  验证字符数：", len(val_text))

# %% [markdown]
# ## 2. 把文字变成编号（第 3 章会换成 BPE 分词器）
#
# 最简单的分词器：每个不同的字符分配一个编号。换行符也是一个“字”，
# 模型靠它学会一首诗在哪里结束。

# %%
# region tokenizer
chars = sorted(set(text))                    # 语料里所有不同的字
stoi = {ch: i for i, ch in enumerate(chars)} # 字 → 编号
itos = {i: ch for ch, i in stoi.items()}     # 编号 → 字
encode = lambda s: [stoi[c] for c in s]
decode = lambda ids: "".join(itos[i] for i in ids)
# endregion tokenizer

train_data = torch.tensor(encode(train_text), dtype=torch.long)
val_data = torch.tensor(encode(val_text), dtype=torch.long)
vocab_size = len(chars)
print("词表大小：", vocab_size)
print("“床前明月光” →", encode("床前明月光"))
assert decode(encode("床前明月光")) == "床前明月光"

# %% [markdown]
# ## 3. 训练样本：用前面的字预测下一个字（第 13 章展开）
#
# 从语料中随机截取长度为 `block_size` 的片段 x，把它整体后移一位得到 y。
# 位置 t 的目标就是 x 中第 t+1 个字。

# %%
block_size = 24   # 模型一次最多看多少个字
batch_size = 32

# region batch
def get_batch(data):
    starts = torch.randint(len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[s : s + block_size] for s in starts])
    y = torch.stack([data[s + 1 : s + block_size + 1] for s in starts])
    return x, y
# endregion batch

x, y = get_batch(train_data)
print("x 形状", tuple(x.shape), "y 形状", tuple(y.shape))
print("x[0] =", decode(x[0].tolist()).replace("\n", "⏎"))
print("y[0] =", decode(y[0].tolist()).replace("\n", "⏎"))

# %% [markdown]
# ## 4. 模型：一个很小的 Decoder-only Transformer
#
# 每个零件后面都有专门的章节；这里先当作黑盒，只要能对上总图即可。

# %%
# region model
class CausalSelfAttention(nn.Module):          # 自注意力：第 5 章
    def __init__(self, d, n_heads):
        super().__init__()
        self.n_heads = n_heads
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.proj = nn.Linear(d, d, bias=False)

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = self.qkv(x).split(D, dim=-1)
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2) for t in (q, k, v))
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)  # 只能看自己和前面的字
        return self.proj(y.transpose(1, 2).reshape(B, T, D))


class SwiGLU(nn.Module):                        # 门控前馈层：第 7 章
    def __init__(self, d, hidden):
        super().__init__()
        self.gate = nn.Linear(d, hidden, bias=False)
        self.value = nn.Linear(d, hidden, bias=False)
        self.down = nn.Linear(hidden, d, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.value(x))


class Block(nn.Module):                         # Transformer Block：第 8 章
    def __init__(self, d, n_heads):
        super().__init__()
        self.norm1 = nn.RMSNorm(d)              # 归一化：第 10 章
        self.attn = CausalSelfAttention(d, n_heads)
        self.norm2 = nn.RMSNorm(d)
        self.ffn = SwiGLU(d, 8 * d // 3)

    def forward(self, x):
        x = x + self.attn(self.norm1(x))        # 残差：第 9 章
        x = x + self.ffn(self.norm2(x))
        return x


class TinyLLM(nn.Module):                       # 完整模型：第 11 章
    def __init__(self, vocab_size, d=96, n_layers=3, n_heads=4, block_size=block_size):
        super().__init__()
        self.tok = nn.Embedding(vocab_size, d)  # 词嵌入：第 4 章
        self.pos = nn.Embedding(block_size, d)  # 位置：第 6 章会换成 RoPE
        self.blocks = nn.ModuleList(Block(d, n_heads) for _ in range(n_layers))
        self.norm = nn.RMSNorm(d)               # 最终归一化
        self.head = nn.Linear(d, vocab_size, bias=False)
        self.head.weight = self.tok.weight      # 输入输出共享一张表：第 4 章
        nn.init.normal_(self.tok.weight, std=d ** -0.5)   # 初始化：第 9 章
        nn.init.normal_(self.pos.weight, std=d ** -0.5)

    def forward(self, idx):
        T = idx.shape[1]
        h = self.tok(idx) + self.pos(torch.arange(T, device=idx.device))
        for block in self.blocks:
            h = block(h)
        return self.head(self.norm(h))          # [B, T, vocab_size] 的 logits
# endregion model


model = TinyLLM(vocab_size)
print("参数量：", sum(p.numel() for p in model.parameters()))

# %% [markdown]
# ## 5. 训练之前：先让它“写”一首
#
# 采样函数每次把当前文字送进模型，取最后一个位置的 logits，
# 按概率抽一个字接在后面（第 21 章细讲温度与采样）。

# %%
# region generate
@torch.no_grad()
def generate(prompt, max_new_tokens=48, temperature=0.8):
    model.eval()
    idx = torch.tensor([encode(prompt)])
    for _ in range(max_new_tokens):
        logits = model(idx[:, -block_size:])[:, -1, :] / temperature
        next_id = torch.multinomial(F.softmax(logits, dim=-1), num_samples=1)
        idx = torch.cat([idx, next_id], dim=1)
        if itos[next_id.item()] == "\n":
            break
    model.train()
    return decode(idx[0].tolist()).strip()
# endregion generate

torch.manual_seed(1)
print("训练前：", generate("春"))

# %% [markdown]
# ## 6. 训练循环（第 2、14、19 章）
#
# 每一步都是同一个骨架：前向得到 logits → 交叉熵损失 → backward 求梯度 → 优化器更新。
# 每隔 10 步再在没训练过的 4 首诗上算一次损失（验证损失），只看不更新。

# %%
# region loss
def lm_loss(x, y):
    logits = model(x)
    return F.cross_entropy(logits.reshape(-1, vocab_size), y.reshape(-1))
# endregion loss

@torch.no_grad()
def val_loss():
    model.eval()
    losses = [lm_loss(*get_batch(val_data)).item() for _ in range(8)]
    model.train()
    return sum(losses) / len(losses)

print("均匀乱猜时的损失约为 ln(词表大小) =", round(math.log(vocab_size), 3))
# region train
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
steps = 600
log = {"loss": [], "val_step": [], "val_loss": [], "uniform": math.log(vocab_size)}
start = time.time()
for step in range(steps + 1):
    x, y = get_batch(train_data)
    loss = lm_loss(x, y)                    # 前向 + 损失
    optimizer.zero_grad(set_to_none=True)
    loss.backward()                         # 求梯度
    optimizer.step()                        # 更新参数
    log["loss"].append(loss.item())
    if step % 10 == 0:
        log["val_step"].append(step)
        log["val_loss"].append(val_loss())
    if step % 100 == 0:
        print(f"step {step:4d}  训练损失 {loss.item():.3f}  验证损失 {log['val_loss'][-1]:.3f}  ({time.time() - start:.0f}s)")
# endregion train

# %% [markdown]
# ## 7. 训练之后：再写几首
#
# 语料只有几十首诗，模型会大段背诵原句，也会把不同诗句拼在一起。
# 训练损失一路下降，验证损失只在最开始短暂下降，随后一路上升：这就是过拟合，第 12、16、20 章会处理。

# %%
torch.manual_seed(1)
for prompt in ["春", "月", "山中", "孤舟"]:
    print(generate(prompt))

# %% [markdown]
# ## 8. 保存损失记录（可选）
#
# 网站上的损失曲线图就是用这份记录画的。

# %%
import json
with open("first_run_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f)
