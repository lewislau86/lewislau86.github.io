# %% [markdown]
# # 第 6 章：文本与词元化
#
# 配套教案：https://lewislau86.github.io/tinyllm/tokenization
#
# 从上到下运行即可（`python tokenization.py`），CPU 上几秒钟。需要安装 `tokenizers` 和 `plotly`
# （本章记录的结果来自 tokenizers 0.23.3、plotly 7.1.0），无需 PyTorch、GPU 或模型下载。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本实验从 Unicode/字节开始，训练一个小型 ByteLevel BPE，检查特殊 token、标签移位、保存加载，
# 并比较四种词表预算。训练文本与测量文本均内置，后者不用于拟合词表。

# %%
import sys
import tokenizers
import plotly
print("Python:", sys.version.split()[0])
print("Tokenizers:", tokenizers.__version__, "Plotly:", plotly.__version__)

# %% [markdown]
# ## 1. 看起来一个字，长度可能不同
#
# 先预测 `猫`、`é`、`e\u0301`、`👩‍💻` 的码点数与字节数。Python 的 `len(str)` 不是屏幕上的字形计数器；NFC 也不负责把一切相似字形变成同一个字符。

# %%
# region unicode-lengths
import unicodedata

samples = ["A", "猫", "é", "e\u0301", "👩‍💻"]
for text in samples:
    print(repr(text), "码点:", len(text),
          "UTF-8 字节:", len(text.encode("utf-8")))

assert "é" != "e\u0301"
assert unicodedata.normalize("NFC", "e\u0301") == "é"
# endregion unicode-lengths

# %% [markdown]
# ## 2. 观察两次 BPE 合并
#
# 这是手写的教学算法，起始单位为 ASCII 字母。统计时乘上样本频次，先合并 `a+b`（8 次），再合并 `ab+ab`（3 次）。每次合并后必须更新片段与统计。

# %%
# region bpe-merges
from collections import Counter

weighted_words = [(list("abab"), 3), (list("abac"), 2), (list("ad"), 1)]

def merge_pair(parts, pair):
    result, i = [], 0
    while i < len(parts):
        if i + 1 < len(parts) and (parts[i], parts[i + 1]) == pair:
            result.append(parts[i] + parts[i + 1])
            i += 2
        else:
            result.append(parts[i])
            i += 1
    return result

for step in range(2):
    counts = Counter()
    for parts, frequency in weighted_words:
        for pair in zip(parts, parts[1:]):
            counts[pair] += frequency
    # 次数相同时按字符串排序，固定这个教学实现的选择规则。
    best = min(counts, key=lambda pair: (-counts[pair], pair))
    print("第", step + 1, "步:", best, "次数:", counts[best])
    weighted_words = [(merge_pair(parts, best), frequency)
                      for parts, frequency in weighted_words]
# endregion bpe-merges

# %% [markdown]
# ### 编码时依照已有 merge rank
#
# 下面直接指定一份很小的词表及合并顺序。先有 `b+c`，后有 `a+b`，所以 `abc` 得到 `a | bc`。这个单元只验证编码优先级，不训练新词表。

# %%
from tokenizers import Tokenizer, models
rank_demo = Tokenizer(models.BPE(
    vocab={"a": 0, "b": 1, "c": 2, "bc": 3, "ab": 4},
    merges=[("b", "c"), ("a", "b")],
))
assert rank_demo.encode("abc").tokens == ["a", "bc"]
print(rank_demo.encode("abc").tokens)

# %% [markdown]
# ## 3. 在训练集上训练 byte-level BPE
#
# 本例保留 256 个基础字节和 4 个特殊 token，不设置规范化器，不添加开头空格。语料只用于演示；词表预算太大时，频次阈值可能让合并提前停止。

# %%
# region train-tokenizer
from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders, processors

