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
# 编号只认字形、不认意思：多音多义的字，在哪里都是同一个编号。

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
print("“两行泪”里的“行”（háng）→", encode("两行泪")[1], "   “送行舟”里的“行”（xíng）→", encode("送行舟")[1])

# %% [markdown]
# ## 步骤 2 · 一个编号怎样变成一个向量（第 5 章）
#
# 词嵌入是一张查表：词表里每个字对应一行 `d` 维的浮点数，编号就是行号。
# 同一个字无论出现在哪一句、哪个位置，查到的都是同一行。

# %%
# region step2
d = 96                                   # 每个字用多少个浮点数表示
tok = nn.Embedding(vocab_size, d)         # 词嵌入表：[词表大小, d]
nn.init.normal_(tok.weight, std=d ** -0.5)

ids = torch.tensor([encode("床前明月光")])   # [1, 5]
h = tok(ids)                              # [1, 5, 96]
# endregion step2

h_other = tok(torch.tensor([encode("举头望明月")]))   # 另一句，“明”在第 4 个字
print("编号形状：", tuple(ids.shape), "  查表后形状：", tuple(h.shape))
print("“床前明月光”的第 1 个字“床”，向量前 4 个数：", [round(v, 3) for v in h[0, 0, :4].tolist()])
print("“床前明月光”的第 3 个字“明”，向量前 4 个数：", [round(v, 3) for v in h[0, 2, :4].tolist()])
print("“举头望明月”的第 4 个字“明”，向量前 4 个数：", [round(v, 3) for v in h_other[0, 3, :4].tolist()])
print("“床”和“明”的向量相同吗：", torch.equal(h[0, 0], h[0, 2]))
print("两句里的两个“明”，向量相同吗：", torch.equal(h[0, 2], h_other[0, 3]))

# %% [markdown]
# ## 步骤 3 · 注意力怎样决定谁看谁（第 6 章）
#
# 每个字用三个投影矩阵算出 q（我要找什么）、k（我有什么）、v（我能提供什么）。
# 第 i 个字拿自己的 q 和每个字的 k 做点积，得到一行分数；因果掩码把后面的字设成负无穷；
# softmax 把这一行变成加起来等于 1 的权重；最后按权重把各个字的 v 加起来，就是第 i 个位置的输出。

# %%
# region step3
x = h[0]                                          # 步骤 2 查到的 5 个向量：[5, 96]
W_q, W_k, W_v = (nn.Linear(d, d, bias=False) for _ in range(3))    # 三个投影矩阵，训练前是随机的

def attend(x):
    q, k, v = W_q(x), W_k(x), W_v(x)              # 每个字各算出 q、k、v，形状都是 [5, 96]
    scores = q @ k.T / d ** 0.5                   # [5, 5]：第 i 行是第 i 个字给每个字打的分
    causal = torch.tril(torch.ones(len(x), len(x))).bool()      # 下三角：位置 i 只能看 0..i
    weights = F.softmax(scores.masked_fill(~causal, float("-inf")), dim=-1)   # 每一行加起来是 1
    return scores, causal, weights, v, weights @ v                  # 输出 = 按权重把各个字的 v 加起来

scores, causal, weights, v, out = attend(x)
# endregion step3

with torch.no_grad():
    print("因果掩码（1 = 可以看，0 = 被挡住）：")
    for row in causal.int().tolist():
        print("  ", " ".join(str(c) for c in row))
    print("第 4 个字“月”给 5 个字打的分：", [round(s, 3) for s in scores[3].tolist()])
    print("遮掉后面以后，softmax 得到的权重：", [round(w, 3) for w in weights[3].tolist()])
    mix = sum(weights[3, j] * v[j] for j in range(5))
    print("“月”位置的输出前 4 个数：", [round(c, 3) for c in out[3, :4].tolist()],
          "  等于按权重把 v 加起来吗：", torch.allclose(out[3], mix, atol=1e-6))
    print("第 1 个字“床”的权重：", [round(w, 3) for w in weights[0].tolist()], "  输出就是它自己的 v 吗：", torch.allclose(out[0], v[0]))

# %% [markdown]
# ## 步骤 4 · 位置为什么必须单独给（第 7 章）
#
# 位置也有一张表：第 0 位、第 1 位……各一行向量，和是什么字无关。
# 进模型的向量 = 字向量 + 位置向量，96 个数逐个相加。

# %%
# region step4
pos = nn.Embedding(24, d)                     # 位置表：24 行，24 = 模型一次最多看多少个字
nn.init.normal_(pos.weight, std=d ** -0.5)
x_in = tok(ids) + pos(torch.arange(5))        # 字向量 + 位置向量：[1, 5, 96]
# endregion step4

