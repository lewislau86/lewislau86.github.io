---
title: "TinyLLM 教程"
description: "从零实现一个能训练、能生成文本、能接受基本评估的小型语言模型。"
pageClass: tinyllm-course
---

# TinyLLM 教程

从零实现一个能训练、生成文本并接受基本评估的 TinyLLM。课程既讲模型结构，也讲让模型**可训练、稳定训练和正确评估**所需的数据、初始化、优化、精度与工程方法。每章配一份可以逐格运行的 PyTorch notebook。

下面这张图就是全书的地图：一段文本从上往下穿过各个零件，变成“下一个字”的分数；训练时再从右侧绕回去更新参数。**每个方框都可以点击**，跳到负责讲它的那一章。之后每章开头都会出现这张图，并高亮本章负责的零件。

<TinyLLMMap />

## 从哪里开始

如果你刚学完大学基础数学与 Python，按顺序读即可：

1. **先读[第 1 章](./first-run.md)，把整条流水线跑起来。** 半分钟训练一个会背唐诗的小模型，看到损失怎样下降、输出怎样从乱码变成诗句。这一章不讲原理，只建立整体印象。
2. **再读第 2～5 章，学会让网络“可训练”。** 张量与梯度，然后是深层网络必备的三件工具：初始化与残差、归一化、门控前馈层。
3. **然后沿第三、四部分把模型搭完整、训练好。** 已成文的章节之间如果隔着规划中的章节，可以先跳过，侧栏的“下一篇”会直接带你到下一章已完成的内容。

不要求现在就认识每个名词。遇到 MoE、μP 等，先知道它们是后续专题即可。

## 已成文的章节

| 章节 | 标题 | 内容 | notebook |
| --- | --- | --- | --- |
| 第 1 章 | [先跑通一个最小 TinyLLM](./first-run.md) | 39 首唐诗、不到 100 行代码，训练一个能“写诗”的小模型，看损失曲线与过拟合 | [first-run.ipynb](/tinyllm/notebooks/first-run) |
| 第 2 章 | [张量与自动求导](./tensors-and-autograd.md) | 张量形状、广播、矩阵乘法、计算图与一次手算梯度 | [tensors-and-autograd.ipynb](/tinyllm/notebooks/tensors-and-autograd) |
| 第 3 章 | [初始化与残差路径](./initialization-and-residuals.md) | Xavier/He 初始化、残差直通路径、深度诊断 | [initialization-and-residuals.ipynb](/tinyllm/notebooks/initialization-and-residuals) |
| 第 4 章 | [归一化](./normalization.md) | LayerNorm、RMSNorm、ScaleNorm；Pre-Norm 与 Post-Norm | [normalization.ipynb](/tinyllm/notebooks/normalization) |
| 第 5 章 | [激活函数与门控前馈层](./activations-and-ffn.md) | ReLU/GELU/SiLU、SwiGLU 门控前馈层与参数量 | [activations-and-ffn.ipynb](/tinyllm/notebooks/activations-and-ffn) |
| 第 6 章 | [文本与词元化](./tokenization.md) | Unicode 与字节、BPE 训练与编码、特殊 token、词表实验 | [tokenization.ipynb](/tinyllm/notebooks/tokenization) |
| 第 7 章 | [词嵌入与输出层](./embeddings-and-output.md) | 查表、logits、交叉熵梯度、Q/K/V 与 KV cache、权重共享 | [embeddings-and-output.ipynb](/tinyllm/notebooks/embeddings-and-output) |
| 第 14 章 | [优化器](./optimizers.md) | SGD、Momentum、Adam、AdamW、Adafactor；参数组与优化器状态 | [optimizers.ipynb](/tinyllm/notebooks/optimizers) |
| 第 17 章 | [数值精度与混合精度](./precision.md) | FP32/FP16/BF16、舍入与溢出、autocast；归一化与精度的关系 | [precision.ipynb](/tinyllm/notebooks/precision) |

## 课程路线 {#roadmap}

### 第一部分 · 先跑起来

用最短的代码看到完整流水线。

- [第 1 章 · 先跑通一个最小 TinyLLM](./first-run.md)

### 第二部分 · 可训练的网络

