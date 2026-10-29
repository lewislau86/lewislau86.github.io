# %% [markdown]
# # 30 分钟快速体验：把 TinyLLM 的零件逐个打开
#
# 配套教案：https://lewislau86.github.io/tinyllm/quickstart
#
# 从上到下运行即可，CPU 上约一分钟。只需要安装 PyTorch。
# 这个文件是这页教程代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 八步，每一步只回答一个问题、只打印几个数字。看懂哪一步，就去读对应的那一章。

# %%
# region imports
import math

import torch
from torch import nn
from torch.nn import functional as F
# endregion imports

torch.manual_seed(0)
print("PyTorch", torch.__version__)

# region corpus
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

CORPUS_URL = "https://lewislau86.github.io/tinyllm/data/tang-poems.jsonl"
CORPUS_SHA256 = "764f0614663c20e95927c6ecb63e454629f6cb0efefe9ac84454e256f7173fb1"

def load_poems(n):
    """本课统一唐诗语料的前 n 首（来源和处理方式见“实验环境”页）。
    依次找：环境变量 TINYLLM_DATA、当前目录、../data/（整包下载解压后的位置）；都没有就从网站下载一份。"""
    candidates = [os.environ.get("TINYLLM_DATA", ""), "tang-poems.jsonl", "../data/tang-poems.jsonl"]
    path = next((Path(p) for p in candidates if p and Path(p).exists()), None)
    if path is None:
        path = Path("tang-poems.jsonl")
        with urlopen(CORPUS_URL, timeout=120) as r:
            path.write_bytes(r.read())
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
        raise RuntimeError(f"{path} 不是本课使用的语料版本，删掉它再运行一次即可重新下载")
    return [json.loads(line) for line in raw.decode("utf-8").splitlines()[:n]]
# endregion corpus

# %% [markdown]
# ## 步骤 1 · 文字怎样变成编号（第 4 章）
#
# 模型只认数字。最简单的分词器给每个不同的字分配一个编号，换行也是一个字。

# %%
# region step1
poems = load_poems(200)
train_text = "\n".join(p["text"] for p in poems if p["split"] == "train") + "\n"
val_text = "\n".join(p["text"] for p in poems if p["split"] == "val") + "\n"

chars = sorted(set(train_text + val_text))
stoi = {ch: i for i, ch in enumerate(chars)}
itos = {i: ch for ch, i in stoi.items()}
encode = lambda s: [stoi[c] for c in s]
decode = lambda ids: "".join(itos[i] for i in ids)
vocab_size = len(chars)
# endregion step1

print("训练用诗：", train_text.count("\n") - 1, "首  验证用诗：", val_text.count("\n") - 1, "首")
print("训练字符数：", len(train_text), "  验证字符数：", len(val_text))
print("词表大小：", vocab_size)
print("“床前明月光” →", encode("床前明月光"))
assert decode(encode("床前明月光")) == "床前明月光"
print("逆变换回文字：", decode(encode("床前明月光")))

# %% [markdown]
# ## 步骤 2 · 一个编号怎样变成一个向量（第 5 章）
#
# 词嵌入是一张查表：词表里每个字对应一行 `d` 维的浮点数。
# 同一个字无论在句子的哪个位置，查到的都是同一行——这正是下一步要解决的问题。

# %%
# region step2
d = 96                                   # 每个字用多少个浮点数表示
tok = nn.Embedding(vocab_size, d)         # 词嵌入表：[词表大小, d]
nn.init.normal_(tok.weight, std=d ** -0.5)

ids = torch.tensor([encode("床前明月光")])   # [1, 5]
h = tok(ids)                              # [1, 5, 96]
# endregion step2

print("编号形状：", tuple(ids.shape), "  查表后形状：", tuple(h.shape))
print("“床”的向量前 4 个数：", [round(v, 3) for v in h[0, 0, :4].tolist()])
print("“明”的向量前 4 个数：", [round(v, 3) for v in h[0, 2, :4].tolist()])
print("两个字查到的向量相同吗：", torch.equal(h[0, 0], h[0, 2]))
print("同一个字出现两次，向量相同吗：", torch.equal(tok(ids)[0, 0], tok(torch.tensor([[ids[0, 0].item()]]))[0, 0]))

