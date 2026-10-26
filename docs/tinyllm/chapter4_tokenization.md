# Chapter 4：文本与词元化

当我们输入“我在学习 TinyLLM。”时，模型并没有直接收到这些文字。它收到的是一串整数；这些整数随后被转换成向量，送入 Transformer。<strong>词元化（tokenization）负责把文本转换成模型可以使用的离散符号序列。</strong> 这一章把这条路径走一遍：文字怎样存储、怎样切分、怎样变成编号，以及这些编号怎样进入下一词元预测任务。

只需要 Python 的字符串、列表和字典基础即可开始。配套 <a href="/tinyllm/chapter4_Tokenization/ch4.ipynb" download>ch4.ipynb</a> 使用内置的小语料，可以在 CPU 上运行，不下载模型或数据集；其中包含本章实验、交互图表和练习。建议先读到第 5 节，再运行 notebook；第 9 节的近期研究可以留到最后。

资料核对日期：<strong>2026-10-11</strong>。近期部分收录 SuperBPE、TokSuite、TokEval 和 2026 年 10 月的 CNF-MCE 预印本；实验使用固定版本的库，论文结果与本章实测分别标明。

## TinyLLM 主线怎么选

从零训练时先用<strong>可逆的字节级 BPE</strong>，保存完整的规范化、预切分、合并规则和特殊 token 配置。它能让未见字符退回字节序列；但中文字的部分字节也可能成为独立 token，不能把“可逆”误当成“切分一定符合语义”。词表大小应按中文/英文/代码比例、序列长度与训练预算比较；若需要复现已有模型，必须使用其原 tokenizer，不能在训练后直接换一套。后续的 BPE 实验会逐步解释这些取舍。

## 1. 模型收到的不是文字，而是编号

假设某个教学词表中有 `我 → 12`、`在 → 35`、`学习 → 78`，那么“我在学习”可以被编码成 `[12, 35, 78]`。编号完全由这份词表决定：78 不意味着“学习”比“我”大，也不意味着两个编号相近的词意思相近。

接下来，模型按照编号查找词嵌入矩阵的对应行：

$$
\text{文本}\ \longrightarrow\ (t_1,\ldots,t_n)\ \longrightarrow\ (E[t_1],\ldots,E[t_n]).
$$

若词表有 $V$ 个条目、每个向量有 $d$ 个分量，那么 $E$ 的形状是 $[V,d]$。<strong>Tokenizer 决定“哪个片段对应哪一行”，模型训练决定“这一行的向量是什么”。</strong> 后者会在 [Chapter 5：词嵌入与输出层](chapter5_embeddings_output.md) 中展开。

| 名称 | 含义 | 一个可能的例子 |
| --- | --- | --- |
| token（词元） | 分词器选出的单位，可以是词、字、字节片段或特殊标记 | `学习`，也可能被拆得更细 |
| vocabulary（词表） | token 与整数 ID 的对应关系 | `学习 → 78` |
| tokenizer（分词器） | 包括预处理、切分、编号与解码规则的完整工具 | 按固定配置把文本转换成 ID 序列 |

本章展示的编号只属于本章的小词表，不能直接送给别人的预训练模型。即使两个词表大小相同，只要 ID 含义不同，输入就会错位。

## 2. 一个“字”到底占多少长度？

### 从 Unicode 码点到 UTF-8 字节

Python 的 `str` 表示 Unicode 文本。通常说的“字符”可能指码点，也可能指屏幕上看起来的一个字形；两者并不总相等。UTF-8 则把码点编码成字节，每个字节是 0～255 之间的整数。Python 的 `len(text)` 按码点计数，`len(text.encode("utf-8"))` 按字节计数。[Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)

```python
import unicodedata

samples = ["A", "猫", "é", "e\u0301", "👩‍💻"]
for text in samples:
    print(repr(text), "码点:", len(text),
          "UTF-8 字节:", len(text.encode("utf-8")))

assert "é" != "e\u0301"
assert unicodedata.normalize("NFC", "e\u0301") == "é"
```

`猫` 是 1 个码点、3 个字节；`é` 是 1 个码点、2 个字节，而 `e` 加组合重音是 2 个码点、3 个字节。`👩‍💻` 由女人、零宽连接符和电脑这 3 个码点构成，共 11 个字节，通常显示为一个组合 emoji。它们各占几个 token，还要看具体 tokenizer。

