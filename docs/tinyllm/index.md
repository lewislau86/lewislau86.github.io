---
title: "TinyLLM 教程"
description: "从零实现一个能训练、能生成文本、能接受基本评估的小型语言模型。"
pageClass: tinyllm-course
---

# TinyLLM 教程

从零实现一个能训练、生成文本并接受基本评估的 TinyLLM。课程既讲模型结构，也讲让模型**可训练、稳定训练和正确评估**所需的数据、初始化、优化、精度与工程方法。每章配一份可以逐格运行的 PyTorch notebook。

动手之前，先按[实验环境：安装与代码下载](./setup.md)装好 Python 和 PyTorch，并下载全部章节的代码和 notebook（整包 zip、单章下载或 git 都可以）。只需要 CPU，大约十分钟。

下面这张图就是全书的地图：一段文本从上往下穿过各个零件，变成“下一个字”的分数；训练时再从右侧绕回去更新参数。**每个方框都可以点击**，跳到负责讲它的那一章。之后每章开头都会出现这张图，并高亮本章负责的零件。

<TinyLLMMap />

## 从哪里开始

如果你刚学完大学基础数学与 Python，按顺序读即可：

1. **先读[第 1 章](./first-run.md)，把整条流水线跑起来。** 半分钟训练一个会背唐诗的小模型，看到损失怎样下降、输出怎样从乱码变成诗句。这一章不讲原理，只建立整体印象。
2. **再读第 2、3 章，补两样背景。** [第 2 章](./tensors-and-autograd.md)备好工具：张量、形状和自动求导，后面每一章都要用；[第 3 章](./architecture-evolution.md)讲架构的来历：从翻译用的 Transformer，到只有解码器的 GPT，再到今天的稀疏混合架构，TinyLLM 的每个零件都能在这里找到出处。
3. **然后顺着总图从上往下搭模型（第 4～9 章）。** 文字变编号、编号变向量、注意力让向量互相看见、前馈层各自加工，最后装进 Block。
4. **把 Block 叠深，它会训不动；第 10～12 章修好它。** 残差、初始化、归一化三件工具让深层网络稳定，再组装出完整的 TinyLLM。
5. **之后是数据与训练（第 13～23 章），再到推理（第 24～26 章）、后训练（第 27～30 章）和应用（第 31 章）。** 已成文的章节之间如果隔着规划中的章节，可以先跳过，侧栏的“下一篇”会直接带你到下一章已完成的内容。

不要求现在就认识每个名词。遇到 MoE、μP 等，先知道它们是后续专题即可。

## 已成文的章节

| 章节 | 内容 | notebook |
| --- | --- | --- |
| [第 1 章 · 先跑通一个最小 TinyLLM](./first-run.md) | 39 首唐诗、不到 100 行代码，训练一个能“写诗”的小模型，看损失曲线与过拟合 | [查看](/tinyllm/notebooks/first-run) |
| [第 2 章 · 张量与自动求导](./tensors-and-autograd.md) | 张量形状、广播、矩阵乘法、计算图与一次手算梯度 | [查看](/tinyllm/notebooks/tensors-and-autograd) |
| [第 3 章 · 架构演进：从 Transformer 到 GPT 再到今天](./architecture-evolution.md) | 三代架构怎样服务同一个目标：编码器-解码器、只有解码器、稀疏专家加混合注意力（Kimi K3）；每一代解决了什么、留下了什么 | [查看](/tinyllm/notebooks/architecture-evolution) |
| [第 4 章 · 文本与词元化](./tokenization.md) | Unicode 与字节、BPE 训练与编码、特殊 token、词表实验 | [查看](/tinyllm/notebooks/tokenization) |
| [第 5 章 · 词嵌入与输出层](./embeddings-and-output.md) | 查表、logits、交叉熵梯度、权重共享、Q/K/V 预览 | [查看](/tinyllm/notebooks/embeddings-and-output) |
| [第 6 章 · 自注意力](./self-attention.md) | Q/K/V、缩放点积、因果掩码、多头注意力；去掉注意力的对照实验与长度平方的代价 | [查看](/tinyllm/notebooks/self-attention) |
| [第 7 章 · 位置表示](./position-encoding.md) | 注意力为什么分不出先后；可学习绝对位置、正弦编码、RoPE；背诗与数位置两个对照实验，超过训练长度时的表现 | [查看](/tinyllm/notebooks/position-encoding) |
| [第 8 章 · 激活函数与门控前馈层](./activations-and-ffn.md) | ReLU/GELU/SiLU、SwiGLU 门控前馈层与参数量 | [查看](/tinyllm/notebooks/activations-and-ffn) |
| [第 9 章 · Transformer Block](./transformer-block.md) | 直接堆叠为什么越深越训不动；Pre-Norm 残差 Block、约 12d² 的参数量；逐层读出残差流里的预测 | [查看](/tinyllm/notebooks/transformer-block) |
| [第 10 章 · 初始化与残差路径](./initialization-and-residuals.md) | Xavier/He 初始化、残差直通路径、深度诊断 | [查看](/tinyllm/notebooks/initialization-and-residuals) |
| [第 11 章 · 归一化](./normalization.md) | LayerNorm、RMSNorm、ScaleNorm；Pre-Norm 与 Post-Norm | [查看](/tinyllm/notebooks/normalization) |
| [第 15 章 · 优化器](./optimizers.md) | SGD、Momentum、Adam、AdamW、Adafactor；参数组与优化器状态 | [查看](/tinyllm/notebooks/optimizers) |
| [第 18 章 · 数值精度与混合精度](./precision.md) | FP32/FP16/BF16、舍入与溢出、autocast；归一化与精度的关系 | [查看](/tinyllm/notebooks/precision) |

