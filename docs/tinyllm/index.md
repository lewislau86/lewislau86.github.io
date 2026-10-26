# TinyLLM 教程

从零实现一个能够训练、生成文本并接受基本评估的 TinyLLM。本项目既讲模型结构，也讲让模型<strong>可训练、稳定训练和正确评估</strong>所需的数据、初始化、优化、精度与工程方法。每章计划包含 Markdown 教案及对应的 PyTorch notebook。

<strong>如果你刚学完大学基础数学与 Python：</strong>先看“从哪里开始”和 Chapter 0 的“统一符号与总览”，再运行 notebook 的前几个实验。下方 26 章是整门课的地图，不要求现在认识每个名词；遇到 MoE、μP 等先知道它们是后续专题即可。

## 图表规范

本项目文档和配套 notebook 的交互式图表统一使用 <strong>Plotly</strong>。新增或修改章节时，优先使用 `plotly.graph_objects` 或 `plotly.express`，保留坐标轴标题、图例和必要的单位；不再引入 Matplotlib。

## 贯穿全书的主线选择

每章都要回答三个问题：<strong>TinyLLM 主线具体选什么、为什么、什么情况下换方案</strong>。下表是从零训练一个小型、稠密、Decoder-only 语言模型的教学基线，不是“所有现代大模型的唯一最优配方”。已完成章节会在正文解释取舍；规划章节先给出待实现的选择，后续实验还要用相同数据、参数预算和训练条件验证。模型规模、硬件、语种、上下文长度和推理吞吐需求变化时，应重新评估。