train_texts = [
    "TinyLLM learns from text. Text becomes tokens.",
    "A tokenizer maps text to token IDs and back.",
    "We train a small language model with a small vocabulary.",
    "我在学习语言模型。词元化把文本转换成编号。",
    "我们用中文和英文训练一个小词表。模型学习预测下一个词元。",
    "文本可以包含空格、换行和标点。学习需要反复实验。",
    "def add(a, b):\n    return a + b\n",
    "for step in range(10):\n    loss = step / 10\n",
    "price = 12.50; count = 2026; version = 'v1.2.3'",
    "Cafe café e\u0301; emoji 🙂; tabs\tand newlines\n",
]
special_tokens = ["<pad>", "<unk>", "<bos>", "<eos>"]

def train_tokenizer(vocab_size):
    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        min_frequency=2,
        special_tokens=special_tokens,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(train_texts, trainer=trainer)
    return tok

tokenizer = train_tokenizer(320)
print("实际词表大小:", tokenizer.get_vocab_size())
# endregion train-tokenizer

# %% [markdown]
# ## 4. 检查编码、offset 与还原
#
# 观察中文的字节片段与 `Ġ` 等显示符号。我们检查整个序列的还原；单独解码每个 token 可能遇到不完整的 UTF-8 字符。offset 也不保证每个 token 对应一个不同汉字。

# %%
# region encode-roundtrip
probe = "猫在学习 TinyLLM。\n"
encoded = tokenizer.encode(probe, add_special_tokens=False)
print("tokens:", encoded.tokens)
print("IDs:", encoded.ids)
print("offsets:", encoded.offsets)
assert tokenizer.decode(encoded.ids, skip_special_tokens=False) == probe

roundtrip_cases = ["", "  空格\t换行\n", "é", "e\u0301", "👩‍💻", "𠮷", probe]
for text in roundtrip_cases:
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    assert tokenizer.token_to_id("<unk>") not in ids
    assert tokenizer.decode(ids, skip_special_tokens=False) == text
print("普通文本往返检查通过:", len(roundtrip_cases), "个案例")
# endregion encode-roundtrip

# %% [markdown]
# ## 5. 注册特殊 token 后，还要定义添加规则
#
# 本例为每条样本加一次 BOS/EOS。默认解码会跳过它们，因此显示文本与模型内部的 ID 序列不同。

# %%
# region special-template
bos_id = tokenizer.token_to_id("<bos>")
eos_id = tokenizer.token_to_id("<eos>")
pad_id = tokenizer.token_to_id("<pad>")
tokenizer.post_processor = processors.TemplateProcessing(
    single="<bos> $A <eos>",
    special_tokens=[("<bos>", bos_id), ("<eos>", eos_id)],
)
with_special = tokenizer.encode("我在学习。")
assert with_special.ids[0] == bos_id and with_special.ids[-1] == eos_id
assert with_special.ids.count(bos_id) == with_special.ids.count(eos_id) == 1
print(with_special.tokens)
assert tokenizer.decode(with_special.ids) == "我在学习。"
# endregion special-template

# %% [markdown]
# ### 保留字符串出现在原文时
#
# `add_special_tokens=False` 关闭模板添加，但不是“所有文本一律按普通字符处理”的开关。观察字面量 `<eos>` 的 ID 与两种解码结果。生产系统需要制定保留字符串的处理协议。

# %%
# region literal-eos
literal = tokenizer.encode("文档里写了 <eos>", add_special_tokens=False)
assert eos_id in literal.ids
print("保留特殊标记:", tokenizer.decode(literal.ids, skip_special_tokens=False))
print("默认跳过标记:", tokenizer.decode(literal.ids))
# endregion literal-eos

# %% [markdown]
# ## 6. 为下一词元预测准备输入和目标
#
# 手动移位一次；输入侧的补齐掩码与目标侧的损失掩码分别处理。最后一个有效目标应为 EOS。`-100` 是损失忽略值，不是 token ID。本例没有实现注意力的 causal mask；使用会内部移位的模型时不能再次手动移位。

# %%
# region label-shift
sequences = [tokenizer.encode(text).ids for text in ["猫", "我在学习 TinyLLM。"]]
width = max(map(len, sequences))
padded = [ids + [pad_id] * (width - len(ids)) for ids in sequences]
masks = [[1] * len(ids) + [0] * (width - len(ids)) for ids in sequences]

