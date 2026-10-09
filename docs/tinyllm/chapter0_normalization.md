# Chapter 0 · 归一化

本章梳理 Transformer/LLM 中有代表性的归一化技术。<strong>LayerNorm、RMSNorm、ScaleNorm、QK Norm、DeepNorm 都是本章的正式主题</strong>。它们解决的问题并不完全相同：有的处理每个 token 的隐藏向量，有的处理注意力中的 query/key，有的调整残差路径。因此应平等学习、按作用位置比较，而不能简单地用一张“谁更先进”的排行榜代替分析。

本章包含理论、PyTorch API 调用示例，以及可逐格运行的 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a>。notebook 既有固定数据实验，也有五种方法的教学版实现；每段代码后都解释如何阅读结果。

## 学习目标

1. 对形状为 `[batch, seq_len, hidden_size]` 的隐藏状态，说清楚归一化沿哪个维度进行。
2. 能写出 LayerNorm、RMSNorm、ScaleNorm 的公式，解释它们如何改变均值和尺度。
3. 能说明 QK Norm 改变注意力的哪个环节，以及 DeepNorm 如何处理深层残差块。
4. 区分归一化<strong>方法</strong>、归一化<strong>位置</strong>与归一化<strong>替代方案</strong>。

## 配合阅读的交互演示

这些网页可以直接在浏览器里操作。它们用于建立直觉；本章公式与 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a> 才是核对具体数值和 PyTorch 实现的依据。

