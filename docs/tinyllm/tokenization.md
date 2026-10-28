---
title: "第 4 章：文本与词元化"
description: "文字怎样变成整数编号：Unicode 与字节、BPE 的训练与编码、特殊 token 协议，以及词表大小的取舍。"
pageClass: tinyllm-course
---

# 第 4 章：文本与词元化

[课程总览](./index.md) · [上一章](./architecture-evolution.md) · [下一章](./embeddings-and-output.md)

::: tip 本章学习目标
区分字形、码点、字节与 token 四种长度；手推几步 BPE 合并；训练一个能还原原文的小分词器，并说明特殊 token、补齐与训练标签怎样配合。

**前置：** Python 字符串、列表和字典；[第 1 章](./first-run.md)的字符级编号。

**实践方式：** [tokenization.ipynb](/tinyllm/notebooks/tokenization)（也可以直接运行 <a href="/tinyllm/code/tokenization.py" download>tokenization.py</a>），内置小语料，CPU 即可，不下载模型或数据集。建议先读到第 6 节再运行；第 9 节的近期研究可以留到最后。
:::

[第 1 章](./first-run.md)用了最朴素的办法：唐诗语料里出现过的 556 个字，一个字一个号，“床前明月光”变成 `[169, 65, 237, 253, 45]`。这张表在唐诗上够用，可一旦换一段文字就露了底：输入里出现一个英文单词、一行 Python 代码或一个 emoji，表里根本查不到；就算都查得到，“一字一号”也让常见的词组（比如“学习”“语言模型”）每次都占好几个位置。

现在把这张手写的表换成正式的<strong>分词器（tokenizer）</strong>。它要做到三件事：任何文本都有办法表示，常见片段得到较短的表示，编号还能原样还原成文字。本章沿着“我在学习 TinyLLM。”这一句，走一遍文字怎样存储、怎样切分、怎样变成编号，以及这些编号怎样接进下一词元预测。

<TinyLLMMap active="tokenization" />

## 1. 模型收到的是一串编号

假设某个教学词表中有 `我 → 12`、`在 → 35`、`学习 → 78`，那么“我在学习”被编码成 `[12, 35, 78]`。编号的含义完全由这份词表规定：它只是行号，78 和 12 之间的大小、远近都没有语言上的意义。

接下来，模型按编号去词嵌入矩阵里取对应的行：

$$
\text{文本}\ \longrightarrow\ (t_1,\ldots,t_n)\ \longrightarrow\ (E[t_1],\ldots,E[t_n]).
$$

若词表有 $V$ 个条目、每个向量有 $d$ 个分量，$E$ 的形状就是 $[V,d]$。<strong>Tokenizer 决定“哪个片段对应哪一行”，模型训练决定“这一行的向量是什么”。</strong>后者在 [第 5 章：词嵌入与输出层](embeddings-and-output.md) 展开。

| 名称 | 含义 | 一个可能的例子 |
| --- | --- | --- |
| token（词元） | 分词器选出的单位，可以是词、字、字节片段或特殊标记 | `学习`，也可能被拆得更细 |
| vocabulary（词表） | token 与整数 ID 的对应关系 | `学习 → 78` |
| tokenizer（分词器） | 包括预处理、切分、编号与解码规则的完整工具 | 按固定配置把文本转换成 ID 序列 |

本章的编号只属于本章的小词表。两个词表即使大小相同，ID 含义也各不相同，所以模型必须和训练它时用的那套 tokenizer 配对使用。

## 2. 先量长度：一个“字”有多长

### 从 Unicode 码点到 UTF-8 字节