input_ids = [row[:-1] for row in padded]
attention_mask = [row[:-1] for row in masks]
labels = [[token if valid else -100 for token, valid in zip(row[1:], mask[1:])]
          for row, mask in zip(padded, masks)]

for original, row_labels in zip(sequences, labels):
    valid_labels = [value for value in row_labels if value != -100]
    assert valid_labels == original[1:]
    assert valid_labels[-1] == eos_id
print("batch/序列长度:", len(input_ids), len(input_ids[0]))
print("两条样本有效目标数:", [sum(x != -100 for x in row) for row in labels])
# endregion label-shift

# %% [markdown]
# ## 7. 保存与重新加载
#
# 序列化 tokenizer 后，重新加载必须得到相同 ID。临时目录在本单元结束后清理。真实训练请保存到检查点目录，并另外记录语料版本、依赖版本以及上层的 chat template。

# %%
# region save-load
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

with TemporaryDirectory() as directory:
    path = Path(directory) / "tokenizer.json"
    tokenizer.save(str(path))
    reloaded = Tokenizer.from_file(str(path))
    for text in roundtrip_cases + ["文档里写了 <eos>"]:
        assert reloaded.encode(text).ids == tokenizer.encode(text).ids
    print("保存后加载的编码一致；SHA-256:", hashlib.sha256(path.read_bytes()).hexdigest())
# endregion save-load

# %% [markdown]
# ## 8. 比较词表预算
#
# 仅改变词表预算，四段测量文本不参与训练。统计不包含 BOS/EOS；bytes/token 只描述这批文本的压缩效率，不表示模型能力。

# %%
# region budget-sweep
evaluation_texts = {
    "中文": "今天我们检查词元化，看看陌生汉字龘能否还原。",
    "英文": "A tiny tokenizer should preserve unfamiliar text exactly.",
    "代码": "def square(x):\n    return x ** 2\n",
    "数字与 emoji": "2026-10-11 price=19.95 👩‍💻",
}
measurements = []
for budget in [260, 288, 320, 384]:
    candidate = train_tokenizer(budget)
    for domain, text in evaluation_texts.items():
        ids = candidate.encode(text, add_special_tokens=False).ids
        assert candidate.decode(ids, skip_special_tokens=False) == text
        measurements.append({
            "budget": budget, "actual_vocab": candidate.get_vocab_size(),
            "domain": domain, "tokens": len(ids),
            "bytes_per_token": len(text.encode("utf-8")) / len(ids),
        })
for row in measurements:
    print(row["budget"], row["actual_vocab"], row["domain"], row["tokens"],
          round(row["bytes_per_token"], 3))
# endregion budget-sweep

# %% [markdown]
# ### 用 Plotly 观察变化
#
# 横轴是请求的词表预算，悬停显示实际大小。比较同一种文本在不同预算下的变化；这里不同领域各只有一个长度不同的样本，不应把柱子的高低当成语言排名。

# %%
import plotly.graph_objects as go
fig = go.Figure()
for domain in evaluation_texts:
    rows = [row for row in measurements if row["domain"] == domain]
    fig.add_bar(
        name=domain,
        x=[str(row["budget"]) for row in rows],
        y=[row["tokens"] for row in rows],
        customdata=[[row["actual_vocab"], row["bytes_per_token"]] for row in rows],
        hovertemplate="词表预算: %{x}<br>实际词表: %{customdata[0]}"
                      "<br>token 数: %{y}<br>bytes/token: %{customdata[1]:.3f}"
                      "<extra>%{fullData.name}</extra>",
    )
fig.update_layout(
    title="四种词表预算下的序列长度（每类一个留出样本）",
    xaxis_title="目标词表大小（包含 4 个特殊 token）",
    yaxis_title="普通 token 数（不含 BOS/EOS）",
    legend_title="测量文本",
    barmode="group",
    template="plotly_white",
    height=480,
)
fig.show()