| 章节 | 主线选择 | 主要理由与调整条件 |
| --- | --- | --- |
| [0 归一化](chapter0_normalization.md) | 每个注意力/前馈子层前用 RMSNorm，末尾再用一次 RMSNorm | 控制每个 token 的尺度，计算较简洁；若注意力分数失控，再评估 QK Norm；极深 Post-Norm 结构另研究 DeepNorm。 |
| [1 自动求导](chapter1_pytorch_autograd.md) | 用 PyTorch autograd 训练，手算小例子核验 | 保留正确的计算图；手写反传用于理解和梯度检查。 |
| [2 初始化与残差](chapter2_initialization_residuals.md) | 线性层先用 Xavier normal，嵌入用标准差 `1/√d` 的零均值正态；注意力输出和 FFN 输出投影再乘 `1/√(2L)`；采用 Pre-Norm 与两次残差相加 | 随机权重打破对称，较小的初始残差更新抑制深度累积；这是教学起点，仍需结合激活 RMS 与梯度诊断。 |
| [3 激活与 FFN](chapter3_activations_ffn.md) | 无偏置 SwiGLU：SiLU 门控，门控宽度先取约 `8d/3` | 相近参数预算下比较门控与普通 `4d` FFN；若追求最少算子或复现旧架构，可选 GELU/ReLU 普通 FFN。 |
| [4 词元化](chapter4_tokenization.md) | 训练可逆的字节级 BPE，固定特殊 token 协议 | 未见字符可退回字节；词表大小需按语种、语料和序列长度权衡。 |
| [5 嵌入与输出](chapter5_embeddings_output.md) | 可学习 token embedding；教学小模型先共享输入嵌入与输出权重 | 减少词表相关参数；若预算充足或共享约束影响效果，再试独立输出层。 |
| [6 位置表示](chapter6_position_encoding.md) | 对 Q/K 使用 RoPE | 把位置信息放进注意力计算；超过训练上下文不能只靠 RoPE 自动保证质量，须专门验证或扩展训练。 |
| [7 自注意力](chapter7_self_attention.md) | 因果掩码的缩放点积注意力；先实现 MHA，再按推理预算切换 GQA | MHA 便于核对形状，GQA 可减少 KV cache；两者的头数与质量需一起验证。 |
| [8 Transformer Block](chapter8_transformer_block.md) | 注意力和 SwiGLU 各有一次 Pre-RMSNorm 与残差加法 | 保留直接的残差梯度路径；复杂的额外归一化只在诊断有需求时加入。 |
| [9 完整模型](chapter9_tinyllm_model.md) | 稠密 Decoder-only Transformer，最后 RMSNorm 接词表 logits | 先形成可训练、可生成的闭环；MoE 等结构留到有明确规模和吞吐需求时。 |
| [10 数据](chapter10_data_pipeline.md) | 先清洗、去重，再按文档或来源划分训练/验证集并检查跨集合近重复 | 避免同源内容跨集合泄漏；混合比例取决于任务与语料质量。 |
| [11 损失](chapter11_language_model_loss.md) | 下一个 token 的交叉熵，只统计有效目标 token | 与自回归生成目标一致；有 padding 或 SFT 模板时显式掩码。 |
| [12 优化器](chapter12_optimizers.md) | AdamW；对归一化权重及偏置关闭 weight decay | 自适应更新适合基线，衰减与梯度惩罚分离；状态内存不足再比较 Adafactor 等。 |
| [13 学习率](chapter13_learning_rate.md) | 按优化器 step 短暂 warmup，随后 cosine decay | 降低初期大更新的风险，后期平滑降低步长；峰值和 warmup 长度依预算调参。 |
| [14 正则化](chapter14_regularization.md) | AdamW 的适度 weight decay；先不加 label smoothing，dropout 从 0 起测 | 先用验证集判断过拟合，再决定是否增加 dropout；低数据量下不能照搬大规模预训练设置。 |
| [15 精度](chapter15_precision.md) | 支持时用 BF16 混合精度，关键归约保持稳定实现；否则用 FP32 | BF16 指数范围较宽；缺 BF16 且需 FP16 时再配合 GradScaler。 |
| [16 梯度](chapter16_gradient_stability.md) | 记录梯度范数并按全局范数裁剪；需要大有效 batch 时做梯度累积 | 能定位并限制异常更新；裁剪阈值和累积步数不能脱离损失归一化设置。 |
| [17 训练循环](chapter17_training_loop.md) | 固定种子，明确 `zero_grad → forward → backward → clip → step → scheduler`，保存完整检查点 | 便于复现和中断恢复；梯度累积时只在更新步裁剪、更新学习率。 |
| [18 评估](chapter18_training_evaluation.md) | 先过拟合小 batch，再看独立验证集交叉熵/困惑度与生成样例 | 分开排查代码连通性、泛化和生成质量；比较困惑度需同一 tokenizer 与数据口径。 |
| [19 生成](chapter19_autoregressive_generation.md) | 可复现评估用贪心解码；开放式生成提供温度与 top-p | 评估稳定，交互时可调多样性；采样参数需随任务调节。 |
| [20 推理](chapter20_inference_efficiency.md) | 自回归 decode 使用 KV cache，分别测 prefill 与 decode | 避免每步重算前缀；长上下文和并发会增加显存，必要时配合 GQA。 |
| [21 指令微调](chapter21_instruction_finetuning.md) | 在预训练模型上做 SFT，只对助手答案计算 loss | 让监督信号对应目标回答；模板和终止 token 必须与推理一致。 |
| [22 参数高效](chapter22_peft_sparsity.md) | 小模型先全参数训练；显存受限的微调再用 LoRA | LoRA 节省可训练参数及优化器状态；MoE 与剪枝有不同目标，不能统称为“更省”。 |
| [23 大规模稳定性](chapter23_large_model_stability.md) | 保留基础 Pre-Norm 配置并监测尺度；扩深/扩宽出现问题时才评估 μP、DeepNorm 等整套方案 | 这些方法涉及初始化、结构和学习率的联动，不能只替换一个常数。 |
| [24 扩展专题](chapter24_advanced_topics.md) | 优先使用 PyTorch 的缩放点积注意力接口；量化、分布式与对齐按目标单独引入 | 实现可以选择可用的高效内核；部署约束出现前不增加训练基线的复杂度。 |
| [25 Agent 记忆](chapter25_agent_memory.md) | 在模型外保存有来源和时间的文本事实，检索后放回上下文 | 参数和 KV cache 不会自动保存可更新的跨会话事实；按规模决定是否增加向量索引。 |