with torch.no_grad():
    r4 = lambda vec: [round(c, 3) for c in vec[:4].tolist()]
    print("“明”的字向量                ", r4(tok.weight[stoi["明"]]))
    print("位置 2（从 0 数）的位置向量 +", r4(pos.weight[2]))
    print("加起来，进模型的向量        =", r4(x_in[0, 2]))
    other = tok(torch.tensor([encode("举头望明月")])) + pos(torch.arange(5))
    print("两句里的“明”：字向量相同吗", torch.equal(tok.weight[stoi["明"]], h_other[0, 3]),
          "  加上位置以后还相同吗", torch.equal(x_in[0, 2], other[0, 3]))

# %% [markdown]
# 为什么非加不可？把“床前明月光”的前四个字打乱成“月明前床光”。最后一个字“光”能看到前面所有的字，
# 不加位置时，它看到的是同一组向量，只是顺序不同，注意力算出的输出完全一样：

# %%
# region step4-shuffle
shuffled = torch.tensor([encode("月明前床光")])
with torch.no_grad():
    same_without = torch.allclose(attend(tok(ids)[0])[-1][-1], attend(tok(shuffled)[0])[-1][-1], atol=1e-6)
    same_with = torch.allclose(attend(x_in[0])[-1][-1], attend((tok(shuffled) + pos(torch.arange(5)))[0])[-1][-1], atol=1e-6)
# endregion step4-shuffle
print("不加位置：“光”的输出在两句里相同吗：", same_without)
print("加上位置：“光”的输出在两句里相同吗：", same_with)

# %% [markdown]
# ## 步骤 5 · 训练的目标：让正确答案的概率变大（第 15 章）
#
# 把前面的零件装成一个完整的模型。它对每个位置输出词表上每个字的概率，猜“下一个字是什么”。
# 一道题的损失是 -ln(正确答案的概率)：概率越大，损失越小。训练要做的，就是让所有题的平均损失尽量小。

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

# region step5-one
prompt, answer = "床前明月", "光"
with torch.no_grad():
    probs = F.softmax(model(torch.tensor([encode(prompt)]))[0, -1], dim=-1)   # 最后一个位置：猜下一个字
p_answer = probs[stoi[answer]].item()
# endregion step5-one
print("参数量：", sum(p.numel() for p in model.parameters()))
print(f"题目：看到“{prompt}”，猜下一个字。正确答案“{answer}”")
print(f"模型给“{answer}”的概率 {p_answer:.6f}（完全平均是 1/{vocab_size} = {1 / vocab_size:.6f}）")
print(f"这一题的损失 -ln({p_answer:.6f}) = {-math.log(p_answer):.3f}")
top = probs.topk(5)
print("模型最想填的 5 个字：", [(itos[i], round(q, 4)) for i, q in zip(top.indices.tolist(), top.values.tolist())])

x, y = get_batch(train_data)
print("一批样本：x", tuple(x.shape), " y", tuple(y.shape))
print("乱猜的理论值 ln(词表大小) =", round(math.log(vocab_size), 3))
print("随机参数下的实测损失 =", round(sum(lm_loss(*get_batch(train_data)).item() for _ in range(8)) / 8, 3))

# %% [markdown]
# ## 步骤 6 · 怎样把损失变小：梯度和优化器（第 2、16 章）
#
# 梯度回答一个问题：把某个参数加大一点点，损失会变大还是变小、变多少。
# 先拿步骤 5 的那道题，挑一个参数，按梯度预测、再亲手挪一下核对。

# %%
# region step6-grad
loss_one = -torch.log_softmax(model(torch.tensor([encode(prompt)]))[0, -1], dim=-1)[stoi[answer]]
model.zero_grad(set_to_none=True)
loss_one.backward()                                       # 一次算出全部参数的梯度
row = stoi[answer]
g = model.tok.weight.grad[row]                            # 字表里“光”那一行 96 个参数的梯度
j = g.abs().argmax().item()                               # 看其中梯度最大的那一个
step = -0.01 * g[j].sign()                                # 逆着梯度的方向挪 0.01
with torch.no_grad():
    saved = model.tok.weight[row, j].clone()
    model.tok.weight[row, j] += step
    loss_moved = -torch.log_softmax(model(torch.tensor([encode(prompt)]))[0, -1], dim=-1)[stoi[answer]]
    model.tok.weight[row, j] = saved                      # 放回原值，不影响后面
# endregion step6-grad
print(f"这一题的损失：{loss_one.item():.4f}")
print(f"“光”那一行第 {j} 个参数：值 {saved.item():+.4f}，梯度 {g[j].item():+.4f}")
print(f"把它挪 {step.item():+.2f}：按梯度预测损失变化 {g[j].item() * step.item():+.5f}，实际变化 {loss_moved.item() - loss_one.item():+.5f}")

# %% [markdown]
# 所有参数一起挪：每个参数都朝“让损失变小”的方向走一小步，`参数 ← 参数 - 学习率 × 梯度`。
# 实际用的 AdamW 是它的改进版，会按每个参数过去的梯度自动调整步子大小（第 16 章）。