张量与梯度，以及让深层网络能稳定训练的三件工具：初始化与残差、归一化、前馈层。

- [第 2 章 · 张量与自动求导](./tensors-and-autograd.md)
- [第 3 章 · 初始化与残差路径](./initialization-and-residuals.md)
- [第 4 章 · 归一化](./normalization.md)
- [第 5 章 · 激活函数与门控前馈层](./activations-and-ffn.md)

### 第三部分 · 构造语言模型

从文本入口一路搭到完整的 Decoder-only 模型。

- [第 6 章 · 文本与词元化](./tokenization.md)
- [第 7 章 · 词嵌入与输出层](./embeddings-and-output.md)
- [第 8 章 · 位置表示](./position-encoding.md)（规划中）
- [第 9 章 · 自注意力](./self-attention.md)（规划中）
- [第 10 章 · Transformer Block](./transformer-block.md)（规划中）
- [第 11 章 · 完整 TinyLLM](./tinyllm-model.md)（规划中）

### 第四部分 · 数据与训练

数据、目标函数、优化器、学习率、精度与训练诊断。

- [第 12 章 · 语料与数据管线](./data-pipeline.md)（规划中）
- [第 13 章 · 语言模型目标函数](./language-model-loss.md)（规划中）
- [第 14 章 · 优化器](./optimizers.md)
- [第 15 章 · 学习率策略](./learning-rate.md)（规划中）
- [第 16 章 · 正则化与泛化](./regularization.md)（规划中）
- [第 17 章 · 数值精度与混合精度](./precision.md)
- [第 18 章 · 梯度稳定与累积](./gradient-stability.md)（规划中）
- [第 19 章 · 训练循环与检查点](./training-loop.md)（规划中）
- [第 20 章 · 训练诊断与评估](./training-evaluation.md)（规划中）

### 第五部分 · 生成与扩展

生成、推理效率、微调与扩展专题。

- [第 21 章 · 自回归生成](./generation.md)（规划中）
- [第 22 章 · 推理效率](./inference-efficiency.md)（规划中）
- [第 23 章 · 指令微调](./instruction-finetuning.md)（规划中）
- [第 24 章 · 参数高效与稀疏结构](./peft-and-sparsity.md)（规划中）
- [第 25 章 · 大规模训练稳定性](./large-model-stability.md)（规划中）
- [第 26 章 · 扩展专题](./advanced-topics.md)（规划中）
- [第 27 章 · Agent 记忆与检索](./agent-memory.md)（规划中）

## 贯穿全书的主线选择 {#mainline-choices}

每章结尾都有一节“本章结论：TinyLLM 的选择”，回答三个问题：**主线具体选什么、为什么、什么情况下换方案**。下表把它们汇总在一起。这是从零训练一个小型、稠密、Decoder-only 语言模型的教学基线，不是“所有现代大模型的唯一最优配方”；规划章节的选择还要用相同数据、参数预算和训练条件验证。

<details>
<summary>展开全书主线选择汇总表（27 行）</summary>