# %% [markdown]
# ## 9. 练习：规范化后还原什么？
#
# 先不要运行答案。把 `e\u0301` 经过 NFC 后编码，能否还原为原来的两个码点？尝试填出：
#
# ```python
# expected_text = ...  # 原文，还是 NFC 后的文本？
# assert decoded == expected_text
# ```
#
# 下面是参考答案，并检查词表预算 1,000 为什么没有自动带来 1,000 个条目。

# %%
from tokenizers import normalizers
normalized_tokenizer = Tokenizer.from_str(tokenizer.to_str())
normalized_tokenizer.normalizer = normalizers.NFC()
original = "e\u0301"
decoded = normalized_tokenizer.decode(
    normalized_tokenizer.encode(original, add_special_tokens=False).ids
)
assert decoded == unicodedata.normalize("NFC", original)
assert decoded != original
print("输入码点数:", len(original), "输出码点数:", len(decoded))

large_budget_tokenizer = train_tokenizer(1000)
actual = large_budget_tokenizer.get_vocab_size()
assert actual < 1000
print("预算 1000，实际词表:", actual, "；小语料和 min_frequency 限制了合并。")

# %% [markdown]
# ## 10. 可选：最长匹配与全局最少 token
#
# 自造的 ASCII 词表含单字母以及 `ab`、`abc`、`cdef`。先预测 `abcdef` 的贪心结果与全局结果，再运行答案。
#
# 动态规划用 `best[i]` 保存后缀 `text[i:]` 的最少 token 数；枚举当前位置能用的词表项，选 `1 + best[j]` 最小的路径。这只是单位成本的教学例子，不包含 CNF-MCE 的边界惩罚、候选生成或训练，也不是论文复现。

# %%
toy_vocab = set("abcdef") | {"ab", "abc", "cdef"}

def greedy_longest(text, vocab):
    result, i = [], 0
    while i < len(text):
        candidates = [piece for piece in vocab if text.startswith(piece, i)]
        if not candidates:
            raise ValueError("词表未覆盖输入")
        piece = max(candidates, key=lambda item: (len(item), item))
        result.append(piece)
        i += len(piece)
    return result

def minimum_tokens(text, vocab):
    n = len(text)
    best = [float("inf")] * n + [0]
    next_position = [None] * n
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n + 1):
            if text[i:j] in vocab and 1 + best[j] < best[i]:
                best[i] = 1 + best[j]
                next_position[i] = j
    if best[0] == float("inf"):
        raise ValueError("词表未覆盖输入")
    pieces, i = [], 0
    while i < n:
        j = next_position[i]
        pieces.append(text[i:j])
        i = j
    return pieces

greedy = greedy_longest("abcdef", toy_vocab)
optimal = minimum_tokens("abcdef", toy_vocab)
assert greedy == ["abc", "d", "e", "f"]
assert optimal == ["ab", "cdef"]
assert "".join(optimal) == "abcdef"
assert minimum_tokens("", toy_vocab) == []
print("最长匹配:", greedy, "；全局最少 token:", optimal)

# %% [markdown]
# ## 完成检查与后续阅读
#
# 你已经验证：Unicode/字节区别、BPE 合并与编码优先级、普通文本还原、特殊 token 协议、目标移位、保存加载，以及四组词表预算。最少 token 路径只对设定成本最优，不代表模型回答更好。下一步是将 ID 接入词嵌入矩阵。
#
# - [Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)
# - [Hugging Face Tokenizers 流水线](https://huggingface.co/docs/tokenizers/pipeline)
# - [Transformers 对话模板](https://huggingface.co/docs/transformers/chat_templating)
# - [SuperBPE（2025）](https://arxiv.org/abs/2503.13423v3)
# - [TokSuite（ICML 2026）](https://proceedings.mlr.press/v306/altintas26a.html)
# - [CNF-MCE（2026-10 预印本）](https://arxiv.org/abs/2610.01127)
#
# 本 notebook 使用小语料的 CPU 实验，不包含语言模型预训练或论文性能复现。完整解释和限制见[本章教案](https://lewislau86.github.io/tinyllm/tokenization)。

# %%
assert len(measurements) == 16
assert all(row["tokens"] > 0 for row in measurements)
assert len(fig.data) == 4
print("所有教学实验与断言通过。")