归一化、激活和位置编码的主线选择参考 [LLaMA](https://arxiv.org/abs/2302.13971) 与 [Llama 3](https://arxiv.org/abs/2407.21783) 的公开架构；门控前馈层见 [GLU 变体研究](https://arxiv.org/abs/2002.05202)，Pre-Norm 的初始化梯度分析见 [Xiong 等](https://arxiv.org/abs/2002.04745)。线性层的 Xavier 初始化见 [PyTorch 文档](https://docs.pytorch.org/docs/stable/nn.init.html)；残差投影按层数缩小借鉴 [nanoGPT 的具体实现](https://github.com/karpathy/nanoGPT/blob/master/model.py)，但这里从 Xavier 尺度出发，并非逐行复现 nanoGPT，更不是所有 LLM 共用的规则。GQA 的缓存权衡见 [GQA 论文](https://arxiv.org/abs/2305.13245)。

## 已完成章节

| 章节                                                                                                          | 内容                                                          | 状态                                                    |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------- |
| [Chapter 0：Normalization](chapter0_normalization.md) | LayerNorm、RMSNorm、ScaleNorm、QK Norm、DeepNorm；BF16/FP16 数值实验 | 教案与 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a> 已完成 |
| [Chapter 1：PyTorch 张量与自动求导](chapter1_pytorch_autograd.md) | 张量形状、广播、矩阵乘法、计算图、梯度与设备 | 教案与 <a href="/tinyllm/chapter1_PyTorch_Autograd/ch1.ipynb" download>ch1.ipynb</a> 已完成 |
| [Chapter 2：初始化与残差路径](chapter2_initialization_residuals.md) | 正态/截断正态、Xavier/He、Pre/Post-LN、残差缩放与梯度诊断 | 教案与 <a href="/tinyllm/chapter2_Initialization_Residuals/ch2.ipynb" download>ch2.ipynb</a> 已完成 |
| [Chapter 3：激活函数与门控前馈层](chapter3_activations_ffn.md) | ReLU/GELU/SiLU、SwiGLU、形状、参数量与合成拟合 | 教案与 <a href="/tinyllm/chapter3_Activations_FFN/ch3.ipynb" download>ch3.ipynb</a> 已完成 |
| [Chapter 4：文本与词元化](chapter4_tokenization.md) | Unicode/字节、BPE、特殊 token、训练标签、词表实验与近期研究 | 教案与 <a href="/tinyllm/chapter4_Tokenization/ch4.ipynb" download>ch4.ipynb</a> 已完成 |
| [Chapter 5：词嵌入与输出层](chapter5_embeddings_output.md) | token ID 查表、Q/K/V 与 KV cache、logits、权重共享及检索模型边界 | 教案与 <a href="/tinyllm/chapter5_Embeddings_Output/ch5.ipynb" download>ch5.ipynb</a> 已完成 |
| [Chapter 12：优化器](chapter12_optimizers.md) | SGD、Momentum、AdaGrad、RMSProp、Adam/AdamW、Adafactor；参数组与优化器状态 | 教案与 <a href="/tinyllm/chapter12_Optimizers/ch12.ipynb" download>ch12.ipynb</a> 已完成 |
| [Chapter 15：数值精度与混合精度](chapter15_precision.md)           | FP32/FP16/BF16、数值稳定、PyTorch CPU/CUDA/MPS 与可选 MLX 实验         | 教案与 <a href="/tinyllm/chapter15_Precision/ch15.ipynb" download>ch15.ipynb</a> 已完成  |

## 课程路线（规划） {#课程路线规划}

下面是<strong>教学目录</strong>，第 0、1、2、3、4、5、12、15 章已有完整教案与 notebook；其余章节以规划或专题导读为主。现有章节保留原编号。课程按“基础工具 → 构造模型 → 训练模型 → 使用与扩展”推进；实践中可以先完成最小语言模型，再回头深入各类训练策略。

### 第一阶段：张量与稳定训练基础

* [<strong>Chapter 0 · 归一化</strong>](chapter0_normalization.md)：已有 LayerNorm、RMSNorm、ScaleNorm、QK Norm、DeepNorm、Pre/Post-Norm 与 FP16/BF16 实验；后续补充 BatchNorm、GroupNorm 的对照。
* [<strong>Chapter 1 · PyTorch 张量与自动求导</strong>](chapter1_pytorch_autograd.md)：维度、广播、矩阵乘法、参数、计算图、反向传播、梯度检查。已有 PyTorch 基础可跳读。
* [<strong>Chapter 2 · 初始化与残差路径</strong>](chapter2_initialization_residuals.md)：已完成正态/截断正态、Xavier、He、残差、Pre/Post-LN、残差缩放及深度诊断实验。
* [<strong>Chapter 3 · 激活函数与门控前馈层</strong>](chapter3_activations_ffn.md)：已完成 ReLU、GELU、SiLU/Swish、SwiGLU 的曲线、梯度、参数量和小型拟合实验。

### 第二阶段：构造 Decoder-only 语言模型

* [<strong>Chapter 4 · 文本与词元化</strong>](chapter4_tokenization.md)：Unicode/字节、BPE 训练与编码、特殊 token、标签与掩码、词表实验；SuperBPE、TokSuite、CNF-MCE 研究导读。
* [<strong>Chapter 5 · 词嵌入与输出层</strong>](chapter5_embeddings_output.md)：已完成 token ID 查表、Q/K/V 与 KV 复用、logits、交叉熵梯度和 Weight Tying 实验；解释 Agent 为什么通常另用文本检索模型。
* [<strong>Chapter 6 · 位置表示</strong>](chapter6_position_encoding.md)：绝对位置编码、RoPE，位置作用于注意力的哪个环节。
* [<strong>Chapter 7 · 自注意力</strong>](chapter7_self_attention.md)：Q/K/V、缩放点积、因果 mask、多头注意力、张量转置与形状核对。
* [<strong>Chapter 8 · Transformer Block</strong>](chapter8_transformer_block.md)：注意力、前馈层、残差、归一化的连接方式；搭建多个 Block。
* [<strong>Chapter 9 · 完整 TinyLLM</strong>](chapter9_tinyllm_model.md)：组装 Decoder-only 模型，检查参数量、前向形状和下一 token logits。

### 第三阶段：数据、目标函数与训练

* [<strong>Chapter 10 · 语料与数据管线</strong>](chapter10_data_pipeline.md)：清洗、去重、训练/验证划分、shuffle、batching、bucketing、数据来源混合、数据泄漏检查。
* [<strong>Chapter 11 · 语言模型目标函数</strong>](chapter11_language_model_loss.md)：输入与目标错位、softmax、交叉熵、负对数似然、困惑度、padding 与 loss mask。
* [<strong>Chapter 12 · 优化器</strong>](chapter12_optimizers.md)：SGD、Momentum、Adam、AdamW、Adafactor；参数组、优化器状态、AdamW 与 L2 正则的区别。
* [<strong>Chapter 13 · 学习率策略</strong>](chapter13_learning_rate.md)：Warmup、Cosine Decay、Linear Decay、OneCycle；按 step 更新与学习率曲线。
* [<strong>Chapter 14 · 正则化与泛化</strong>](chapter14_regularization.md)：Weight Decay、L1/L2、Dropout、Label Smoothing、Early Stopping；训练损失与验证损失。区分通用方法与语言模型预训练的具体选择。
* [<strong>Chapter 15 · 数值精度与混合精度</strong>](chapter15_precision.md)：浮点数的范围与有效位、舍入/下溢/溢出、FP32/FP16/BF16、运算的中间精度、autocast、归一化与精度的关系；包含 PyTorch CPU/CUDA/MPS 和可选 MLX 实验。Chapter 0 只先讲归一化所需的精度基础。
* [<strong>Chapter 16 · 梯度稳定与累积</strong>](chapter16_gradient_stability.md)：Gradient Clipping、FP16 Loss Scaling（`GradScaler`）、梯度累积与梯度数值监测；解释它们在训练循环中的调用顺序。
* [<strong>Chapter 17 · 训练循环与检查点</strong>](chapter17_training_loop.md)：DataLoader、forward/backward、optimizer/scheduler step、随机种子、保存与恢复。
* [<strong>Chapter 18 · 训练诊断与评估</strong>](chapter18_training_evaluation.md)：先过拟合一个小 batch，再观察 loss、梯度、验证集困惑度和生成样例。

### 第四阶段：生成、效率和进阶结构

* [<strong>Chapter 19 · 自回归生成</strong>](chapter19_autoregressive_generation.md)：逐 token 解码、温度、top-k、top-p、停止条件与重复问题。
* [<strong>Chapter 20 · 推理效率</strong>](chapter20_inference_efficiency.md)：Prefill/decode、KV cache、前缀复用、注意力时间与显存开销、批量生成。
* [<strong>Chapter 21 · 指令微调</strong>](chapter21_instruction_finetuning.md)：预训练与监督微调、对话模板、只对答案计算 loss、基础评估。
* [<strong>Chapter 22 · 参数高效与稀疏结构</strong>](chapter22_peft_sparsity.md)：LoRA、MoE、结构化/非结构化稀疏、剪枝；分别说明节省的是训练参数、推理计算还是存储。
* [<strong>Chapter 23 · 大规模训练稳定性</strong>](chapter23_large_model_stability.md)：μP、DeepNorm/残差缩放、深度与宽度扩展；在 Chapter 0 的公式基础上比较完整训练配置。
* [<strong>Chapter 24 · 扩展专题</strong>](chapter24_advanced_topics.md)：GQA、FlashAttention、量化、分布式训练与对齐方法；根据课程进展拆为独立章节。
* [<strong>Chapter 25 · Agent 记忆与检索</strong>](chapter25_agent_memory.md)：历史如何写入、更新、检索并送回上下文；与模型参数、上下文和 KV cache 的边界。

## 四种常被叫作“记忆”的东西

问“模型记得什么”之前，先问<strong>信息保存在哪里、何时失效、能否跨会话复用</strong>：

| 保存位置 | 保存什么 | 生命周期 | 在推理中做什么 |
| --- | --- | --- | --- |
| 模型参数（含词嵌入） | 训练形成的权重 | 持续到换权重或训练更新 | 决定模型如何处理输入；通常不保存某次对话的原文 |
| 当前上下文 | 本次送入模型的 token | 随请求或上下文管理改变 | 提供当前可见的指令、问题与证据 |
| KV cache | 当前前缀在各注意力层算出的 K/V 张量 | 通常随生成请求结束；服务系统可在条件满足时复用前缀 | 避免每生成一个 token 就重算相同前缀的 K/V，占用推理内存 |
| Agent 外部记忆 | 历史文本、提取的事实及来源等 | 可跨请求保存，直到更新或删除 | 检索相关内容，并把可读文本放回当前上下文 |

一轮对话可能经过 <strong>外部记忆检索 → 组装上下文 → tokenizer → 模型前向计算与 KV cache → 逐 token 生成</strong>。KV cache 存的是计算结果，不会自动判断哪些事实值得长期保留；外部记忆即使保存在向量库里，也要先检索并进入上下文，模型才能在这一轮使用。详见 [Chapter 20](chapter20_inference_efficiency.md) 和 [Chapter 25](chapter25_agent_memory.md)。

## 从哪里开始

<strong>最小闭环</strong>：准备文本 → 词元化（把文字变成整数编号）→ 构建 Decoder-only 模型（只能看当前及之前的词）→ 训练它预测下一个词元 → 用没训练过的数据验证 → 逐词生成文本。第一阶段和第三阶段中的许多方法会让这个闭环更稳、更可解释，但不要求在第一个小模型里一次用完所有技术。第一阶段第 0 至 3 章已有归一化、自动求导、初始化/残差和门控前馈层实验；后续章节会沿用“公式/参数解释 → PyTorch 调用 → 可复现实验 → 如何读结果”的教案格式。

## 其他

* <strong>Pre-LN/Post-LN 是归一化放置方式</strong>，Residual Connection 是结构，RMSNorm 是具体归一化算法；三者可以组合，不应作为互斥选项。
* <strong>Weight Decay 与 L2 惩罚不总等价</strong>。特别是在 AdamW 中，权重衰减与梯度中的 L2 项是不同做法，课程会用参数更新算例对照。[PyTorch AdamW 文档](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html) 提供了算法定义。
* <strong>Label Smoothing、Early Stopping、Dropout 并非每个 LLM 预训练都必须采用</strong>；要结合目标函数、训练预算与验证策略判断。
* <strong>Gradient Scaling 是泛称，Loss Scaling 是其中用于缩放 loss/梯度的具体做法</strong>，在 FP16 混合精度训练中特别常见。梯度裁剪限制梯度范数，梯度累积合并多个 micro-batch；这三类操作的目的与调用顺序需要分别解释。
* <strong>BatchNorm/GroupNorm 值得对照学习</strong>，但本项目的 Decoder-only 主线优先理解逐 token 的 LayerNorm/RMSNorm；[PyTorch 归一化 API](https://docs.pytorch.org/docs/stable/nn.html#normalization-layers) 可用于检查各层统计维度。

数据去重和混合不只是加载技巧，也会影响语言模型质量与评估可信度，可参见 [Deduplicating Training Data Makes Language Models Better](https://arxiv.org/abs/2107.06499) 和 [DataComp-LM](https://arxiv.org/abs/2406.11794)。训练循环的基础调用顺序可参考 [PyTorch 官方优化教程](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial)。