# %% [markdown]
# ## 步骤 3 · 注意力怎样决定谁看谁（第 6 章）
#
# 每个位置给所有位置打分，`softmax` 之后变成一组加起来等于 1 的权重。
# 因果掩码把“后面”的位置设成负无穷，权重归零：生成时不能偷看还没写出来的字。

# %%
# region step3
T = 6
scores = torch.randn(T, T)                              # 假装是 Q 和 K 打分的结果
causal = torch.tril(torch.ones(T, T)).bool()             # 下三角：位置 i 只能看到 0..i
masked = scores.masked_fill(~causal, float("-inf"))
weights = F.softmax(masked, dim=-1)                      # 每一行加起来是 1
# endregion step3

print("因果掩码（1 = 可以看，0 = 被挡住）：")
for row in causal.int().tolist():
    print("  ", " ".join(str(v) for v in row))
print("第 3 个位置（从 0 数）拿到的权重：", [round(v, 3) for v in weights[3].tolist()])
print("每一行的权重和：", [round(v, 3) for v in weights.sum(-1).tolist()])

# %% [markdown]
# ## 步骤 4 · 位置为什么必须单独给（第 7 章）
#
# 上一步的权重只看“谁和谁相关”，不看“谁排第几”。所以位置要另加一张表：
# 第 0 位、第 1 位……各一行向量，与内容无关。把第二个字换掉，位置那一项会被完整减掉。

# %%
# region step4
pos = nn.Embedding(24, d)                 # 24 = 模型一次最多看多少个字
nn.init.normal_(pos.weight, std=d ** -0.5)
positions = torch.arange(ids.shape[1])

h1 = tok(ids) + pos(positions)
ids2 = ids.clone()
ids2[0, 1] = stoi["月"]                   # 只把第二个字“前”换成“月”
h2 = tok(ids2) + pos(positions)
# endregion step4

print("位置 0 的向量前 4 个数：", [round(v, 3) for v in pos.weight[0, :4].tolist()])
print("位置 1 的向量前 4 个数：", [round(v, 3) for v in pos.weight[1, :4].tolist()])
print("换字前后，第 2 个位置的输入向量差：", [round(v, 3) for v in (h1 - h2)[0, 1, :4].tolist()])
print("这个差等于两个字嵌入之差吗：", torch.allclose((h1 - h2)[0, 1], tok.weight[stoi["前"]] - tok.weight[stoi["月"]], atol=1e-6))

# %% [markdown]
# ## 步骤 5 · “完全乱猜”的损失是多少（第 14 章）
#
# 损失用交叉熵。参数随机、对每个字一视同仁时，每个字的概率约 `1/词表大小`，
# 损失就落在 `ln(词表大小)` 附近。这是检查代码写没写错的第一个信号。

# %%
# region step5
class Block(nn.Module):
    """一个 Transformer Block：注意力 + 前馈层，各配一次 RMSNorm 和残差（第 8、9、10、11 章）。"""
    def __init__(self, d, n_heads):
        super().__init__()
        self.n_heads = n_heads
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.qkv, self.proj = nn.Linear(d, 3 * d, bias=False), nn.Linear(d, d, bias=False)
        hidden = 8 * d // 3
        self.gate, self.value, self.down = nn.Linear(d, hidden, bias=False), nn.Linear(d, hidden, bias=False), nn.Linear(hidden, d, bias=False)

    def forward(self, x):
        B, T, D = x.shape
        a = self.norm1(x)
        q, k, v = self.qkv(a).split(D, dim=-1)
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2) for t in (q, k, v))
        a = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        x = x + self.proj(a.transpose(1, 2).reshape(B, T, D))
        f = self.norm2(x)
        return x + self.down(F.silu(self.gate(f)) * self.value(f))