| 章节 | 主线选择 | 主要理由与调整条件 |
| --- | --- | --- |
| [1 先跑通](./first-run.md) | 一个文件跑通字符级小模型：字符编号、可学习位置向量、3 层 Pre-RMSNorm Block、AdamW | 先看到完整流水线和损失曲线，再逐章替换成正式方案；它只用于建立整体印象，不是后续章节的基线配置。 |
| [2 自动求导](./tensors-and-autograd.md) | 用 PyTorch autograd 训练，手算小例子核验 | 保留正确的计算图；手写反传用于理解和梯度检查。 |
| [3 初始化与残差](./initialization-and-residuals.md) | 线性层先用 Xavier normal，嵌入用标准差 `1/√d` 的零均值正态；注意力输出和 FFN 输出投影再乘 `1/√(2L)`；采用 Pre-Norm 与两次残差相加 | 随机权重打破对称，较小的初始残差更新抑制深度累积；这是教学起点，仍需结合激活 RMS 与梯度诊断。 |
| [4 归一化](./normalization.md) | 每个注意力/前馈子层前用 RMSNorm，末尾再用一次 RMSNorm | 控制每个 token 的尺度，计算较简洁；若注意力分数失控，再评估 QK Norm；极深 Post-Norm 结构另研究 DeepNorm。 |
| [5 激活与 FFN](./activations-and-ffn.md) | 无偏置 SwiGLU：SiLU 门控，门控宽度先取约 `8d/3` | 相近参数预算下比较门控与普通 `4d` FFN；若追求最少算子或复现旧架构，可选 GELU/ReLU 普通 FFN。 |
| [6 词元化](./tokenization.md) | 训练可逆的字节级 BPE，固定特殊 token 协议 | 未见字符可退回字节；词表大小需按语种、语料和序列长度权衡。 |
| [7 嵌入与输出](./embeddings-and-output.md) | 可学习 token embedding；教学小模型先共享输入嵌入与输出权重 | 减少词表相关参数；若预算充足或共享约束影响效果，再试独立输出层。 |
| [8 位置表示](./position-encoding.md) | 对 Q/K 使用 RoPE | 把位置信息放进注意力计算；超过训练上下文不能只靠 RoPE 自动保证质量，须专门验证或扩展训练。 |
| [9 自注意力](./self-attention.md) | 因果掩码的缩放点积注意力；先实现 MHA，再按推理预算切换 GQA | MHA 便于核对形状，GQA 可减少 KV cache；两者的头数与质量需一起验证。 |
| [10 Transformer Block](./transformer-block.md) | 注意力和 SwiGLU 各有一次 Pre-RMSNorm 与残差加法 | 保留直接的残差梯度路径；复杂的额外归一化只在诊断有需求时加入。 |
| [11 完整模型](./tinyllm-model.md) | 稠密 Decoder-only Transformer，最后 RMSNorm 接词表 logits | 先形成可训练、可生成的闭环；MoE 等结构留到有明确规模和吞吐需求时。 |
| [12 数据](./data-pipeline.md) | 先清洗、去重，再按文档或来源划分训练/验证集并检查跨集合近重复 | 避免同源内容跨集合泄漏；混合比例取决于任务与语料质量。 |
| [13 损失](./language-model-loss.md) | 下一个 token 的交叉熵，只统计有效目标 token | 与自回归生成目标一致；有 padding 或 SFT 模板时显式掩码。 |
| [14 优化器](./optimizers.md) | AdamW；对归一化权重及偏置关闭 weight decay | 自适应更新适合基线，衰减与梯度惩罚分离；状态内存不足再比较 Adafactor 等。 |
| [15 学习率](./learning-rate.md) | 按优化器 step 短暂 warmup，随后 cosine decay | 降低初期大更新的风险，后期平滑降低步长；峰值和 warmup 长度依预算调参。 |
| [16 正则化](./regularization.md) | AdamW 的适度 weight decay；先不加 label smoothing，dropout 从 0 起测 | 先用验证集判断过拟合，再决定是否增加 dropout；低数据量下不能照搬大规模预训练设置。 |
| [17 精度](./precision.md) | 支持时用 BF16 混合精度，关键归约保持稳定实现；否则用 FP32 | BF16 指数范围较宽；缺 BF16 且需 FP16 时再配合 GradScaler。 |
| [18 梯度](./gradient-stability.md) | 记录梯度范数并按全局范数裁剪；需要大有效 batch 时做梯度累积 | 能定位并限制异常更新；裁剪阈值和累积步数不能脱离损失归一化设置。 |
| [19 训练循环](./training-loop.md) | 固定种子，明确 `zero_grad → forward → backward → clip → step → scheduler`，保存完整检查点 | 便于复现和中断恢复；梯度累积时只在更新步裁剪、更新学习率。 |
| [20 评估](./training-evaluation.md) | 先过拟合小 batch，再看独立验证集交叉熵/困惑度与生成样例 | 分开排查代码连通性、泛化和生成质量；比较困惑度需同一 tokenizer 与数据口径。 |
| [21 生成](./generation.md) | 可复现评估用贪心解码；开放式生成提供温度与 top-p | 评估稳定，交互时可调多样性；采样参数需随任务调节。 |
| [22 推理](./inference-efficiency.md) | 自回归 decode 使用 KV cache，分别测 prefill 与 decode | 避免每步重算前缀；长上下文和并发会增加显存，必要时配合 GQA。 |
| [23 指令微调](./instruction-finetuning.md) | 在预训练模型上做 SFT，只对助手答案计算 loss | 让监督信号对应目标回答；模板和终止 token 必须与推理一致。 |
| [24 参数高效](./peft-and-sparsity.md) | 小模型先全参数训练；显存受限的微调再用 LoRA | LoRA 节省可训练参数及优化器状态；MoE 与剪枝有不同目标，不能统称为“更省”。 |
| [25 大规模稳定性](./large-model-stability.md) | 保留基础 Pre-Norm 配置并监测尺度；扩深/扩宽出现问题时才评估 μP、DeepNorm 等整套方案 | 这些方法涉及初始化、结构和学习率的联动，不能只替换一个常数。 |
| [26 扩展专题](./advanced-topics.md) | 优先使用 PyTorch 的缩放点积注意力接口；量化、分布式与对齐按目标单独引入 | 实现可以选择可用的高效内核；部署约束出现前不增加训练基线的复杂度。 |
| [27 Agent 记忆](./agent-memory.md) | 在模型外保存有来源和时间的文本事实，检索后放回上下文 | 参数和 KV cache 不会自动保存可更新的跨会话事实；按规模决定是否增加向量索引。 |