## 课程路线 {#roadmap}

### 第一部分 · 先跑起来

用最短的代码看到完整流水线。

- [第 1 章 · 先跑通一个最小 TinyLLM](./first-run.md)

### 第二部分 · 背景知识

动手搭模型之前的两样准备：张量与自动求导这门“工具”，以及大模型架构从 Transformer 到今天的来龙去脉。

- [第 2 章 · 张量与自动求导](./tensors-and-autograd.md)
- [第 3 章 · 架构演进：从 Transformer 到 GPT 再到今天](./architecture-evolution.md)

### 第三部分 · 沿数据流搭模型

顺着总图从上往下：文字变编号、编号变向量、注意力让向量互相看见、前馈层各自加工，最后装进 Block。

- [第 4 章 · 文本与词元化](./tokenization.md)
- [第 5 章 · 词嵌入与输出层](./embeddings-and-output.md)
- [第 6 章 · 自注意力](./self-attention.md)
- [第 7 章 · 位置表示](./position-encoding.md)
- [第 8 章 · 激活函数与门控前馈层](./activations-and-ffn.md)
- [第 9 章 · Transformer Block](./transformer-block.md)

### 第四部分 · 让深层网络训得动

Block 一叠深就训不动。残差、初始化、归一化三件工具解决这个问题，再组装出完整的 TinyLLM。

- [第 10 章 · 初始化与残差路径](./initialization-and-residuals.md)
- [第 11 章 · 归一化](./normalization.md)
- [第 12 章 · 完整 TinyLLM](./tinyllm-model.md)（规划中）

### 第五部分 · 数据与训练

数据、目标函数、优化器、学习率、精度与训练诊断；最后把模型做大：大规模训练的稳定性与稀疏专家（MoE）。

- [第 13 章 · 语料与数据管线](./data-pipeline.md)（规划中）
- [第 14 章 · 语言模型目标函数](./language-model-loss.md)（规划中）
- [第 15 章 · 优化器](./optimizers.md)
- [第 16 章 · 学习率策略](./learning-rate.md)（规划中）
- [第 17 章 · 正则化与泛化](./regularization.md)（规划中）
- [第 18 章 · 数值精度与混合精度](./precision.md)
- [第 19 章 · 梯度稳定与累积](./gradient-stability.md)（规划中）
- [第 20 章 · 训练循环与检查点](./training-loop.md)（规划中）
- [第 21 章 · 训练诊断与评估](./training-evaluation.md)（规划中）
- [第 22 章 · 大规模训练稳定性](./large-model-stability.md)（规划中）
- [第 23 章 · 稀疏专家（MoE）](./mixture-of-experts.md)（规划中）

### 第六部分 · 推理

模型训好以后怎样用、怎样用得省：逐字生成、推理效率与量化。

- [第 24 章 · 自回归生成](./generation.md)（规划中）
- [第 25 章 · 推理效率](./inference-efficiency.md)（规划中）
- [第 26 章 · 量化](./quantization.md)（规划中）

### 第七部分 · 后训练

在预训练模型上继续训练：指令微调、参数高效微调，再用 RLHF、DPO、GRPO 让回答符合人的偏好、学会推理。