class TinyLLM(nn.Module):
    def __init__(self, vocab_size, d=96, n_layers=3, n_heads=4, block_size=24):
        super().__init__()
        self.tok = nn.Embedding(vocab_size, d)
        self.pos = nn.Embedding(block_size, d)
        self.blocks = nn.ModuleList(Block(d, n_heads) for _ in range(n_layers))
        self.norm = nn.RMSNorm(d)
        self.head = nn.Linear(d, vocab_size, bias=False)
        self.head.weight = self.tok.weight          # 输入输出共享一张表（第 5 章）
        nn.init.normal_(self.tok.weight, std=d ** -0.5)
        nn.init.normal_(self.pos.weight, std=d ** -0.5)

    def forward(self, idx):
        h = self.tok(idx) + self.pos(torch.arange(idx.shape[1]))
        for block in self.blocks:
            h = block(h)
        return self.head(self.norm(h))


block_size, batch_size = 24, 32
train_data = torch.tensor(encode(train_text), dtype=torch.long)
val_data = torch.tensor(encode(val_text), dtype=torch.long)

def get_batch(data):
    starts = torch.randint(len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[s : s + block_size] for s in starts])
    y = torch.stack([data[s + 1 : s + block_size + 1] for s in starts])
    return x, y

model = TinyLLM(vocab_size)
def lm_loss(x, y):
    return F.cross_entropy(model(x).reshape(-1, vocab_size), y.reshape(-1))
# endregion step5

x, y = get_batch(train_data)
print("参数量：", sum(p.numel() for p in model.parameters()))
print("一批样本：x", tuple(x.shape), " y", tuple(y.shape))
print("乱猜的理论值 ln(词表大小) =", round(math.log(vocab_size), 3))
print("随机参数下的实测损失 =", round(sum(lm_loss(*get_batch(train_data)).item() for _ in range(8)) / 8, 3))

# %% [markdown]
# ## 步骤 6 · 梯度怎样告诉每个参数往哪走（第 2、15 章）
#
# `backward()` 一次就把“这次错得有多离谱”分摊到全部参数上，每个参数得到一个梯度；
# 优化器按梯度的方向把参数挪一小步。走完这一步，同一批数据的损失会小一点。

# %%
# region step6
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)

loss_before = lm_loss(x, y)
optimizer.zero_grad(set_to_none=True)
loss_before.backward()                                    # 求梯度：第 2 章
grad_norm = torch.sqrt(sum((p.grad ** 2).sum() for p in model.parameters() if p.grad is not None))
n_grads = sum(1 for p in model.parameters() if p.grad is not None)
optimizer.step()                                          # 更新参数：第 15 章
loss_after = lm_loss(x, y)
# endregion step6

print("有梯度的参数张量：", n_grads, "个")
print("梯度总范数：", round(grad_norm.item(), 3))
print("同一批数据，更新前损失：", round(loss_before.item(), 4))
print("同一批数据，更新后损失：", round(loss_after.item(), 4))

# %% [markdown]
# ## 步骤 7 · 训一会儿，损失会掉下来（第 1、20 章）
#
# 把上一步重复几百次。每 50 步在没参加训练的验证集上再算一次损失，只看不更新。

# %%
# region step7
steps = 1000
log = {"loss": [], "val_step": [], "val_loss": [], "uniform": math.log(vocab_size)}   # 供网站画损失曲线
for step in range(steps + 1):
    xb, yb = get_batch(train_data)
    loss = lm_loss(xb, yb)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()
    log["loss"].append(loss.item())
    if step % 100 == 0:
        with torch.no_grad():
            v = sum(lm_loss(*get_batch(val_data)).item() for _ in range(4)) / 4
        log["val_step"].append(step)
        log["val_loss"].append(v)
        print(f"step {step:3d}  训练损失 {loss.item():.3f}  验证损失 {v:.3f}")
# endregion step7

# %% [markdown]
# ## 步骤 8 · 训练之后，让它写一首（第 17、21、24 章）
#
# 把预测的字接回去，再预测下一个。语料只有几百首诗，训练损失很低、验证损失反而很高：
# 模型把训练集背了下来，这是过拟合，第 17、21 章专门处理。

# %%
# region step8
@torch.no_grad()
def generate(prompt, max_new_tokens=40, temperature=0.8):
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
# endregion step8

torch.manual_seed(1)
for prompt in ["春", "床前", "孤舟"]:
    print(generate(prompt))

# %%
import json
with open("quickstart_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f)

# %% [markdown]
# 八步走完。想深挖哪一步，就去读对应的那一章；想从头看一遍完整流水线，读第 1 章。