归一化、激活和位置编码的主线选择参考 [LLaMA](https://arxiv.org/abs/2302.13971) 与 [Llama 3](https://arxiv.org/abs/2407.21783) 的公开架构；门控前馈层见 [GLU 变体研究](https://arxiv.org/abs/2002.05202)，Pre-Norm 的初始化梯度分析见 [Xiong 等](https://arxiv.org/abs/2002.04745)。线性层的 Xavier 初始化见 [PyTorch 文档](https://docs.pytorch.org/docs/stable/nn.init.html)；残差投影按层数缩小借鉴 [nanoGPT 的具体实现](https://github.com/karpathy/nanoGPT/blob/master/model.py)，但这里从 Xavier 尺度出发，并非逐行复现 nanoGPT，更不是所有 LLM 共用的规则。GQA 的缓存权衡见 [GQA 论文](https://arxiv.org/abs/2305.13245)。

</details>

<details>
<summary>几组容易混淆的概念</summary>

* <strong>Pre-LN/Post-LN 是归一化放置方式</strong>，Residual Connection 是结构，RMSNorm 是具体归一化算法；三者可以组合，不应作为互斥选项。
* <strong>Weight Decay 与 L2 惩罚不总等价</strong>。特别是在 AdamW 中，权重衰减与梯度中的 L2 项是不同做法，课程会用参数更新算例对照。[PyTorch AdamW 文档](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html) 提供了算法定义。
* <strong>Label Smoothing、Early Stopping、Dropout 并非每个 LLM 预训练都必须采用</strong>；要结合目标函数、训练预算与验证策略判断。
* <strong>Gradient Scaling 是泛称，Loss Scaling 是其中用于缩放 loss/梯度的具体做法</strong>，在 FP16 混合精度训练中特别常见。梯度裁剪限制梯度范数，梯度累积合并多个 micro-batch；这三类操作的目的与调用顺序需要分别解释。
* <strong>BatchNorm/GroupNorm 值得对照学习</strong>，但本项目的 Decoder-only 主线优先理解逐 token 的 LayerNorm/RMSNorm；[PyTorch 归一化 API](https://docs.pytorch.org/docs/stable/nn.html#normalization-layers) 可用于检查各层统计维度。

数据去重和混合不只是加载技巧，也会影响语言模型质量与评估可信度，可参见 [Deduplicating Training Data Makes Language Models Better](https://arxiv.org/abs/2107.06499) 和 [DataComp-LM](https://arxiv.org/abs/2406.11794)。训练循环的基础调用顺序可参考 [PyTorch 官方优化教程](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial)。

</details>

## 写作与图表约定

正文配图是静态 SVG，由 `scripts/generate-tinyllm-figures.py` 生成；notebook 中的交互图表统一使用 **Plotly**。完整的写作规范见[课程写作规范](/guide/course-conventions)。