- [第 27 章 · 指令微调](./instruction-finetuning.md)（规划中）
- [第 28 章 · 参数高效微调（LoRA）](./lora-finetuning.md)（规划中）
- [第 29 章 · RLHF：奖励模型与 PPO](./rlhf.md)（规划中）
- [第 30 章 · DPO 与 GRPO](./preference-alignment.md)（规划中）

### 第八部分 · 应用

模型参数不动，靠往上下文里放信息让它更有用。

- [第 31 章 · Agent 记忆与检索](./agent-memory.md)（规划中）

## 贯穿全书的主线选择 {#mainline-choices}

每章结尾都有一节“本章结论：TinyLLM 的选择”，回答三个问题：**主线具体选什么、为什么、什么情况下换方案**。下表把它们汇总在一起。这是从零训练一个小型、稠密、Decoder-only 语言模型的教学基线，不是“所有现代大模型的唯一最优配方”；规划章节的选择还要用相同数据、参数预算和训练条件验证。

<details>
<summary>展开全书主线选择汇总表（31 行）</summary>

| 章节 | 主线选择 | 主要理由与调整条件 |
| --- | --- | --- |
| [1 先跑通](./first-run.md) | 一个文件跑通字符级小模型：字符编号、可学习位置向量、3 层 Pre-RMSNorm Block、AdamW | 先看到完整流水线和损失曲线，再逐章替换成正式方案；它只用于建立整体印象，不是后续章节的基线配置。 |
| [2 自动求导](./tensors-and-autograd.md) | 用 PyTorch autograd 训练，手算小例子核验 | 保留正确的计算图；手写反传用于理解和梯度检查。 |
| [3 架构演进](./architecture-evolution.md) | 采用第二代的现代稠密解码器：只有解码器，因果注意力配 RoPE，Pre-Norm RMSNorm，SwiGLU | 每个零件都能在小模型上单独验证，也是第三代模型的骨架；MoE、混合注意力等放到后面的专题里对照。 |
| [4 词元化](./tokenization.md) | 训练可逆的字节级 BPE，固定特殊 token 协议 | 未见字符可退回字节；词表大小需按语种、语料和序列长度权衡。 |
| [5 嵌入与输出](./embeddings-and-output.md) | 可学习 token embedding；教学小模型先共享输入嵌入与输出权重 | 减少词表相关参数；若预算充足或共享约束影响效果，再试独立输出层。 |
| [6 自注意力](./self-attention.md) | 因果掩码的缩放点积注意力；先实现 MHA，再按推理预算切换 GQA | MHA 便于核对形状，GQA 可减少 KV cache；两者的头数与质量需一起验证。 |
| [7 位置表示](./position-encoding.md) | 对 Q/K 使用 RoPE | 把位置信息放进注意力计算；超过训练上下文不能只靠 RoPE 自动保证质量，须专门验证或扩展训练。 |
| [8 激活与 FFN](./activations-and-ffn.md) | 无偏置 SwiGLU：SiLU 门控，门控宽度先取约 `8d/3` | 相近参数预算下比较门控与普通 `4d` FFN；若追求最少算子或复现旧架构，可选 GELU/ReLU 普通 FFN。 |
| [9 Transformer Block](./transformer-block.md) | 注意力和 SwiGLU 各有一次 Pre-RMSNorm 与残差加法 | 保留直接的残差梯度路径；复杂的额外归一化只在诊断有需求时加入。 |
| [10 初始化与残差](./initialization-and-residuals.md) | 线性层先用 Xavier normal，嵌入用标准差 `1/√d` 的零均值正态；注意力输出和 FFN 输出投影再乘 `1/√(2L)`；采用 Pre-Norm 与两次残差相加 | 随机权重打破对称，较小的初始残差更新抑制深度累积；这是教学起点，仍需结合激活 RMS 与梯度诊断。 |
| [11 归一化](./normalization.md) | 每个注意力/前馈子层前用 RMSNorm，末尾再用一次 RMSNorm | 控制每个 token 的尺度，计算较简洁；若注意力分数失控，再评估 QK Norm；极深 Post-Norm 结构另研究 DeepNorm。 |
| [12 完整模型](./tinyllm-model.md) | 稠密 Decoder-only Transformer，最后 RMSNorm 接词表 logits | 先形成可训练、可生成的闭环；MoE 作为对照变体放在[第 23 章](./mixture-of-experts.md)。 |
| [13 数据](./data-pipeline.md) | 先清洗、去重，再按文档或来源划分训练/验证集并检查跨集合近重复 | 避免同源内容跨集合泄漏；混合比例取决于任务与语料质量。 |
| [14 损失](./language-model-loss.md) | 下一个 token 的交叉熵，只统计有效目标 token | 与自回归生成目标一致；有 padding 或 SFT 模板时显式掩码。 |
| [15 优化器](./optimizers.md) | AdamW；对归一化权重及偏置关闭 weight decay | 自适应更新适合基线，衰减与梯度惩罚分离；状态内存不足再比较 Adafactor 等。 |
| [16 学习率](./learning-rate.md) | 按优化器 step 短暂 warmup，随后 cosine decay | 降低初期大更新的风险，后期平滑降低步长；峰值和 warmup 长度依预算调参。 |
| [17 正则化](./regularization.md) | AdamW 的适度 weight decay；先不加 label smoothing，dropout 从 0 起测 | 先用验证集判断过拟合，再决定是否增加 dropout；低数据量下不能照搬大规模预训练设置。 |
| [18 精度](./precision.md) | 支持时用 BF16 混合精度，关键归约保持稳定实现；否则用 FP32 | BF16 指数范围较宽；缺 BF16 且需 FP16 时再配合 GradScaler。 |
| [19 梯度](./gradient-stability.md) | 记录梯度范数并按全局范数裁剪；需要大有效 batch 时做梯度累积 | 能定位并限制异常更新；裁剪阈值和累积步数不能脱离损失归一化设置。 |
| [20 训练循环](./training-loop.md) | 固定种子，明确 `zero_grad → forward → backward → clip → step → scheduler`，保存完整检查点 | 便于复现和中断恢复；梯度累积时只在更新步裁剪、更新学习率。 |
| [21 评估](./training-evaluation.md) | 先过拟合小 batch，再看独立验证集交叉熵/困惑度与生成样例 | 分开排查代码连通性、泛化和生成质量；比较困惑度需同一 tokenizer 与数据口径。 |
| [22 大规模稳定性](./large-model-stability.md) | 保留基础 Pre-Norm 配置并监测尺度；扩深/扩宽出现问题时才评估 μP、DeepNorm 等整套方案 | 这些方法涉及初始化、结构和学习率的联动，不能只替换一个常数；多卡训练时再引入数据并行等分布式方案。 |
| [23 MoE](./mixture-of-experts.md) | 主线保持稠密；MoE 作为对照变体，用相同数据和步数从头训练，并试稀疏升级 | 同样的计算量能放下更多参数，但要处理负载均衡与路由稳定；参数规模或推理成本成为瓶颈时再切换。 |
| [24 生成](./generation.md) | 可复现评估用贪心解码；开放式生成提供温度与 top-p | 评估稳定，交互时可调多样性；采样参数需随任务调节。 |
| [25 推理](./inference-efficiency.md) | 自回归 decode 使用 KV cache，分别测 prefill 与 decode；注意力优先用 PyTorch 的缩放点积注意力接口 | 避免每步重算前缀，并让框架选择 FlashAttention 等高效内核；长上下文和并发会增加显存，必要时配合 GQA。 |
| [26 量化](./quantization.md) | 训练沿用第 18 章的精度；部署受限时先做按通道或分组的 INT8 权重量化 | 压缩推理存储和带宽；每次量化都在同一验证集上比较困惑度与生成样例。 |
| [27 指令微调](./instruction-finetuning.md) | 在预训练模型上做 SFT，只对助手答案计算 loss | 让监督信号对应目标回答；模板和终止 token 必须与推理一致。 |
| [28 LoRA](./lora-finetuning.md) | 小模型先全参数微调；显存受限时再用 LoRA | LoRA 节省可训练参数及优化器状态，不减少基础权重的推理存储。 |
| [29 RLHF](./rlhf.md) | 在小任务上完整实现一遍：奖励模型 + PPO + KL 惩罚 | 理解偏好对齐的完整流程；四个模型、训练不稳，实际对齐方法见第 30 章。 |
| [30 DPO 与 GRPO](./preference-alignment.md) | 在 SFT 模型上先用 DPO；有能自动判分的任务时再用 GRPO | DPO 不需要单独的奖励模型；对齐后同时检查目标任务和原有能力。 |
| [31 Agent 记忆](./agent-memory.md) | 在模型外保存有来源和时间的文本事实，检索后放回上下文 | 参数和 KV cache 不会自动保存可更新的跨会话事实；按规模决定是否增加向量索引。 |

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