# %%
# region step6
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)

loss_before = lm_loss(x, y)
optimizer.zero_grad(set_to_none=True)
loss_before.backward()                                    # 求梯度：第 2 章
grad_norm = torch.sqrt(sum((p.grad ** 2).sum() for p in model.parameters() if p.grad is not None))
n_grads = sum(1 for p in model.parameters() if p.grad is not None)
optimizer.step()                                          # 更新参数：第 16 章
loss_after = lm_loss(x, y)
# endregion step6

print("有梯度的参数张量：", n_grads, "个")
print("梯度总范数：", round(grad_norm.item(), 3))
print("同一批数据，更新前损失：", round(loss_before.item(), 4))
print("同一批数据，更新后损失：", round(loss_after.item(), 4))

# %% [markdown]
# ## 步骤 7 · 训一会儿，损失会掉下来（第 1、21 章）
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
            val_loss = sum(lm_loss(*get_batch(val_data)).item() for _ in range(4)) / 4
        log["val_step"].append(step)
        log["val_loss"].append(val_loss)
        print(f"step {step:3d}  训练损失 {loss.item():.3f}  验证损失 {val_loss:.3f}")
# endregion step7

# %% [markdown]
# ## 步骤 8 · 训练之后，让它写一首（第 18、22、27 章）
#
# 把预测的字接回去，再预测下一个。语料只有几百首诗，训练损失很低、验证损失反而很高：
# 模型把训练集背了下来，这是过拟合，第 18、22 章专门处理。

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
for start in ["春", "床前", "孤舟"]:
    print(generate(start))

# %% [markdown]
# 回到步骤 1 的问题：“行”在“两行泪”和“送行舟”里是同一个编号、同一个字向量。
# 经过 3 个 Block 以后呢？取“行”这个位置最后的向量，用余弦相似度比一比（1 表示方向完全相同）。

# %%
# region step8-context
@torch.no_grad()
def vector_after_blocks(text):
    """把 text 送进训练好的模型，取最后一个字经过 3 个 Block 之后的向量。"""
    idx = torch.tensor([encode(text)])
    h = model.tok(idx) + model.pos(torch.arange(idx.shape[1]))
    for block in model.blocks:
        h = block(h)
    return h[0, -1]

contexts = {"还将两行": "háng", "万里送行": "xíng", "寥落古行": "xíng"}
vecs = {c: vector_after_blocks(c) for c in contexts}
# endregion step8-context
cos = lambda a, b: F.cosine_similarity(a, b, dim=0).item()
print("查表得到的字向量：三处“行”完全相同，余弦相似度 1.0")
names = list(contexts)
for i in range(3):
    for k in range(i + 1, 3):
        a, b = names[i], names[k]
        print(f"经过 3 个 Block 以后：“{a}”（{contexts[a]}）与“{b}”（{contexts[b]}）的“行”，余弦相似度 {cos(vecs[a], vecs[b]):.3f}")

# %%
@torch.no_grad()
def first_head(text):
    """训练好的模型第 1 层、第 1 个注意力头，在 text 上的打分、权重、v 和输出（给网站的注意力动画用）。"""
    idx = torch.tensor([encode(text)])
    blk = model.blocks[0]
    a = blk.norm1(model.tok(idx) + model.pos(torch.arange(idx.shape[1])))
    q, k, v = blk.qkv(a)[0].split(d, dim=-1)
    hd = d // blk.n_heads
    q, k, v = q[:, :hd], k[:, :hd], v[:, :hd]
    s = q @ k.T / hd ** 0.5
    mask = torch.tril(torch.ones(len(q), len(q))).bool()
    w = F.softmax(s.masked_fill(~mask, float("-inf")), dim=-1)
    return s, w, v, w @ v

def pack(s, w, v, o):
    r = lambda t: [[round(c, 4) for c in row] for row in t.tolist()]
    return {"scores": r(s), "weights": r(w), "v": r(v[:, :6]), "out": r(o[:, :6])}

with torch.no_grad():
    attention_demo = {"names": list("床前明月光"),
                      "before": pack(scores, weights, v, out),
                      "after": pack(*first_head("床前明月光"))}
log["position_demo"] = {"names": list("床前明月光"),
                        "tok": [[round(c, 3) for c in tok(ids)[0, i, :4].tolist()] for i in range(5)],
                        "pos": [[round(c, 3) for c in pos.weight[i, :4].tolist()] for i in range(5)],
                        "sum": [[round(c, 3) for c in x_in[0, i, :4].tolist()] for i in range(5)]}
with open("quickstart_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f)
with open("quickstart_attention.json", "w", encoding="utf-8") as f:
    json.dump(attention_demo, f, ensure_ascii=False)

# %% [markdown]
# 八步走完。想深挖哪一步，就去读对应的那一章；想从头看一遍完整流水线，读第 1 章。