因此，“一个中文字等于一个 token”不能作为通用估算规则。同一份文本的<strong>字形数、码点数、字节数和 token 数是四种不同的长度</strong>。

### 规范化会改变什么？

规范化（normalization）可以把某些等价写法统一。NFC 可以将 `e` 加组合重音组合成 `é`；NFKC 还会统一一些兼容形式，例如全角字符。小写化、去除重音、合并空白也属于常见的文本处理，但会丢掉原始写法的信息。

需要提前决定解码的承诺：是恢复<strong>原文</strong>，还是恢复<strong>规范化后的文本</strong>？如果编码前先把 `Hello` 变成 `hello`，解码器通常无法知道原来的 H 是大写。本章不配置规范化器，也不自动添加开头空格，让普通文本的往返还原更容易检查。

空格也有内容：Python 代码的缩进、Markdown 的换行、数字之间的分隔都可能有用。不要为了让示例整洁，就在编码前无条件调用 `strip()` 或 `" ".join(text.split())`。

## 3. 为什么会出现子词和 BPE？

用整个词作为单位，需要决定怎样识别词边界，并处理没有见过的新词；每个 Unicode 码点都是一个单位，序列可能很长，而且完整字符集很大。字节词表只需要 256 个基础值，能覆盖有效 UTF-8 文本，但逐字节建模也会产生很长的序列。

子词方法折中了这两端：把常见片段合在一起，不常见的部分拆开。它不要求每个片段都是语言学上的词根。<strong>Byte-level BPE 从字节开始学习合并，一个 token 也可能只是某个中文字的部分字节。</strong>

| 起始单位 | 好处 | 需要面对的问题 |
| --- | --- | --- |
| 整个词 | 常见词的序列短、直观 | 新词和词边界处理；中文不能简单按空格切词 |
| Unicode 码点 | 容易理解字符边界 | 大字符集、未覆盖字符、长序列 |
| 字节 | 256 个基础值即可表示有效 UTF-8 文本 | 多字节字符可能被拆分，序列较长 |
| 子词或字节合并片段 | 让常见片段获得更短表示 | 需要训练语料、词表预算和确定的编码规则 |

### BPE 训练：反复合并常见的相邻片段

Byte Pair Encoding，简称 BPE。先用一个只有 ASCII 字母的例子看清机制：语料中 `abab` 出现 3 次、`abac` 出现 2 次、`ad` 出现 1 次。初始单位是单个字母，统计相邻对时要乘上每条样本的出现次数。

```python
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
```

第一步合并 `a + b → ab`，计数为 8；第二步合并 `ab + ab → abab`，计数为 3。训练器持续更新统计，直到达到词表预算或没有符合条件的合并。这段代码只演示合并；下一节使用库处理字节映射、预切分和模型保存。

### BPE 编码：按照已有合并顺序处理新文本