| 演示                                                                                                                      | 建议怎样看                                                                                    | 对应本章                    |
| ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------- |
| [Layer Normalization & RMSNorm 交互演示](https://continuousfunction.ai/domains/attention-transformers/layer-normalization/) | 改动输入向量，观察“先减均值”与“直接按均方根缩放”如何改变输出；特别试试所有分量同时加一个常数。                                        | 第 1、2 节及 notebook 的平移实验 |
| [Transformer Explainer](https://poloclub.github.io/transformer-explainer/)                                              | 沿着一个 token 的计算路径找到归一化与注意力模块的位置，先建立整体结构印象。该工具展示的是 GPT-2 架构，不代表所有现代模型都采用同一种归一化。            | 第 7 节的 Block 位置图        |
| [Transformer Attention Playground](https://www.rugvailabs.com/play/transformer)                                         | 观察 Q/K 点积、softmax 和加权 V 的变化，再回到第 4 节理解为什么要在点积前控制 Q/K 的尺度。它演示注意力计算，并不直接实现本章所有 QK Norm 变体。 | 第 4 节 QK Norm           |

建议顺序：先看 LayerNorm/RMSNorm 的向量变化，再在 Transformer Explainer 中定位模块，最后看 Q/K 如何影响 softmax。网页交互会随网站更新；如果页面无法访问，notebook 中的固定数据实验仍可独立运行。

## 统一符号与总览

设一个 token 的隐藏向量为 $x=(x_1,\ldots,x_d)$。$d$ 是隐藏维度，$\epsilon>0$ 用来避免除以零。$\gamma$ 表示逐元素可学习缩放，$\beta$ 表示逐元素可学习平移。以下默认对单个 token 的最后一维计算统计量，不跨 batch 或 token 求平均；QK Norm 则在注意力头的维度上处理 query/key。

| 技术                                                 | 核心操作              | 主要作用位置          | 关注的问题      | 与其他方法的关系                 |
| -------------------------------------------------- | ----------------- | --------------- | ---------- | ------------------------ |
| [LayerNorm](chapter0_normalization.md#_1-layernorm) | 减均值，再除以标准差        | 隐藏状态            | 居中和控制尺度    | 可用于 Pre-Norm 或 Post-Norm |
| [RMSNorm](chapter0_normalization.md#_2-rmsnorm)     | 除以均方根，不减均值        | 隐藏状态            | 控制尺度       | 可用于 Pre-Norm 或 Post-Norm |
| [ScaleNorm](chapter0_normalization.md#_3-scalenorm) | 除以向量的 L2 范数，再乘标量  | 隐藏状态            | 控制向量长度     | 是另一种隐藏状态归一化              |
| [QK Norm](chapter0_normalization.md#_4-qk-norm)     | 分别归一化 query 与 key | 注意力内部           | 控制注意力分数的尺度 | 可与上述隐藏状态归一化共存            |
| [DeepNorm](chapter0_normalization.md#_5-deepnorm)   | 调整残差分支、归一化与初始化    | Transformer 残差块 | 极深网络的训练稳定性 | 是结构方案，并非单个归一化层的替代品       |

这张表中的“同等地位”指<strong>教学覆盖程度相同</strong>，并不表示五种技术在模型中能互相替换。例如，使用 RMSNorm 的模型仍可在注意力中加入 QK Norm。

### 哪些架构用过这些方法？

| 方法        | 有明确资料支持的架构或模型                                                                                                                                                                                                                                        | 需要注意的边界                                                          |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| LayerNorm | [原始 Transformer](https://arxiv.org/abs/1706.03762)、[BERT](https://arxiv.org/abs/1810.04805)、[GPT-2](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf)、[GPT-3](https://arxiv.org/abs/2005.14165) | 这些模型的归一化放置位置不完全相同；GPT-3 沿用 GPT-2 风格的预归一化。                        |
| RMSNorm   | [LLaMA](https://arxiv.org/abs/2302.13971)、[Gemma 2](https://arxiv.org/abs/2408.00118)、[Qwen3](https://arxiv.org/abs/2505.09388)                                                                                                                      | Gemma 2 在子层前后使用 RMSNorm；Qwen3 同时还在注意力中使用 QK Norm。                |
| ScaleNorm | [Transformers without Tears](https://arxiv.org/abs/1910.05895) 的机器翻译 Transformer，覆盖 IWSLT/TED 低资源语种对和 WMT'14 英德实验                                                                                                                                    | 有明确的研究架构和实验，但不宜把它写成 LLaMA、GPT-3 等主流 LLM 的已确认组件。                  |
| QK Norm   | [原始 QKNorm 论文](https://aclanthology.org/2020.findings-emnlp.379/) 的机器翻译 Transformer；[OLMo 2/3、Qwen 3、Gemma 3、Marin 32B](https://allenai.org/papers/olmpool)                                                                                          | 原论文采用逐头 L2 归一化；现代 LLM 常用 RMSNorm，且有整层投影与逐头两种粒度。名称相近不代表公式完全相同。    |
| DeepNorm  | [DeepNet](https://arxiv.org/abs/2203.00555) 的极深 Transformer，包括论文中的 200 层多语言翻译模型和最高 1000 层的实验架构                                                                                                                                                       | DeepNorm 是 DeepNet 提出的残差与初始化方案；不能据此说 BERT、GPT 或 LLaMA 的原始架构采用了它。 |

<strong>读表原则：</strong>“论文在某种 Transformer 上验证过”与“某个知名预训练模型正式采用”是不同证据。上表对 ScaleNorm、DeepNorm 使用论文中的研究架构，对 LayerNorm、RMSNorm、QK Norm 列出可核对的公开模型；不把技术名称相似的实现强行视为同一种公式。

## 1. LayerNorm

<strong>做法。</strong>先计算隐藏向量的均值和方差，再居中、缩放，并应用可学习参数：

$$
\mu=\frac{1}{d}\sum_{i=1}^{d}x_i,\qquad
\sigma^2=\frac{1}{d}\sum_{i=1}^{d}(x_i-\mu)^2
$$

$$
y_i=\gamma_i\frac{x_i-\mu}{\sqrt{\sigma^2+\epsilon}}+\beta_i
$$

<strong>参数中文说明。</strong>$x_i$ 是第 $i$ 个隐藏特征，$d$ 是隐藏维度；$\mu$ 是该 token 的均值，$\sigma^2$ 是方差；$\epsilon$ 防止分母为零；$\gamma_i$ 和 $\beta_i$ 分别是第 $i$ 维可学习的缩放与平移参数，输出为 $y_i$。

<strong>PyTorch 调用。</strong>假设 `x` 的形状为 `[batch, seq, d]`：

```python
layer_norm = nn.LayerNorm(
    normalized_shape=d,       # 只归一化最后一维，长度为 d
    eps=1e-5,                # 加在方差上，避免分母为零
    elementwise_affine=True, # 学习逐维 weight（gamma）和可选 bias（beta）
    bias=True,               # 学习逐维平移；False 时仍可保留 weight
)
y = layer_norm(x)            # 输出形状仍为 [batch, seq, d]
```

`elementwise_affine=False` 会同时关闭 `weight` 与 `bias`；默认二者各有 `d` 个参数。参见 [PyTorch LayerNorm 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html)。

<strong>作用位置。</strong>常用于 Transformer 子层前或残差相加后；这是 Pre-Norm / Post-Norm 的选择。

<strong>目的与取舍。</strong>输出在应用 $\gamma,\beta$ 前均值为零、方差接近一。对所有分量同时加同一个常数时，居中步骤会消除这个偏移。它需要计算均值和方差；实际运行速度取决于内核和硬件，不能只凭算术步骤断言性能。

<strong>代表性应用。</strong>原始 Transformer、BERT、GPT-2 和 GPT-3 使用了 LayerNorm 或其放置方式的变体。GPT-3 不应列在 RMSNorm 代表模型中。

## 2. RMSNorm

<strong>做法。</strong>不减均值，只用输入平方的平均值计算均方根：

$$
\mathrm{RMS}(x)=\sqrt{\frac{1}{d}\sum_{i=1}^{d}x_i^2+\epsilon},\qquad
y_i=\gamma_i\frac{x_i}{\mathrm{RMS}(x)}
$$

<strong>参数中文说明。</strong>$x_i$ 和 $d$ 分别是第 $i$ 个隐藏特征和隐藏维度；$\mathrm{RMS}(x)$ 是该 token 各维平方的平均值再开方；$\epsilon$ 防止全零向量导致除零；$\gamma_i$ 是第 $i$ 维可学习缩放参数。标准形式没有 $\beta_i$ 平移项。

<strong>PyTorch 调用。</strong>输入 `x` 的形状同样为 `[batch, seq, d]`：

```python
rms_norm = nn.RMSNorm(
    normalized_shape=d,       # 沿最后一维计算 RMS
    eps=1e-5,                # 加在平方均值上，避免分母为零
    elementwise_affine=True, # 学习逐维 weight（gamma），不创建 bias
)
y = rms_norm(x)              # 输出形状仍为 [batch, seq, d]
```

`elementwise_affine=False` 会关闭 `weight`。`eps` 默认是 `None`，PyTorch 按内部计算类型（opmath dtype）的 machine epsilon 选取；官方文档说明 FP16/BF16 输入在此采用 FP32 的 epsilon。这里显式写 `1e-5` 便于比较。参见 [PyTorch RMSNorm 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.RMSNorm.html)。

<strong>作用位置。</strong>和 LayerNorm 一样，可放在注意力或前馈子层的输入、输出附近；具体模型代码仍应逐一核对。

<strong>目的与取舍。</strong>控制向量尺度，保留均值信息；输出通常不以零为中心。省去居中与方差计算，但不能据此保证任意实现都更快。RMSNorm 论文在其测试的模型和实现中报告约 7%–64% 的速度提升，这不是通用硬件指标。FP16/BF16 的稳定性仍取决于累加精度、$\epsilon$ 和内核。

<strong>代表性应用。</strong>LLaMA 系列使用 Pre-Norm + RMSNorm；Gemma 2 同时在子层前后使用 RMSNorm。

### LayerNorm 与 RMSNorm 的并行计算差别

<strong>两者都可以高度并行</strong>：不同 token 的隐藏向量彼此独立，同一向量内的求和也可做并行归约（reduction）。差别主要在每个向量内部所需的统计量与运算依赖：

* <strong>LayerNorm</strong> 要得到均值，再计算围绕均值的方差（或用等价的统计量计算方式），随后居中、缩放。它涉及均值相关的额外运算和依赖，因此算子实现通常更复杂。
* <strong>RMSNorm</strong> 直接对输入的平方求平均并开方，不做减均值和中心化方差。它少了一套均值相关的运算与数据依赖，通常有机会减少计算、数据读写和归约同步开销。

这解释了 RMSNorm <strong>可能更省</strong>的来源，而不是说 LayerNorm 无法并行，也不是保证 RMSNorm 在所有设备上都更快。融合内核、输入形状、dtype 和硬件会决定实际开销；上面提到的论文速度结果只适用于其测试设置。参见 [RMSNorm 原论文](https://arxiv.org/abs/1910.07467)。

## 3. ScaleNorm

<strong>做法。</strong>用向量的 L2 范数归一化，再乘可学习标量 $g$：

$$
\|x\|_2=\sqrt{\sum_{i=1}^{d}x_i^2},\qquad
y=g\frac{x}{\|x\|_2+\epsilon}
$$

<strong>参数中文说明。</strong>$x$ 是一个 token 的完整隐藏向量；$|x|_2$ 是它的 L2 长度，即各维平方求和再开方；$g$ 是一个可学习标量，用来决定输出向量的目标长度；$\epsilon$ 防止零向量除零。与逐维的 $\gamma_i$ 不同，一个 ScaleNorm 层通常只有一个 $g$。

<strong>PyTorch 调用。</strong>PyTorch 没有同名的 `nn.ScaleNorm` 标准模块；以下代码与上面的公式一致：

```python
class ScaleNorm(nn.Module):
    def __init__(self, eps=1e-6):
        super().__init__()
        self.g = nn.Parameter(torch.tensor(1.0))  # 一个可学习标量，控制长度
        self.eps = eps                            # 防止零向量除零

    def forward(self, x):
        length = x.norm(
            p=2,          # 计算 L2 范数
            dim=-1,       # 沿隐藏维度计算
            keepdim=True, # 保留末尾长度为 1 的维度，便于广播
        )
        return self.g * x / (length + self.eps)

y = ScaleNorm()(x)            # x 和 y 都是 [batch, seq, d]
```

也可用 `F.normalize(x, p=2, dim=-1, eps=eps)` 实现近似形式，但其分母为 `max(norm, eps)`，在接近零时与上式不同。参见 [PyTorch `F.normalize` 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.normalize.html)。

<strong>作用位置。</strong>作为隐藏状态归一化，可用于 Transformer 子层周围。原论文还讨论了其他配套初始化和输出归一化设计，不能把整篇论文的效果全归因于 ScaleNorm。

<strong>目的与取舍。</strong>直接约束向量长度，形式简洁。不减均值，也不会像逐维 $\gamma$ 一样单独学习每个特征的缩放。$\epsilon$ 的放置和 $g$ 的共享方式要以具体实现为准；上式是便于教学的安全形式。

<strong>代表性研究。</strong>《Transformers without Tears》在 Transformer 实验中研究了 ScaleNorm。

## 4. QK Norm

<strong>核心问题。注意力分数（attention logits）由 Q 与 K 的点积得到。若 Q/K 的范数变大，分数可能过大或波动很大，使 softmax 过度饱和：某些 key 的权重接近 1，其余接近 0。这可能增加训练不稳定的风险。QK Norm 在点积前控制 Q/K 的尺度，专门处理注意力内部</strong>的数值；LayerNorm/RMSNorm 通常处理 Transformer 主干的 hidden state，两者可以同时使用。[原始 QKNorm 论文](https://aclanthology.org/2020.findings-emnlp.379/) 和 [OlmPool 架构研究](https://allenai.org/papers/olmpool) 分别讨论了 softmax 饱和与训练稳定性。

<strong>两种常见粒度。这里的“layerwise”不是跨 batch 或跨 token 求统计量，而是对每个 token 投影得到的整条 Q 或 K 向量</strong>归一化；“headwise”先拆成注意力头，再分别归一化每个头的向量。

| 粒度                      | 归一化沿哪个维度                          | 公开模型例子                                                         |
| ----------------------- | --------------------------------- | -------------------------------------------------------------- |
| Layerwise QK Norm（整层投影） | 对每个 token 的 Q/K 拼接投影宽度求 RMS，再拆为各头 | [OLMo 2、OLMo 3](https://allenai.org/papers/olmpool)            |
| Headwise QK Norm（逐头）    | 拆头后，分别对每个头的 `head_dim` 求 RMS      | [Qwen 3、Gemma 3、Marin 32B](https://allenai.org/papers/olmpool) |

<strong>做法。下面先用原始论文的逐头 L2 版本</strong>说明基本机制；上表现代模型中的 RMSNorm 版本不应直接等同于这个公式：

$$
\widehat q=\frac{q}{\|q\|_2+\epsilon},\qquad
\widehat k=\frac{k}{\|k\|_2+\epsilon},\qquad
s(q,k)=g\,\widehat q^{\mathsf T}\widehat k
$$

接着对所有允许关注的 key 的分数做 softmax。原始 QKNorm 论文使用 L2 归一化和可学习尺度，代替固定的 $1/\sqrt{d_k}$ 缩放。<strong>QK Norm 是方法家族，不限于这一种公式</strong>：当前模型可用整层或逐头的 RMSNorm，且缩放、RoPE 与归一化的先后顺序须看具体实现。

<strong>参数中文说明。</strong>$q$ 是一个 query 向量，$k$ 是一个 key 向量，$d_k$ 是每个注意力头的特征维度；$\widehat q$ 和 $\widehat k$ 是归一化后的向量；$g$ 是调节注意力分数幅度的可学习尺度，$s(q,k)$ 是进入 softmax 前的分数。$\epsilon$ 防止零向量除零。这里的 L2 公式只是 QK Norm 的一种具体形式。

<strong>PyTorch 调用。</strong>假设 `q/k/v` 的形状为 `[batch, heads, seq, head_dim]`，`g` 是已注册在模型中的可学习标量：

```python
q_unit = F.normalize(
    q,       # query 向量
    p=2,     # L2 归一化
    dim=-1,  # 每个头的 head_dim 维度
    eps=1e-6 # 防止零向量除零
)
k_unit = F.normalize(k, p=2, dim=-1, eps=1e-6)  # key 使用同样参数
logits = (q_unit * g) @ k_unit.transpose(-2, -1) # [B, H, S_q, S_k]
probs = logits.softmax(dim=-1)                   # 沿 key 位置计算概率
out = F.scaled_dot_product_attention(
    q_unit * g, # 先乘可学习尺度 g；scale 参数不能接收 Parameter
    k_unit,     # 已归一化的 key
    v,          # value 不在此处做 QK 归一化
    is_causal=True, # 自回归模型禁止看未来 token
    scale=1.0,  # 避免默认再乘 1 / sqrt(head_dim)
)
```

这里的 `logits/probs` 便于教学观察；注意力函数直接返回加权后的 `out`。逐头 RMSNorm 版本可在拆头后用 `nn.RMSNorm(head_dim)` 分别处理 Q/K；整层投影版本则应在拆头前，对 Q/K 各自的<strong>完整投影宽度</strong>应用 RMSNorm。两者的统计维度不同，不能只改模块名称。具体模型的 Q/K 投影宽度、权重形状与 RoPE 顺序仍须核对。参见 [PyTorch 注意力函数文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)。

<strong>作用位置。</strong>注意力内部、Q/K 投影之后、点积之前。它不负责归一化残差流中的隐藏状态，因此可与 LayerNorm、RMSNorm 或 ScaleNorm 同时出现。

<strong>目的与取舍。</strong>控制 query/key 范数和注意力 logits 的尺度，降低 softmax 因分数过大而饱和及训练不稳定的风险。它也改变注意力的表达方式，并增加计算。[OlmPool](https://allenai.org/papers/olmpool) 的受控实验发现 QK Norm 有助于稳定训练，但在其长上下文扩展实验中损害了部分效果；逐头版本的影响也与整层版本不同。因此需要结合训练稳定性和目标上下文长度评估，不能只因“更稳定”就默认采用。

<strong>代表性研究与应用。</strong>原始 QKNorm 论文使用逐头 L2 归一化；现代公开模型中的整层/逐头 RMSNorm 实例见上表。[Qwen3 技术报告](https://arxiv.org/abs/2505.09388) 也把 QK Norm 列为架构修改之一。

## 5. DeepNorm

<strong>做法。</strong>调整残差分支的比例，同时配套特殊初始化。用 $F$ 表示一个 Transformer 子层，其核心结构可概括为：

$$
x_{\mathrm{next}}=\mathrm{LayerNorm}(\alpha x+F(x))
$$

$\alpha$ 以及部分权重初始化的缩放系数由网络结构和深度确定。只复制上式而不采用配套初始化，并不等于完整实现了 DeepNorm。

<strong>参数中文说明。</strong>$x$ 是进入残差块的隐藏状态；$F(x)$ 是注意力或前馈子层的输出；$\alpha$ 控制残差路径中原输入的权重；$x_{\mathrm{next}}$ 是经过残差相加和 LayerNorm 后的输出。完整 DeepNorm 还包含依网络深度和结构确定的初始化缩放系数，不能只给 $\alpha$ 一个任意值。

<strong>PyTorch 调用。</strong>PyTorch 没有 `nn.DeepNorm` 标准模块。下面只展示残差块的局部前向式，假设 `sublayer` 已定义且输出形状与 `x` 相同：

```python
alpha = 1.5                 # 仅为演示；真实值由网络深度与结构确定
norm = nn.LayerNorm(
    normalized_shape=d,     # 归一化最后一维
    eps=1e-5,              # 防止方差为零
)
branch = sublayer(x)        # 注意力或前馈子层输出，形状同 x
y = norm(alpha * x + branch) # 先缩放残差、相加，再归一化
```

完整 DeepNorm 还要求按 [DeepNet 论文](https://arxiv.org/abs/2203.00555) 为相应编码器/解码器设置 `alpha` 和线性层初始化；单独调用 `nn.LayerNorm` 不能代表整个方案。

对 <strong>decoder-only、共 $M$ 个 Transformer 层</strong> 的情况，论文给出 $\alpha=(2M)^{1/4}$、初始化缩放 $\beta=(8M)^{-1/4}$。先对层权重做标准初始化（论文举 Xavier 为例），再用 $\beta$ 缩放前馈网络的权重，以及注意力的 value 投影和 output 投影权重；query/key 投影不在这份指定清单内。编码器或 encoder-decoder 的系数不同，不能套用这组公式。计算、初始化时机和被缩放的权重清单见 [DeepNet 论文第 4.3 节](https://arxiv.org/pdf/2203.00555)。<a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a> 会计算给定 $M$ 的系数，并构造一个带因果注意力和前馈层的小型 decoder-only Block；这仍不是深层训练效果验证。

<strong>作用位置。</strong>整个残差块，而非单个 token 向量的独立归一化公式。它保留了 LayerNorm，同时改变残差路径与初始化。

<strong>目的与取舍。</strong>面向非常深的 Transformer，缓解训练时更新过大或不稳定的问题。它引入结构和初始化约束，不能与“换成 RMSNorm”视作同一操作。

<strong>代表性研究。</strong>《DeepNet: Scaling Transformers to 1,000 Layers》验证了该方案在极深 Transformer 中的作用。

## 6. 其他值得了解的发展

下面每项都关系到归一化设计，但与前五项的作用层次不同；后续可扩为独立课程实验。

| 方案                    | 要点                         | 与本章五项的关系                              |
| --------------------- | -------------------------- | ------------------------------------- |
| pRMSNorm              | 从部分维度估计 RMS                | RMSNorm 原论文提出的近似变体；减少统计量计算，但会引入估计误差   |
| NormFormer            | 在注意力后、注意力头输出和前馈层内部增加归一化或缩放 | 调整归一化数量与位置的架构方案，可与基础归一化层结合            |
| Pre-Norm / Post-Norm  | 分别在子层前或残差相加后归一化            | 是<strong>位置选择</strong>，不是新的统计公式                    |
| Sandwich Norm / 双侧归一化 | 在子层前后都放归一化层                | 是<strong>层的布置方式</strong>；Gemma 2 是使用前后 RMSNorm 的实例 |
| DyT（Dynamic Tanh）     | 用带可学习参数的 tanh 操作替代归一化层     | 是<strong>归一化替代方案</strong>，本身不计算均值、方差或范数            |

BatchNorm 也是重要的深度学习方法，但它对 batch 的依赖及训练/推理统计量处理与这里的逐 token 隐藏状态归一化不同，本章不将其作为 LLM 主线。近年的论文仍不断提出新变体；本章覆盖有明确原始论文或代表模型证据、且能帮助理解 TinyLLM 设计的主要方案，并非宣称穷尽所有论文。

## 7. 两个容易混淆的维度

<strong>方法决定怎么算，位置决定在哪里算。</strong>设 $F$ 是注意力层或前馈层，`Norm` 可以是适用的隐藏状态归一化层：

```
Pre-Norm:   output = x + F(Norm(x))
Post-Norm:  output = Norm(x + F(x))
```

QK Norm 插在 $F$ 的注意力内部，不属于上面 `Norm(x)` 的同一个位置。DeepNorm 改写残差块并配合初始化。实际模型可以同时包含多种方案，不能只用一个词概括整套归一化设计。

### 在一个 decoder-only Block 中看位置

下面的示意图表示一种<strong>可组合的布局</strong>，不是某个具体预训练模型的逐层复刻。`Norm` 可选 LayerNorm、RMSNorm 或 ScaleNorm；QK Norm 只处理注意力内部的 Q/K；DeepNorm 则要求替换残差连接和初始化规则。

```
输入 x ────────────────┐
  │                   │
  └→ Norm → Q/K/V 投影 │
              ├→ QK Norm(Q, K) → QKᵀ → mask → softmax → 加权 V → 输出投影
              │                                           │
              └───────────────────────────────────────────┘
                       │
          普通 Pre-Norm：x + Attention(Norm(x))
                       │
          再经过 Norm → MLP → 残差相加 → 下一 Block

DeepNorm 改动的是残差块：LayerNorm(alpha * x + 子层输出)，
并按网络深度设置 alpha 和指定权重的初始化缩放 beta。
```

因果 mask 必须在 softmax 前施加。QK Norm 的具体实现可能安排在 RoPE 前或后，应以目标架构为准。图中的 `Norm → Q/K/V 投影` 与 `Attention(Norm(x))` 是同一条路径的展开。

<strong>手算检查。</strong>取 $x=[1,2,3]$，仅为方便计算暂设 $\epsilon=0$，并令缩放参数为 1、平移参数为 0：

* LayerNorm：均值为 2，方差为 $2/3$，输出约为 $[-1.225,0,1.225]$。
* RMSNorm：均方根为 $\sqrt{14/3}$，输出约为 $[0.463,0.926,1.389]$。
* ScaleNorm：L2 范数为 $\sqrt{14}$，输出约为 $[0.267,0.535,0.802]$。

真实实现必须保留正的 $\epsilon$，尤其要处理全零向量。QK Norm 需要成对的 query/key 才能展示；DeepNorm 需要残差子层与初始化才有意义，不能硬塞进这个单向量算例。

## 8. 常用方案与 PyTorch 调用

<strong>在入门代码和常见 LLM 架构中，LayerNorm 与 RMSNorm 是最常见的隐藏状态归一化层。</strong>QK Norm 用于需要额外控制注意力分数的架构；ScaleNorm 和 DeepNorm 是需要理解的研究方案，选用时要连同论文的结构与训练设定一起评估。这里说的是使用频率，不是教学重要性：本章五种方法都应掌握。预训练模型应遵守其原本架构，不能仅因为某种方法“更常用”就替换权重对应的归一化层。

下面的例子只演示 API 与张量维度。输入 `x` 为 `[batch, seq_len, hidden_size]`；`nn.LayerNorm(d)` 和 `nn.RMSNorm(d)` 都作用于最后一维。PyTorch 2.11 中有这两个内置模块，实际项目仍应核对所用版本。

```python
import torch
from torch import nn
from torch.nn import functional as F

batch, seq_len, d = 2, 4, 8
x = torch.randn(batch, seq_len, d)

# LayerNorm：逐 token 计算均值和方差；默认有 weight 和 bias。
layer_norm = nn.LayerNorm(d, eps=1e-5)
y_ln = layer_norm(x)

# RMSNorm：逐 token 计算均方根；默认只有 weight。
rms_norm = nn.RMSNorm(d, eps=1e-5)
y_rms = rms_norm(x)

# ScaleNorm：PyTorch 无同名标准模块，用基础算子组合。
# 一个可学习标量 g；此处将其初值设为 sqrt(d)。
g = nn.Parameter(torch.tensor(d**0.5))
y_scale = g * x / x.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-6)

assert y_ln.shape == y_rms.shape == y_scale.shape == x.shape
```

`F.normalize(x, p=2, dim=-1, eps=1e-6)` 也可完成 L2 归一化；**一定写 `dim=-1`**，因为其默认维度是 `1`。它使用 `max(norm, eps)` 防止除零，与前面教学公式的 `norm + eps` 在接近零时不完全相同。

QK Norm 没有一个统一的 PyTorch `nn.QKNorm` 标准模块。以下是原始论文思路的<strong>L2 版本示意</strong>。`q/k/v` 的形状是 `[batch, heads, seq_len, head_dim]`。`scaled_dot_product_attention` 的 `scale` 参数只接受 Python 数值，不能直接传可学习的 `Parameter`；因此先把 $g$ 乘到 query 上，再指定 `scale=1.0`，避免函数默认再乘一次 $1/\sqrt{d_k}$。

```python
heads, head_dim = 2, 4
q = torch.randn(batch, heads, seq_len, head_dim)
k = torch.randn(batch, heads, seq_len, head_dim)
v = torch.randn(batch, heads, seq_len, head_dim)

q_unit = F.normalize(q, p=2, dim=-1, eps=1e-6)
k_unit = F.normalize(k, p=2, dim=-1, eps=1e-6)
g_qk = nn.Parameter(torch.tensor(head_dim**0.5))
attention_out = F.scaled_dot_product_attention(
    q_unit * g_qk, k_unit, v, is_causal=True, scale=1.0
)
assert attention_out.shape == q.shape
```

有些模型采用<strong>逐头 RMSNorm 版 QK Norm</strong>，那应分别对 `q`、`k` 的最后一维使用 `nn.RMSNorm(head_dim)`；它与上面的 L2 版本不完全等价。RoPE、缩放参数和归一化的先后顺序应按目标模型实现核对。

DeepNorm 也没有一个单独的 `nn.DeepNorm` 调用。`nn.LayerNorm(d)(alpha * x + F_sub(x))` 只能表达其残差块的一个局部形式；真正的 DeepNorm 还必须根据网络深度、编码器/解码器结构设置 $\alpha$ 和配套的权重初始化。**不要把一个任意 `alpha` 加到残差上就称为完整 DeepNorm。**

## 9. 动手实验：看归一化前后发生了什么

打开 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a>，选择安装了 PyTorch 的 Python 内核，从上到下运行所有单元格。本实验在 PyTorch 2.11.0 上运行通过，使用固定输入，不需要下载数据或训练模型。notebook 逐项打印原始向量、输出向量及最后一维的 `mean`、`RMS`、`L2`，并提供读数说明和练习。输入形状为 `[1, 4, 4]`，即一个 batch、四个 token、每个 token 四个特征。

| 实验            | 输入                                      | 应观察到什么                                               |
| ------------- | --------------------------------------- | ---------------------------------------------------- |
| LayerNorm     | `[1,2,3,4]` 与整体加 10 后的 `[11,12,13,14]`  | 两行归一化输出相同，均值约为 0；说明它消除了整体平移                          |
| RMSNorm       | 同上                                      | 两行输出不同，均方根约为 1，输出均值通常不为 0                            |
| ScaleNorm     | 同上，固定 `g=1`                             | 非零输入的 L2 长度约为 1，但均值不被强制变为 0                          |
| 全零向量          | `[0,0,0,0]`                             | 三种输出均为有限的零向量；观察 `eps` 防止除零                           |
| QK Norm       | 长度差异很大的两个 Q/K 向量                        | 原始 `QK` 最大分数为 100；L2 归一化后最大分数为 1，并改变 softmax 概率      |
| DeepNorm 残差示意 | 相同 `x` 和分支输出，比较 `alpha=1` 与 `alpha=1.5` | 改变残差输入相加前的比例，会改变 LayerNorm 的输入与输出；`1.5` 只是演示值，不是论文系数 |

notebook 还提供完整的 <strong>输入平移/正数缩放对照</strong>、<strong>decoder-only DeepNorm 系数与初始化名单</strong>，以及下面的 <strong>FP32/FP16/BF16 数值实验</strong>。这些单元格对应本章第 7 节的位置说明、第 5 节的 DeepNorm 公式和第 10 节的精度讨论。

<strong>读数提示：</strong>非零输入经过默认 LayerNorm 后的 RMS 约为 1；经过默认 RMSNorm 后的 RMS 约为 1；经过 `g=1` 的 ScaleNorm 后的 <strong>L2</strong> 约为 1。这三个“约为 1”对应不同统计量，不能混为一谈。全零向量是例外。`eps` 会使数值略偏离 1，学到的 `weight/bias` 也会改变这些输出性质。

### 实验：给输入平移或缩放

在 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a> 中，用同一个向量分别计算 `x`、`x + c`、`a * x`，并分别送入三种方法。暂不考虑 $\epsilon$ 和学到的仿射参数时，LayerNorm 对所有维度加同一个常数不敏感；RMSNorm、ScaleNorm 一般会改变结果。对正的整体乘数 $a$，三者理论上都保持输出不变；当 $\epsilon$ 不可忽略或低精度输入已经舍入时，只能说<strong>近似</strong>不变。负乘数会翻转输出符号（LayerNorm 有非零偏置时还需另外考虑偏置）。

### PyTorch 函数与参数速查

| 调用                                                                    | 本实验中的参数                                       | 参数含义与常见坑                                                                                                                           |
| --------------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `nn.LayerNorm(normalized_shape=d, eps=1e-5)`                          | `d=4`；默认 `elementwise_affine=True, bias=True` | 整数 `d` 表示只归一化最后一维；`eps` 加在方差上；默认有形状为 `[d]` 的 `weight` 和 `bias`。`bias=False` 只关闭偏置，`elementwise_affine=False` 同时关闭可学习仿射参数。          |
| `nn.RMSNorm(normalized_shape=d, eps=1e-5)`                            | `d=4`；默认 `elementwise_affine=True`            | 只归一化最后一维；默认有 `[d]` 的 `weight`，没有 `bias` 参数。默认 `eps=None` 时按内部计算类型选 epsilon；本课显式设为 `1e-5`。                                          |
| `F.normalize(x, p=2, dim=-1, eps=1e-6)`                               | `p=2` 为 L2；`dim=-1` 为隐藏维度                     | `F.normalize` 的默认 `dim=1`，对 `[batch, seq, hidden]` 会沿 <strong>seq</strong> 而非 hidden 归一化，所以这里必须显式传 `-1`；计算为 `x / max(L2(x), eps)`。              |
| `x.norm(p=2, dim=-1, keepdim=True)`                                   | `keepdim=True`                                | 得到 `[batch, seq, 1]` 范数，便于广播回原向量；`clamp_min(1e-6)` 避免零分母。                                                                          |
| `F.scaled_dot_product_attention(q, k, v, is_causal=False, scale=1.0)` | Q/K/V 为 `[batch, heads, seq, head_dim]`       | 返回注意力加权后的 V，<strong>不返回 logits 或概率矩阵</strong>；实验单独用矩阵乘法打印 logits。默认 `scale` 为 $1/\sqrt{d_k}$，这里显式设 `1.0` 以观察归一化的影响。自回归注意力应设置 `is_causal=True`。 |

可学习参数可用 `module.named_parameters()` 查看。notebook 会打印 LayerNorm 的 `weight/bias` 和 RMSNorm 的 `weight`。`F.normalize` 与 `Tensor.norm` 本身不创建参数；ScaleNorm 的标量 `g` 要作为 `nn.Parameter` 注册在模型里。前面 API 示例展示了这种写法，notebook 为便于对照把 `g` 固定为 1。

<strong>实验边界：</strong>QK Norm 演示使用 L2 版本；DeepNorm 先用任意 $\alpha$ 展示局部残差变化，随后在第 10 节按论文的 decoder-only 系数与初始化构造小型 Block。notebook 没有训练完整深层网络。之后若比较训练稳定性与速度，应在相同数据、深度、dtype、设备和计时方式下做专门实验。

## 10. BF16/FP16 对归一化有什么影响？

### 10.1 为什么归一化有时能让低精度计算更稳？

把 FP16 想成一把<strong>刻度有限、量程也有限</strong>的尺子。归一化不会增加这把尺子的刻度数；它改变的是送入<strong>后续运算</strong>的数值大小。以 RMSNorm 为例，先把一个向量除以它的均方根，归一化后的均方根约为 1（忽略 `eps` 和可学习的 `weight`）。LayerNorm 还会减均值，使该向量均值约为 0、方差约为 1。这样，后续矩阵乘法、平方或注意力点积遇到极大数值而溢出的机会<strong>可能降低</strong>。这是“控制数值范围”，不是“提高浮点格式的精度”。[PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html) 也建议对极端输入考虑归一化或截断，并检查非有限值。

例如，FP16 能存下 `1000`，却存不下 `1000 × 1000`（会溢出）；若先在安全的计算路径中把一组约为 `1000` 的激活归一化到约为 1，再转换成 FP16 去平方，结果就可能保持有限。**顺序很重要：若在归一化内部已经用低精度算出了 `inf`，或者输入转换时已丢失小差异，事后归一化不能修复。notebook 的第 9 节有“先低精度平方”和“先用 FP32 平方”的对照；这里解释的是为什么把归一化放在后续敏感运算之前**可能有帮助。

归一化也不是“低精度安全保证”：除以很小的 RMS/标准差可能放大噪声，所以公式需要 `eps`；可学习的缩放参数、后续权重与残差相加又可能把数值放大。BF16 的范围较宽，但刻度较粗；归一化无法恢复 BF16 输入中已被舍入掉的差异。因此要分别观察<strong>激活是否溢出</strong>、<strong>结果离 FP32 参考有多远</strong>和<strong>训练是否收敛</strong>，不能只凭归一化后的范围判断“精度变好了”。完整的浮点格式、混合精度和误差实验放在规划的 Chapter 15。

### 10.2 归一化本身也要注意计算精度

归一化的公式涉及均值或平方和，再做除法。输入 dtype 影响<strong>输入能表示的数</strong>，统计量的计算 dtype 和算子实现影响<strong>中间结果</strong>，输出 dtype 又影响最终的舍入。不能只看输入标着 BF16/FP16 就断言整个计算都在该 dtype 中完成。

| dtype | 主要特点                      | 归一化中的典型风险                                  |
| ----- | ------------------------- | ------------------------------------------ |
| FP32  | 动态范围和有效精度都较高              | 作为本章的数值参考，但不同内核仍可能有细微差异                    |
| FP16  | 有效精度比 BF16 高，但动态范围窄       | 很小的数可能下溢或被舍入为 0；很大的数、平方或累加可能溢出             |
| BF16  | 指数范围接近 FP32，但有效精度比 FP16 低 | 较大的基数上，小差异可能在输入转换时消失，尤其影响需要先减均值的 LayerNorm |

`torch.finfo(dtype).eps` 是 <strong>1 附近可分辨的相对间隔</strong>；`tiny` 是最小正规范数正数，`max` 是最大有限数。它们意义不同，也与归一化层构造函数中的 `eps` 参数不同。FP16 与 BF16 的实际表示范围可用 notebook 中的 `torch.finfo` 在本机查看。[PyTorch 数值类型文档](https://docs.pytorch.org/docs/stable/type_info.html) 对这些字段有定义。

notebook 分别演示三类情况：① FP16 对微小值的舍入/下溢，② BF16 在较大基数上丢失微小差异，③ 先在低精度中平方与先转成 FP32 再平方的差别。最后比较 `nn.LayerNorm`、`nn.RMSNorm` 在 FP32/FP16/BF16 输入上的输出与 FP32 参考结果。<strong>差异不能一概归因于公式</strong>：输入一旦转换成低精度并丢失信息，后续转回 FP32 也无法恢复。

实际训练中常用混合精度，并由框架/内核决定某些统计计算的更高精度路径。若自己手写归一化，可明确采用 `x.float()` 计算均值或平方均值、除法，再按需要转回输入 dtype；这只保护转换之后的计算，不能弥补已经发生的输入舍入。FP16 训练还要关注梯度下溢/溢出与 loss scaling，BF16 则更要关注舍入精度；二者没有普遍的“哪个归一化永远更稳定”结论。参见 [PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html) 和 [PyTorch AMP 文档](https://docs.pytorch.org/docs/stable/amp.html)。

## 11. 五种方法的教学版实现

<a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb 第 10 节</a> 将公式写成可运行的 `nn.Module`：

| 方法        | 教学实现中的关键步骤                                            | 检查方式                                         |
| --------- | ----------------------------------------------------- | -------------------------------------------- |
| LayerNorm | `mean → 减均值 → 方差 → rsqrt → weight/bias`               | 与 `nn.LayerNorm` 比较输出、输入梯度和参数梯度              |
| RMSNorm   | `平方均值 → rsqrt → weight`                               | 与 `nn.RMSNorm` 比较输出、输入梯度和参数梯度                |
| ScaleNorm | `L2 范数 → 除以长度 → 乘可学习标量 g`                             | 检查非零向量长度、零向量和 `g` 的梯度                        |
| QK Norm   | 逐头归一化 Q/K → `QKᵀ` → softmax → 加权 V                    | 与 `F.scaled_dot_product_attention` 对照输出并检查梯度 |
| DeepNorm  | 按 decoder-only 层数确定 $\alpha,\beta$ → 初始化指定投影 → 两个残差子层 | 检查输出形状和反向梯度；不宣称复现深层训练收益                      |

这些实现用于看清统计量、数据依赖和参数。它们没有融合内核，<strong>不能用作性能基准</strong>。LayerNorm/RMSNorm 的对照使用 FP32；低精度实验见第 10 节。DeepNorm 小 Block 的 $M$ 表示假设的总层数，单个 Block 的运行只检验局部实现；完整模型仍需搭建 $M$ 层并训练验证。

## 12. Apple 平台上的 MLX 对照

<a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb 第 12 节</a> 新增可选 MLX 单元：用 `mlx.core` 对照 LayerNorm、RMSNorm、ScaleNorm、QK Norm 的关键运算，并用 `mlx.nn.LayerNorm`、`mlx.nn.RMSNorm` 核对前两者；DeepNorm 只演示局部残差系数，完整方案仍需多层网络与初始化。MLX 使用自己的数组和模块，不能把它当作 PyTorch 的 `device="mlx"`。未安装 MLX 时该节自动跳过；安装与平台要求见 [MLX 官方文档](https://ml-explore.github.io/mlx/build/html/install.html)。本节的手写公式与前面的 PyTorch 教学实现相互对照，不用于速度比较。

## 参考资料

* [Layer Normalization，Ba 等，2016](https://arxiv.org/abs/1607.06450)
* [Root Mean Square Layer Normalization，Zhang 与 Sennrich，2019](https://arxiv.org/abs/1910.07467)
* [Transformers without Tears：ScaleNorm，Nguyen 与 Salazar，2019](https://arxiv.org/abs/1910.05895)
* [Query-Key Normalization for Transformers，Henry 等，2020](https://aclanthology.org/2020.findings-emnlp.379/)
* [DeepNet：DeepNorm，Wang 等，2022](https://arxiv.org/abs/2203.00555)
* [NormFormer，Shleifer 等，2021](https://arxiv.org/abs/2110.09456)
* [Transformers without Normalization：DyT，Zhu 等，2025](https://arxiv.org/abs/2503.10622)
* [LLaMA 论文，Touvron 等，2023](https://arxiv.org/abs/2302.13971)
* [GPT-3 论文，Brown 等，2020](https://arxiv.org/abs/2005.14165)
* [Gemma 2 技术报告，2024](https://arxiv.org/abs/2408.00118)
* [Qwen3 技术报告，2025](https://arxiv.org/abs/2505.09388)
* [PyTorch LayerNorm 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html) · [PyTorch RMSNorm 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.RMSNorm.html)
* [PyTorch `F.normalize` 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.normalize.html) · [PyTorch `scaled_dot_product_attention` 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)