要决定怎样切分，先得知道文字在计算机里是什么。Python 的 `str` 表示 Unicode 文本，基本单位是<strong>码点</strong>；屏幕上看起来的“一个字”叫字形，它可能由几个码点组成。UTF-8 再把每个码点编码成 1～4 个<strong>字节</strong>，每个字节是 0～255 之间的整数。`len(text)` 数码点，`len(text.encode("utf-8"))` 数字节。[Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/tokenization.py" download>tokenization.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/tokenization.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python tokenization.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/tokenization)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/tokenization.ipynb)。
:::

先猜一猜：`猫`、`é`、`👩‍💻` 各有几个码点、几个字节？

<<< @/public/tinyllm/code/tokenization.py#unicode-lengths

![五个样例的码点数与 UTF-8 字节数：A 是 1 个码点 1 个字节，猫是 1 个码点 3 个字节（E7 8C AB），é 是 1 个码点 2 个字节，e 加组合重音是 2 个码点 3 个字节，👩‍💻 是 3 个码点 11 个字节](/tinyllm/figures/utf8-lengths.svg)

从左往右读这张图：每一列是一个看起来“只有一个字”的样例，下面依次展开它的码点和字节。ASCII 字母最省，一码点一字节；常用汉字占 3 个字节；`é` 有两种写法，单个预组合码点占 2 字节，`e` 加组合重音则是 2 个码点、3 个字节；`👩‍💻` 由“女人”、零宽连接符和“电脑”三个码点拼成，共 11 个字节，却通常显示为一个 emoji。

所以同一份文本有<strong>字形数、码点数、字节数和 token 数四种长度</strong>。前三种由 Unicode 和 UTF-8 决定，最后一种由具体的 tokenizer 决定，这正是本章要构造的东西。

### 规范化会改变什么

规范化（normalization）把某些等价写法统一起来。NFC 把 `e` 加组合重音合成 `é`；NFKC 还会统一一些兼容形式，例如全角字符。小写化、去除重音、合并空白也是常见处理，它们会丢掉原始写法的信息。

所以要提前定下解码的承诺：还原<strong>原文</strong>，还是还原<strong>规范化后的文本</strong>？编码前把 `Hello` 变成 `hello`，解码器就再也无从知道原来的 H 是大写。本章不配置规范化器，也不自动添加开头空格，这样普通文本的往返还原最容易检查。

空格同样承载内容：Python 代码的缩进、Markdown 的换行、数字之间的分隔都有用。编码前请保留原样，别为了让示例整洁就无条件调用 `strip()` 或 `" ".join(text.split())`。

## 3. 从字节到子词：BPE 怎样学合并

选什么作为切分的起始单位？四种做法各有取舍：

| 起始单位 | 好处 | 需要面对的问题 |
| --- | --- | --- |
| 整个词 | 常见词的序列短、直观 | 新词和词边界处理；中文没有空格可依 |
| Unicode 码点 | 容易理解字符边界 | 大字符集、未覆盖字符、长序列（第 1 章就是这种） |
| 字节 | 256 个基础值即可表示任何有效 UTF-8 文本 | 多字节字符会被拆开，序列较长 |
| 子词或字节合并片段 | 常见片段获得更短表示 | 需要训练语料、词表预算和确定的编码规则 |

子词方法折中两端：常见片段合在一起，罕见部分拆开，片段只看统计频率，未必对应语言学上的词根。<strong>Byte-level BPE 从 256 个字节出发学习合并</strong>，所以任何文本都能表示；代价是一个 token 有时只是某个汉字的一部分字节。

### BPE 训练：反复合并最常见的相邻对

Byte Pair Encoding，简称 BPE。先用只有 ASCII 字母的小语料看清机制：`abab` 出现 3 次、`abac` 出现 2 次、`ad` 出现 1 次。初始单位是单个字母，统计相邻对时要乘上每条样本的出现次数。先猜：第一步会合并哪一对？

<<< @/public/tinyllm/code/tokenization.py#bpe-merges

![BPE 在语料 abab×3、abac×2、ad×1 上的两步合并：第 1 步 a+b 的加权次数为 8，合并成 ab；第 2 步 ab+ab 的次数为 3，合并成 abab](/tinyllm/figures/bpe-merges.svg)

图从上往下是两轮“统计—合并”。第 1 步，`a b` 在 `abab` 里出现两次（×3 = 6），在 `abac` 里出现一次（×2 = 2），合计 8，是最高的一对，于是三条样本里的 `a b` 都变成 `ab`。第 2 步在合并后的序列上重新统计，只有 `abab` 里出现 `ab ab`，次数为 3，合并成 `abab`。训练器就这样持续更新统计，直到用完词表预算或没有符合条件的候选。每一步学到的合并按顺序记下来，就是这个 BPE 模型的全部“知识”。

这段代码只演示合并本身；第 4 节交给库去处理字节映射、预切分和保存。

### BPE 编码：按学到的顺序处理新文本

训练结束后，编码一篇新文章时会照搬已经学到的<strong>合并优先级</strong>（merge rank），而不会重新统计新文章里的高频对。假设先学到 `b + c → bc`、后学到 `a + b → ab`，新文本 `abc` 按优先级得到 `a | bc`；如果改用“从左边贪心匹配最长词表项”，可能得到 `ab | c`。两种算法给出不同的切分，同一个模型应始终用训练时的那一种。[Hugging Face BPE 教程](https://huggingface.co/learn/llm-course/en/chapter6/5)

BPE 的合并通常发生在预切分器划出的边界之内。先按单词切开再训练，就学不到跨越这些边界的短语；第 9 节的 SuperBPE 改的正是这一点。

### SentencePiece、Unigram 和 BPE 的关系

BPE 是算法，SentencePiece 是工具：SentencePiece 既可以训练 BPE，也可以训练 Unigram；它直接读取原始句子，用 `▁` 表示空白，默认规范化涉及 NFKC，使用时要核对规范化配置与还原要求。[SentencePiece 官方说明](https://github.com/google/sentencepiece)

Unigram 从一大批候选片段及其概率出发，逐步删减出词表，编码时选概率较高的切分路径；BPE 保存的是合并过程。WordPiece 是另一种常见子词方法，训练与编码规则各有不同。本章专注把一套 BPE 流程走通。[Tokenizers 模型组件](https://huggingface.co/docs/tokenizers/components)

## 4. 训练一个能还原原文的分词器

### 先看流水线，再调用 API

一个 tokenizer 是一条流水线：<strong>规范化 → 预切分 → BPE 等模型切分并映射 ID → 添加特殊 token</strong>。解码时根据 ID 找回片段，再按解码规则拼回文本。规范化、预切分和后处理都属于配置，需要和词表一起保存。[Tokenizers 流水线](https://huggingface.co/docs/tokenizers/pipeline)

本章固定使用 `tokenizers==0.23.3`，以保证 API 一致（它未必是资料核对日的最新版本）；Plotly 图表用 `plotly==7.1.0`。在 Python 3.10 及以上环境中安装：

```sh
python -m pip install tokenizers==0.23.3 plotly==7.1.0
```

下面是专门编写的教学训练集，混合了中文、英文、代码、数字和 emoji。后面用来测量的句子另行列出，<strong>不参与训练词表</strong>。真实项目也是先划分训练、验证和测试数据，再只用训练部分拟合 tokenizer。

<<< @/public/tinyllm/code/tokenization.py#train-tokenizer

几个参数的含义：

- `initial_alphabet` 保留全部 256 个字节对应的基础符号，所以没见过的有效 UTF-8 文本也有表示路径，这是相对第 1 章字符表的关键改进。
- `min_frequency=2`：出现次数低于 2 的候选对不再合并。
- `vocab_size` 是目标预算；语料很小时，实际大小可能达不到它。特殊 token 也占词表位置，本例至少需要 256 + 4 个位置。
- `ByteLevel` 把字节映射成可显示的符号再交给 BPE，它自带预切分规则，合并发生在这些片段之内。`add_prefix_space=False` 让它不在输入开头自动补空格。

训练器与保存 API 的用法可对照 [Tokenizers 官方入门](https://huggingface.co/docs/tokenizers/quicktour)。

### 观察切分，同时检查还原

<<< @/public/tinyllm/code/tokenization.py#encode-roundtrip

打印出的 token 里可能有 `Ġ` 之类的符号，看起来像乱码：这是字节映射的显示形式，`Ġ` 代表一个空格字节。`offsets` 给出每个 token 对应的原文区间；一个汉字被拆成几个字节片段时，这几个片段的区间会重叠在同一个字上。

两条与解码有关的事实值得记住：

- <strong>整段解码</strong>才是还原原文的标准做法。单个 token 可能只含某个 UTF-8 字符的一部分，逐 token 解码再拼接会在字符中间断开、显示出替换符 `�`。生成时要逐步显示文本，就用能缓冲不完整字节的流式解码。
- 往返检查覆盖的是“正常 Unicode 文本编码得到的完整序列”。随手拼出的 ID 序列，或在字符中间截断的序列，未必能组成有效 UTF-8。

## 5. 特殊 token：给序列加上结构

普通 token 表示文本片段；特殊 token 为序列提供结构。常见的有 BOS（开始）、EOS（结束）、PAD（补齐）和 UNK（无法表示的输入）。这些名称和用途由各模型自己约定：有的模型不用 BOS，有的区分“一条消息结束”和“整轮对话结束”。

把 `<bos>`、`<eos>` 注册进词表只是给它们分配了 ID；什么时候插入它们，由<strong>后处理模板</strong>决定。本例显式设置模板：

<<< @/public/tinyllm/code/tokenization.py#special-template

`decode` 默认跳过特殊 token，所以用户看不到 BOS/EOS。再看一个边界情况：普通输入里恰好写了字面量 `<eos>`，库会把它识别成已注册的特殊 token，默认解码随之把它跳过：

<<< @/public/tinyllm/code/tokenization.py#literal-eos

可见“原文可逆”带有条件。`add_special_tokens=False` 关闭的只是模板插入；用户文本中的保留标记怎样处理，需要产品自己定下转义或普通文本编码策略，并把用户字符串当作不可信输入对待。

对话模型还需要 <strong>chat template</strong>：把角色、内容、消息分隔和生成起点序列化成训练时的格式。使用预训练模型时，模板随模型一起加载，`apply_chat_template(tokenize=True)` 可以直接得到 ID；若先生成模板字符串再单独编码，要检查有没有重复插入 BOS/EOS。各模型的角色标记各有约定，按名字互换会出错。[Transformers 对话模板说明](https://huggingface.co/docs/transformers/chat_templating)

## 6. 把 ID 序列接到“预测下一个词元”

一条样本经过模板得到 `[BOS, 我, 在, 学习, EOS]`。和第 1 章一样，下一词元任务把输入与目标错开一位：

| 位置 | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| 模型输入 | BOS | 我 | 在 | 学习 |
| 预测目标 | 我 | 在 | 学习 | EOS |

真实训练按 batch 处理，长短不一的样本要先补齐。下面只用列表构造数据，不需要 PyTorch：

<<< @/public/tinyllm/code/tokenization.py#label-shift

![两条补齐到相同长度的样本：input_ids 取前 n-1 个位置，labels 取后 n-1 个位置；attention_mask 有效位置为 1、补齐位置为 0；补齐位置的标签记为 -100，EOS 保留为目标](/tinyllm/figures/label-shift.svg)

图中用简化的 token 展示两条样本：短的 `[<bos> 猫 <eos> <pad>…]` 和长的 `[<bos> 我 在 学习 。 <eos>]`。先看上下两行的错位：`input_ids` 取每行前 n-1 个，`labels` 取后 n-1 个，于是每一列都是“看到这个，预测下一个”。再看短样本的尾部：补齐位置的 `attention_mask` 是 0，标签被换成 `-100`；而 `<eos>` 仍是一个正常的目标，模型要学会在该结束时预测结束。

这里出现了三种“遮住”，各管一件事：

- <strong>padding attention mask</strong> 告诉注意力哪些位置是补齐的；本例 1 表示有效、0 表示补齐。
- <strong>causal mask</strong> 让每个位置只看自己和之前的位置，在注意力层里构造（[第 6 章](self-attention.md)），本段代码没有实现。
- <strong>loss mask</strong> 决定哪些目标参与损失。本例用 `-100` 表示忽略，后续损失函数要设同样的 `ignore_index`。

当 PAD 与 EOS 共用同一个 ID 时，按 `label == pad_id` 删除目标会把 EOS 一起删掉；应按真实长度或补齐掩码判断，像上面的代码那样。

本例是<strong>手动移位</strong>的教学实现。有些模型接口会在内部移位，这时应按接口要求提供未移位的标签，避免错开两次。拼接多篇文档时，还要决定后一篇能否关注前一篇：插入 EOS 只是标出边界，注意力隔离需要另外的掩码。这些在 [第 13 章](data-pipeline.md) 和 [第 14 章](language-model-loss.md) 继续展开。

## 7. 保存整套规则，测量词表预算

### 保存、加载与模型兼容性

<<< @/public/tinyllm/code/tokenization.py#save-load

`TemporaryDirectory` 在实验后清理文件；实际训练时把 `tokenizer.json` 保存在检查点目录，同时记录训练语料版本、库版本和训练参数。用对话模板时还要另存模板及相关配置，因为这份底层 Tokenizers JSON 只含分词流水线，chat template 属于 Transformers 层。

tokenizer 和嵌入权重是一对：重新训练 tokenizer 后，旧 ID 的含义可能全变了；增加词表条目要同步扩展输入/输出层并学习新权重；即使词表固定、只更换切分算法，输入序列的分布也会改变，需要重新评估。

### 测量词表大小与序列长度

下面固定训练文本、预切分和频次阈值，只改变词表预算。测量用四段未参与训练的文本；这是观察机制的小实验，用来看趋势，而非给语言或代码能力排名。

<<< @/public/tinyllm/code/tokenization.py#budget-sweep

先预测：预算从 260 加到 384，四段文本的 token 数会怎样变？实际词表会不会正好是 384？本章固定环境下的实测如下，每个领域对应上面的一条留出文本，不含 BOS/EOS：

| 目标词表大小 | 实际大小 | 中文 token 数 | 英文 token 数 | 代码 token 数 | 数字与 emoji token 数 |
| --- | --- | --- | --- | --- | --- |
| 260 | 260 | 66 | 57 | 33 | 34 |
| 288 | 288 | 60 | 45 | 31 | 34 |
| 320 | 320 | 56 | 41 | 26 | 33 |
| 384 | 337 | 53 | 40 | 25 | 33 |

预算为 260 时，全部位置都被 256 个基础字节和 4 个特殊 token 占满，还没有任何合并，所以每个字节就是一个 token。预算加大后，合并逐渐出现，各领域的 token 数下降。预算设为 384 时实际只得到 337 个条目，因为剩下的候选达不到频次阈值。Notebook 用 Plotly 画出这些变化。读这类表时，先看“大词表是否真的达到预算”，再比较<strong>同一份文本</strong>在不同预算下的变化；各领域原文长度不同，按 token 总数横向比较语言没有意义。

除了 token 数，还可以同时记录下面这些指标，并注明是否包含 BOS/EOS 等结构 token：

| 指标 | 计算方法或观察点 | 能说明什么 |
| --- | --- | --- |
| token 数 | 同一份原文编码后的长度 | 序列长度与上下文占用 |
| bytes/token | 原文 UTF-8 字节数 ÷ 普通 token 数 | 同一数据集上的压缩效率，越高表示序列越短 |
| tokens/码点 | token 数 ÷ Python `len(text)` | 文本切得多碎；不同语言每个码点承载的信息量各异 |
| 实际词表大小 | `get_vocab_size()` | 实际用了多少词表位置，而非配置预算 |
| 往返一致性 | `decode(encode(text)) == text` | 约定范围内是否保留原始文本 |
| 实际出现的词表比例 | 测量语料中用过的普通 ID 数 ÷ 普通词表大小 | 该数据集上的利用情况；小样本里没出现的 token 未必无用 |

数字和代码还要单独看切分边界。`123456` 切成 `123 | 456` 还是 `12 | 345 | 6`，除了 token 数不同，数字的三位分组也不同；代码中的换行、缩进和标点同样有结构作用。可以把每个 token 解码后连同 ID、起止位置一起检查，但字节级片段可能落在多字节字符中间，最终以整段解码与原文的比较为准。[TokEval](https://arxiv.org/abs/2608.18062) 因此把 UTF-8 字符边界、数字位值边界和代码结构纳入评价，而不只看压缩率。

## 8. 怎样公平地比较两个分词器

token 少了，好处是明确的：同一段原文占用更少上下文位置，注意力计算和 KV cache 的开销也随之改变。代价在另一端：词表越大，嵌入层和输出层越大。以共享输入输出权重的简单情况为例，向量维数固定为 768，词表从 32,000 扩到 128,000，仅这张矩阵就增加

$$
(128000-32000)\times768=73{,}728{,}000
$$

个参数；输入输出不共享时还要算两张矩阵。序列节省、词表层开销、编码速度和任务质量要合起来评估。

困惑度（perplexity，PPL）也要小心读。它通常按 token 平均负对数似然再取指数，tokenizer 一换，“平均到每个什么”也就换了，两个 PPL 的单位随之不同。跨 tokenizer 比较时，可以在相同原文和评分协议下改用<strong>按 UTF-8 字节归一化</strong>的负对数似然；它仍然只衡量语言建模，回答问题的正确率要另测；BOS/EOS、文本边界及规范化处理也要保持一致。

“训练相同数量的 token”同样未必公平：压缩更好的 tokenizer 让模型在同样的 token 数里看到了更多原始文本。做研究比较时，要写明固定的是文本量、token 数、参数量、计算量还是时间。

## 9. 近期研究在改变哪些环节

资料核对日期：<strong>2026-10-11</strong>。下面几项工作可以围绕三个问题阅读：<strong>边界能否跨越、词表怎样构造、效果怎样验证</strong>。它们是理解方向的地图，论文结果与本章实测分别标明。

| 工作 | 改变的环节 | 要点 |
| --- | --- | --- |
| [SuperBPE（COLM 2025，2025-08-26 修订版）](https://arxiv.org/abs/2503.13423v3) | 边界 | 先学子词，再允许合并跨越空格，形成多词单位；论文在 200K 词表下报告最多约 33% 的 token 数减少，并从头训练模型比较下游表现。收益来自词表学习过程本身，需要连同模型一起重新训练。 |
| [CNF-MCE（2026-10-01，预印本）](https://arxiv.org/abs/2610.01127) | 词表构建与编码路径 | CNF 统计候选片段并按实际使用筛选词表，MCE 用动态规划最小化切分成本（“最优”针对其定义的成本函数）。固定 qwen250k 词表时，英文网页实验每千字符 token 数从 BPE 的 222.5 降到 MCE 的 221.6；更换整套词表的压缩收益是另一项实验。[固定词表结果](https://arxiv.org/html/2610.01127#S4.SS5) |
| [TokSuite（ICML 2026）](https://proceedings.mlr.press/v306/altintas26a.html) | 下游评价 | 控制实验比较 14 个用不同 tokenizer 预训练的模型，考察多种语言与输入扰动（错别字、空白变化等）下的行为。压缩表格提供线索，任务表现要靠模型评估回答。 |
| [TokEval（COLM 2026）](https://arxiv.org/abs/2608.18062) | 切分结构 | 评价 UTF-8 字符边界是否完整、数字是否沿位值边界切分等；作者从头训练只改 tokenizer 的模型，用按字节归一化的损失和任务表现检验这些指标，发现不同内在指标与不同任务能力的关联程度不一样。 |

<strong>全局选择与从左最长匹配。</strong>为理解 MCE 的思想，看一个<strong>自造的小例子</strong>：词表包含每个单字母，以及 `ab`、`abc`、`cdef`。编码 `abcdef` 时，从左选最长项得到 `abc | d | e | f`（4 个），最少词元的路径则是 `ab | cdef`（2 个）。Notebook 用单位成本的动态规划实现这个例子；它没有论文中的边界惩罚、候选生成与训练过程，只用来解释思想，并非 CNF-MCE 的复现。

<strong>延伸阅读：BLT。</strong>[Byte Latent Transformer（BLT，2024 年提出）](https://arxiv.org/abs/2412.09871) 是更早的另一条路线：直接从字节出发，动态组织成 patch，并在不同层级分配计算。它改变的是模型架构与训练方式，远比把 BPE 换成 `text.encode("utf-8")` 复杂。

对 TinyLLM，合理的实验顺序是：先检查文本可逆性，再记录字符、数字与换行的切分边界，比较同一文本上的 token 数和编码耗时，最后接上模型，在相同原文与预算下测量损失、任务质量、延迟及显存。字节级 token 跨越字符边界本身可以接受，关键是这种行为能被测量和解释。Agent 把旧信息放回提示词后，这些文本同样经过这个 tokenizer；较短的序列可能降低 [第 25 章的 KV cache](inference-efficiency.md) 占用，而 Agent 是否找对记忆属于 [第 31 章](agent-memory.md) 的另一项评测。

## 10. 动手检查与练习

先预测结果，再运行 [tokenization.ipynb](/tinyllm/notebooks/tokenization)：

1. `é` 与 `e\u0301` 看起来相近，为什么码点数和字节数不同？添加 NFC 后，应该断言还原原文，还是还原 NFC 后的文本？
2. 只用英文语料训练，再编码从未出现过的汉字；为什么保留 256 个基础字节就能避免 UNK，而这个汉字却可能占好几个 token？
3. 把词表预算调到 1,000，检查实际词表大小。如果没达到预算，是库出错了，还是频次阈值与语料量限制了合并？
4. 文本中直接写入 `<eos>`，比较默认解码与 `skip_special_tokens=False`。解释“关闭自动添加”和“把标记当普通文本”有什么区别。
5. 观察 batch 中的最后一个有效目标，确认它是 EOS；再检查补齐目标是否为 `-100`，以及标签有没有被移位两次。

Notebook 提供 NFC、词表预算和最短切分的参考答案。验证记录：2026-10-27，Python 3.10、Tokenizers 0.23.3、Plotly 7.1.0；配套脚本从头运行，检查普通文本还原、特殊标记行为、保存加载、标签移位及四组词表预算。这些是 CPU 上的小型 tokenizer 实验，不含语言模型预训练，也不复现上述论文的性能数字。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>从零训练时用可逆的字节级 BPE，并保存完整的规范化、预切分、合并规则和特殊 token 配置。</strong>

理由：256 个基础字节保证任何文本都有表示路径，第 1 章“查不到字”的问题不再出现；BPE 让常见片段变短；整段解码能原样还原原文，便于检查。要记住它的代价：中文字的部分字节也可能成为独立 token，“可逆”只保证能还原，切分是否贴合语义是另一回事。

什么时候改：词表大小按中文/英文/代码比例、序列长度与训练预算比较后再定；复现或微调已有模型时，必须使用它原来的 tokenizer，训练开始后也要保持 tokenizer 固定。

::: warning 常见误区
- **“一个汉字 = 一个 token”只是特例。** 字形、码点、字节、token 是四种长度；字节级 BPE 下一个汉字可能占 1 到 3 个 token。
- **注册了 `<eos>`，编码时未必自动加上。** 插入与否由后处理模板决定；`add_special_tokens=False` 也只是关闭模板，用户文本里的字面量 `<eos>` 仍可能被识别成特殊 token。
- **逐 token 解码再拼接，会在字符中间断开。** 看到 `�` 通常是半个 UTF-8 字符，并非词表损坏；以整段解码为准。
- **`-100` 是损失的忽略标签，词表里没有这个 ID。** PAD 与 EOS 共用 ID 时，按掩码而非 `label == pad_id` 屏蔽，否则 EOS 目标会被一起删掉。
- **PPL 只能在同一个 tokenizer 下比较。** 跨 tokenizer 时改用按字节归一化的负对数似然，并保持相同原文和评分协议。
:::

## 检查理解

1. `猫` 有几个码点、几个 UTF-8 字节？在只有 256 个基础字节、还没学到任何合并的词表里，它占几个 token？

   <details><summary>参考答案</summary>

   1 个码点、3 个字节（E7 8C AB）；没有合并时每个字节一个 token，所以占 3 个 token。

   </details>

2. 在语料 `abab`×3、`abac`×2、`ad`×1 上，为什么 BPE 第一步合并 `a + b`，次数是 8？

   <details><summary>参考答案</summary>

   `a b` 在 `abab` 中出现 2 次（×3 = 6），在 `abac` 中出现 1 次（×2 = 2），合计 8，高于 `b a` 的 5 和其他相邻对。

   </details>

3. 只用英文语料训练的字节级 BPE 遇到没见过的汉字，为什么不会产生 UNK？它通常占几个 token？

   <details><summary>参考答案</summary>

   词表保留了全部 256 个基础字节，任何有效 UTF-8 文本都能退回字节表示；但英文语料里没有学到该汉字字节的合并，所以它通常拆成 3 个字节 token。

   </details>

4. 样本 `[<bos>, 猫, <eos>, <pad>, <pad>, <pad>]` 按本章方式构造训练数据，`labels` 是什么？

   <details><summary>参考答案</summary>

   `labels` 取后 5 个位置：`[猫, <eos>, -100, -100, -100]`。EOS 保留为目标，三个补齐位置记为 -100。

   </details>

5. 词表预算设为 384，实际只得到 337 个条目。原因是什么？

   <details><summary>参考答案</summary>

   训练语料很小，剩余候选对的出现次数达不到 `min_frequency=2`，训练器没有更多可合并的对；这是预期行为，与库的正确性无关。

   </details>

## 参考资料

- [Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html)
- [Hugging Face LLM 课程：BPE 分词](https://huggingface.co/learn/llm-course/en/chapter6/5)
- [SentencePiece 官方说明](https://github.com/google/sentencepiece)
- [Tokenizers 官方入门](https://huggingface.co/docs/tokenizers/quicktour) · [流水线](https://huggingface.co/docs/tokenizers/pipeline) · [模型组件](https://huggingface.co/docs/tokenizers/components)
- [Transformers 对话模板说明](https://huggingface.co/docs/transformers/chat_templating)
- [SuperBPE，COLM 2025](https://arxiv.org/abs/2503.13423v3)
- [CNF-MCE，2026 预印本](https://arxiv.org/abs/2610.01127)（[固定词表结果](https://arxiv.org/html/2610.01127#S4.SS5)）
- [TokSuite，ICML 2026](https://proceedings.mlr.press/v306/altintas26a.html)
- [TokEval，COLM 2026](https://arxiv.org/abs/2608.18062)
- [Byte Latent Transformer，2024](https://arxiv.org/abs/2412.09871)

下一章把这些编号接到词嵌入矩阵，再从向量变回词表上的分数：[第 5 章：词嵌入与输出层](./embeddings-and-output.md)。