训练结束后，编码一篇新文章时不会重新统计这篇文章里的高频对。编码器使用已经学到的合并优先级（merge rank）。如果先学到 `b + c → bc`，后学到 `a + b → ab`，新文本 `abc` 会优先得到 `a | bc`；从左边贪心匹配最长词表项则可能得到 `ab | c`。这两种算法不能混用。[Hugging Face BPE 教程](https://huggingface.co/learn/llm-course/en/chapter6/5)

BPE 的合并通常也不能跨过预切分器建立的边界。先按单词切开，再训练 BPE，就无法直接学到跨过这些边界的短语。这一点会帮助我们理解第 9 节的 SuperBPE。

### SentencePiece、Unigram 和 BPE 是什么关系？

BPE 是算法，SentencePiece 是工具，不能把它们简单当作互斥选项。SentencePiece 可以训练 BPE，也可以训练 Unigram；它可以直接读取原始句子，并用 `▁` 表示空白。其默认规范化涉及 NFKC，因此使用时仍要核对规范化配置与还原要求。[SentencePiece 官方说明](https://github.com/google/sentencepiece)

Unigram 从一批候选片段及其概率出发，逐步筛选词表，编码时选择概率较高的切分路径；BPE 保存的是合并过程。WordPiece 也是常见子词方法，但具体训练与编码规则不同。本章先学会一套 BPE 流程，不要求同时实现所有算法。[Tokenizers 模型组件](https://huggingface.co/docs/tokenizers/components)

## 4. 亲手训练一个可还原文本的分词器

### 先理解流水线，再调用 API

一个 tokenizer 不只有词表。常见编码流程是：<strong>规范化 → 预切分 → BPE 等模型切分并映射 ID → 添加特殊 token</strong>。解码时根据 ID 找到片段，按解码规则恢复文本。预切分、规范化和后处理都是配置的一部分，不能只保存一个词表文件就认为事情结束了。[Tokenizers 流水线](https://huggingface.co/docs/tokenizers/pipeline)

本章固定使用 `tokenizers==0.22.2`，以便运行相同 API；这不表示它是资料核对日的最新版本。Notebook 的 Plotly 图表固定为 `plotly==6.3.0`。在选定的 Python 3.11 环境中安装：

```sh
python -m pip install tokenizers==0.22.2 plotly==6.3.0
```

下面是专门编写的教学训练集。后面的测量句子另行列出，<strong>不用于训练词表</strong>。真实项目中，也要先划分训练、验证和测试数据，再用训练部分拟合 tokenizer。

```python
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
```

`initial_alphabet` 保留全部 256 个字节对应的基础符号，所以没见过的有效 UTF-8 文本仍有表示路径。`min_frequency=2` 表示低于该频次的候选不继续合并；`vocab_size` 是目标预算，语料很小时实际大小可能达不到它。特殊 token 也占用词表位置，本例至少需要 256 + 4 个位置。

ByteLevel 内部把字节映射成可显示的符号，再供 BPE 操作。它仍有预切分规则，不等于“对整篇文章任意合并字节”。`add_prefix_space=False` 避免在没有开头空格的输入前自动补一个空格。训练器与保存 API 的用法可对照 [Tokenizers 官方入门](https://huggingface.co/docs/tokenizers/quicktour)。

### 观察切分，同时检查还原

```python
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
```

token 可能含有 `Ġ` 等符号，看起来也可能像乱码；这是字节映射的显示形式，不是原文突然增加了这些字母。`offsets` 帮助定位 token 对应的原文区域，但拆成多个字节片段的字符可能对应重叠区域，不能把每个 offset 都当作独立汉字。

<strong>逐 token 解码后再拼字符串，不保证等于把整个 ID 序列一起解码。</strong> 单个 token 可能只有 UTF-8 字符的一部分。生成时若要逐步显示文本，应使用能缓冲不完整字节序列的流式解码逻辑；不能看到替换符 `�` 就断言词表损坏了。

本例检查的是正常 Unicode 文本编码所得完整序列的还原，不是任意 ID 序列都能组成有效 UTF-8。随意截断序列，也可能恰好截在字符内部。

## 5. 特殊 token 也需要明确的协议

普通 token 表示文本片段；特殊 token 为序列提供结构。常见名称包括 BOS（开始）、EOS（结束）、PAD（补齐）和 UNK（无法表示的输入）。这些名称和用途不是所有模型统一的标准：有些模型不用 BOS，有些会区分一条消息结束与整轮对话结束。

将 `<bos>` 和 `<eos>` 注册进词表，<strong>不等于每次编码都会自动添加它们</strong>。本例显式设置后处理模板：

```python
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
```

这里的 `decode` 默认跳过特殊 token，所以不会把 BOS/EOS 显示给用户。但如果普通输入恰好包含字面量 `<eos>`，库也可能把它识别成已注册的特殊 token，默认解码会跳过它：

```python
literal = tokenizer.encode("文档里写了 <eos>", add_special_tokens=False)
assert eos_id in literal.ids
print("保留特殊标记:", tokenizer.decode(literal.ids, skip_special_tokens=False))
print("默认跳过标记:", tokenizer.decode(literal.ids))
```

这说明“原文可逆”需要附带条件。`add_special_tokens=False` 关闭的是模板添加，不保证把用户文本中的保留标记当作普通字符。实际产品必须确定保留字符串的转义或普通文本编码策略；不要把用户字符串直接当成可信的对话控制标记。

对话模型还需要 chat template：把角色、内容、消息分隔和生成起点序列化成训练时使用的格式。使用预训练模型时应随模型一起加载模板；`apply_chat_template(tokenize=True)` 可以直接获得相应 ID。若先生成模板字符串，再单独编码，必须检查是否会重复插入 BOS/EOS。不同模型的角色标记不能凭名字互换。[Transformers 对话模板说明](https://huggingface.co/docs/transformers/chat_templating)

## 6. 把 ID 序列接到“预测下一个词元”

假设一条样本经过模板得到 `[BOS, 我, 在, 学习, EOS]`。最简单的下一词元任务使用：

| 位置 | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| 模型输入 | BOS | 我 | 在 | 学习 |
| 预测目标 | 我 | 在 | 学习 | EOS |

输入与目标错开一位，每个位置学习预测紧接着的 token。下面只用列表展示数据构造，无需加载 PyTorch 或训练模型：

```python
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
```

这里有三种不同的“遮住”：

- <strong>padding attention mask</strong> 告诉注意力哪些位置是补齐位置；本例中 1 表示有效、0 表示补齐。
- <strong>causal mask</strong> 阻止当前位置偷看未来，通常在注意力层里构造，本段代码没有实现。
- <strong>loss mask</strong> 决定哪些目标参与损失。本例用 `-100` 表示忽略标签，后续损失函数需要采用相同的 `ignore_index`；它不是词表里的 token ID。

EOS 是需要学习的结束目标，本例保留它的损失；PAD 才被屏蔽。尤其当 PAD 与 EOS 共用 ID 时，不能简单地按 `label == pad_id` 删掉所有目标，应根据真实长度或补齐掩码判断。

本例是<strong>手动移位</strong>的教学实现。有些模型接口会在内部移位，此时应按其接口提供未移位标签，避免错开两次。拼接多篇文档时，还要决定是否允许后一篇关注前一篇：插入 EOS 不会自动建立注意力隔离。相关内容将在 [Chapter 10](chapter10_data_pipeline.md) 和 [Chapter 11](chapter11_language_model_loss.md) 继续展开。

## 7. 保存的是整套规则，比较的是同一批文本

### 保存、加载与模型兼容性

```python
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
```

`TemporaryDirectory` 在实验后会清理文件；实际训练应把 `tokenizer.json` 保存在检查点目录，另外记录训练语料版本、库版本和训练参数。使用对话模板时，还要保存模板及相关配置。这份底层 Tokenizers JSON 并不自动包含 Transformers 层的 chat template。

不要在模型训练途中重新训练 tokenizer 然后沿用原嵌入权重：旧 ID 的含义可能已经改变。增加词表条目也需要扩展输入/输出层并学习新权重。即使固定词表只更换切分算法，输入序列的分布仍可能改变，需要重新评估。

### 测量词表大小与序列长度

下面固定训练文本、预切分和频次阈值，只改变词表预算。测量使用四段未参与训练的文本；这是观察机制的小实验，不是中英文或代码能力排行榜。

```python
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
```

可以同时记录以下指标，且始终注明是否包含 BOS/EOS 等结构 token：

| 指标 | 计算方法或观察点 | 能说明什么 |
| --- | --- | --- |
| token 数 | 同一份原文编码后的长度 | 序列长度与上下文占用 |
| bytes/token | 原文 UTF-8 字节数 ÷ 普通 token 数 | 同一数据集上的压缩效率，越高表示序列越短 |
| tokens/码点 | token 数 ÷ Python `len(text)` | 文本切得多碎；不同语言的码点不等于同等信息量 |
| 实际词表大小 | `get_vocab_size()` | 实际用了多少词表位置，不只是配置预算 |
| 往返一致性 | `decode(encode(text)) == text` | 约定范围内是否保留原始文本 |
| 实际出现的词表比例 | 测量语料中用过的普通 ID 数 ÷ 普通词表大小 | 该数据集上的利用情况；小样本不能证明未出现的 token 无用 |

数值和代码还需要单独看切分边界。比如 `123456` 被切成 `123 | 456` 与 `12 | 345 | 6`，不仅 token 数不同，数字的三位分组也不同。代码中的换行、缩进和标点同样有结构作用。可以把每个 token 解码后连同 ID、起止位置一起检查，但 <strong>token 的可视化字符串不一定就是完整 Unicode 字符</strong>：字节级片段可能落在多字节字符中间，应以整段解码与原文比较为准。[TokEval](https://arxiv.org/abs/2608.18062) 因此把 UTF-8 字符边界、数字位值边界和代码结构纳入评价，而不只看压缩率。

本章固定环境下的实测如下；每个领域只对应上面的一条留出文本，不含 BOS/EOS。

| 目标词表大小 | 实际大小 | 中文 token 数 | 英文 token 数 | 代码 token 数 | 数字与 emoji token 数 |
| --- | --- | --- | --- | --- | --- |
| 260 | 260 | 66 | 57 | 33 | 34 |
| 288 | 288 | 60 | 45 | 31 | 34 |
| 320 | 320 | 56 | 41 | 26 | 33 |
| 384 | 337 | 53 | 40 | 25 | 33 |

预算为 260 时，全部位置都被 256 个基础字节和 4 个特殊 token 占用，普通文本尚未获得合并，因此每个字节对应一个 token。预算设为 384，实际只得到 337 个条目，因为剩余候选达不到频次阈值。Notebook 用 Plotly 展示这些变化。先观察“大词表是否真的达到预算”，再比较同一份文本在不同预算下的结果；各领域原文长度不同，不能直接按 token 总数给语言排名。

## 8. 更少的 token，不自动等于更好的模型

对相同原文，较短序列通常能减少上下文位置占用，并改变注意力计算与 KV cache 成本；但更大词表也会增加嵌入和输出层成本。以共享输入输出权重的简单情况为例，从 32,000 扩到 128,000 个词元、向量维数固定为 768，仅这张矩阵就增加：

$$
(128000-32000)\times768=73{,}728{,}000
$$

个参数。若输入输出不共享，通常还要分别计算两张矩阵。序列节省、词表层开销、编码速度和任务质量需要合起来评估。

另一个容易误读的指标是困惑度（perplexity，PPL）。它通常按 token 平均负对数似然后取指数；tokenizer 改变，平均的单位也变了。不能看到 A 的 PPL 比 B 小，就跨 tokenizer 判定模型更好。可以在相同原文和评分协议下补充按 UTF-8 字节归一化的负对数似然，但它仍不是问答正确率；BOS/EOS、文本边界及规范化处理也必须一致。

“训练相同数量 token”也未必公平：压缩更好的 tokenizer 可能让模型看到了更多原始文本。研究比较需要注明固定的是文本、token 数、参数量、计算量还是时间，不能把这些预算当成同一个条件。

## 9. 近期研究正在改变哪些环节？

下面的工作可以围绕三个问题阅读：<strong>边界能否跨越、词表怎样构造、效果怎样验证</strong>。它们不是要求初学者立刻替换现成模型的操作清单。

### SuperBPE：让词元跨过空格边界

[SuperBPE（COLM 2025，2025-08-26 修订版）](https://arxiv.org/abs/2503.13423v3) 先学习子词，再允许合并跨越空格，形成包含多个词的单位。论文在 200K 词表条件下报告最多约 33% 的 token 数减少，并通过从头训练模型比较下游表现。这里改变的是词表学习过程；不能只修改一个已训练模型的分词器，就假定得到论文的收益。

### CNF-MCE：分别研究词表构建与编码路径

[CNF-MCE（2026-10-01，预印本）](https://arxiv.org/abs/2610.01127) 用 CNF 统计候选片段并按实际使用情况筛选词表，再用 MCE 的动态规划最小化切分成本。“最优”针对定义的成本函数，不代表语义或回答质量最优。固定 qwen250k 词表时，论文英文网页实验的每千字符 token 数从 BPE 的 222.5 降至 MCE 的 221.6；更换整套词表的压缩收益则属于另一项实验。从头训练模型的结果，也不能证明对既有模型直接换编码算法是无损的。[固定词表结果](https://arxiv.org/html/2610.01127#S4.SS5)

为理解“全局选择”和“从左匹配最长项”的差异，可以使用一个<strong>自造的小例子</strong>：词表包含每个单字母，以及 `ab`、`abc`、`cdef`。编码 `abcdef` 时，从左选最长项得到 `abc | d | e | f`，最少词元的路径则是 `ab | cdef`。Notebook 实现这个单位成本的动态规划。它没有论文中的边界惩罚、候选生成与训练过程，<strong>只用于解释思想，不是 CNF-MCE 的复现</strong>。

### TokSuite：评价切分对模型行为的影响

[TokSuite（ICML 2026）](https://proceedings.mlr.press/v306/altintas26a.html) 在其控制实验中比较了 14 个使用不同 tokenizer 预训练的模型，并考察多种语言与输入扰动下的行为。它提醒我们把实验推进到下游：除了数 token，还要看错别字、空白变化、语言差异等情形下的结果。压缩表格提供的是线索，模型评估才能回答任务表现是否改善。

### TokEval：先检查切分本身的结构

[TokEval（COLM 2026）](https://arxiv.org/abs/2608.18062) 给出了比 token 数更细的评价方法，例如 UTF-8 字符边界是否完整、数字是否沿位值边界切分。作者还从头训练只改变 tokenizer 设计的模型，用按字节归一化的语言模型损失和任务表现检验这些指标。其报告指出，不同内在指标与不同任务能力的关联程度不一样；<strong>一个压缩率数字不能代替全面评测</strong>。对 TinyLLM，合理的顺序是先检查文本可逆性，再记录字符、数字与换行的切分边界，比较同一文本上的 token 数及编码耗时，最后才用训练后的模型检验效果。字节级 token 跨越字符边界并不必然是错误，但这种行为应当能被测量和解释。

### 延伸阅读：BLT 为什么不是“去掉分词步骤”这么简单？

[Byte Latent Transformer（BLT，2024 年提出）](https://arxiv.org/abs/2412.09871) 是更早但相关的另一条路线：直接从字节出发，动态组织成 patch，并在不同层级分配计算。它改变了模型如何处理字节和片段，涉及模型架构与训练；不能理解成把当前 BPE 替换成 `text.encode("utf-8")` 就完成了升级。

继续做课程实验时，可以先固定词表和 ID 映射，比较不同切分路径的 token 数、可逆性、数字/换行边界和编码耗时；只有接上模型，并在相同原文与预算下测量损失、任务质量、延迟及显存，才有依据讨论实际收益。Agent 把旧信息放回提示词后，这些文本仍要经过同一个 tokenizer；较短的序列可能降低 [Chapter 20 的 KV cache](chapter20_inference_efficiency.md) 占用，但 Agent 是否找对记忆属于 [Chapter 25](chapter25_agent_memory.md) 的另一项评测。

## 10. 动手检查与练习

尝试先预测结果，再运行 notebook：

1. `é` 与 `e\u0301` 看起来相近，为什么码点数和字节数不同？添加 NFC 后，应该断言还原原文，还是还原 NFC 后的文本？
2. 只训练英文语料，再编码从未出现过的汉字；为什么保留 256 个基础字节可以避免 UNK，却不能保证这个汉字只用一个 token？
3. 把词表预算调到 1,000，检查实际词表大小。如果没达到预算，是库出错了，还是频次阈值与语料量限制了合并？
4. 文本中直接写入 `<eos>`，比较默认解码与 `skip_special_tokens=False`。解释“关闭自动添加”和“把标记当普通文本”为什么不同。
5. 观察 batch 中的最后一个有效目标，确认它是 EOS；再检查补齐目标是否为 `-100`，以及是否误把标签移位了两次。

Notebook 提供 NFC、词表预算和最短切分的参考答案。验证记录：2026-10-11，Python 3.11、Tokenizers 0.22.2、Plotly 6.3.0；配套 notebook 从头运行，检查普通文本还原、特殊标记行为、保存加载、标签移位及四组词表预算。<strong>这些是 CPU 上的小型 tokenizer 实验，不包含语言模型预训练，也不复现上述论文的性能数字。</strong>

完成这些检查后，得到的就不只是一串整数，而是一套有明确文本边界、词表映射、结束协议和还原约定的数据表示。下一章会把编号接到词嵌入矩阵，继续走向模型的第一次前向计算。

返回 [课程总目录](index.md#课程路线规划)，或继续 [Chapter 5：词嵌入与输出层](chapter5_embeddings_output.md)。
