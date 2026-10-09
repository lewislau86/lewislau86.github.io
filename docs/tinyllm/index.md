# TinyLLM 教程

从零实现一个能够训练、生成文本并接受基本评估的 TinyLLM。本项目既讲模型结构，也讲让模型<strong>可训练、稳定训练和正确评估</strong>所需的数据、初始化、优化、精度与工程方法。每章计划包含 Markdown 教案及对应的 PyTorch notebook。

<strong>如果你刚学完大学基础数学与 Python：</strong>先看“从哪里开始”和 Chapter 0 中的“小词典”，再运行 notebook 的前几个实验。下方 25 章是整门课的地图，不要求现在认识每个名词；遇到 MoE、μP 等先知道它们是后续专题即可。

## 已完成章节

| 章节                                                                                                          | 内容                                                          | 状态                                                    |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------- |
| [Chapter 0：Normalization](chapter0_normalization.md) | LayerNorm、RMSNorm、ScaleNorm、QK Norm、DeepNorm；BF16/FP16 数值实验 | 教案与 <a href="/tinyllm/chapter0_Normalization/ch0.ipynb" download>ch0.ipynb</a> 已完成 |
| [Chapter 1：PyTorch 张量与自动求导](chapter1_pytorch_autograd.md) | 张量形状、广播、矩阵乘法、计算图、梯度与设备 | 教案与 <a href="/tinyllm/chapter1_PyTorch_Autograd/ch1.ipynb" download>ch1.ipynb</a> 已完成 |
| [Chapter 15：数值精度与混合精度](chapter15_precision.md)           | FP32/FP16/BF16、数值稳定、PyTorch CPU/CUDA/MPS 与可选 MLX 实验         | 教案与 <a href="/tinyllm/chapter15_Precision/ch15.ipynb" download>ch15.ipynb</a> 已完成  |

## 课程路线（规划） {#课程路线规划}

下面是<strong>教学目录</strong>，未在上表列出的章节只是规划。现有 Chapter 0、Chapter 1、Chapter 15 保留原编号。课程按“基础工具 → 构造模型 → 训练模型 → 使用与扩展”推进；实践中可以先完成最小语言模型，再回头深入各类训练策略。

### 第一阶段：张量与稳定训练基础

* [<strong>Chapter 0 · 归一化</strong>](chapter0_normalization.md)：已有 LayerNorm、RMSNorm、ScaleNorm、QK Norm、DeepNorm、Pre/Post-Norm 与 FP16/BF16 实验；后续补充 BatchNorm、GroupNorm 的对照。
* [<strong>Chapter 1 · PyTorch 张量与自动求导</strong>](chapter1_pytorch_autograd.md)：维度、广播、矩阵乘法、参数、计算图、反向传播、梯度检查。已有 PyTorch 基础可跳读。
* [<strong>Chapter 2 · 初始化与残差路径</strong>](chapter2_initialization_residuals.md)：正态/截断正态、Xavier、He 初始化；Residual Connection、Pre/Post-Norm、残差缩放、深度增加时的激活和梯度。
* [<strong>Chapter 3 · 激活函数与门控前馈层</strong>](chapter3_activations_ffn.md)：ReLU、GELU、SiLU/Swish、SwiGLU；函数曲线、梯度、参数量与 MLP 结构。

### 第二阶段：构造 Decoder-only 语言模型

* [<strong>Chapter 4 · 文本与词元化</strong>](chapter4_tokenization.md)：Unicode/字节、词表、BPE、特殊 token、编码和解码。
* [<strong>Chapter 5 · 词嵌入与输出层</strong>](chapter5_embeddings_output.md)：token ID 到向量、logits、输出投影、Weight Tying（输入输出权重共享）。
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
* [<strong>Chapter 20 · 推理效率</strong>](chapter20_inference_efficiency.md)：Prefill/decode、KV cache、注意力时间与显存开销、批量生成。
* [<strong>Chapter 21 · 指令微调</strong>](chapter21_instruction_finetuning.md)：预训练与监督微调、对话模板、只对答案计算 loss、基础评估。
* [<strong>Chapter 22 · 参数高效与稀疏结构</strong>](chapter22_peft_sparsity.md)：LoRA、MoE、结构化/非结构化稀疏、剪枝；分别说明节省的是训练参数、推理计算还是存储。
* [<strong>Chapter 23 · 大规模训练稳定性</strong>](chapter23_large_model_stability.md)：μP、DeepNorm/残差缩放、深度与宽度扩展；在 Chapter 0 的公式基础上比较完整训练配置。
* [<strong>Chapter 24 · 扩展专题</strong>](chapter24_advanced_topics.md)：GQA、FlashAttention、量化、分布式训练、RAG 与对齐方法；根据课程进展拆为独立章节。

## 从哪里开始

<strong>最小闭环</strong>：准备文本 → 词元化（把文字变成整数编号）→ 构建 Decoder-only 模型（只能看当前及之前的词）→ 训练它预测下一个词元 → 用没训练过的数据验证 → 逐词生成文本。第一阶段和第三阶段中的许多方法会让这个闭环更稳、更可解释，但不要求在第一个小模型里一次用完所有技术。Chapter 0 已提供归一化理论与固定数据实验；后续章节会沿用“公式/参数解释 → PyTorch 调用 → 可复现实验 → 如何读结果”的教案格式。

## 其他

* <strong>Pre-LN/Post-LN 是归一化放置方式</strong>，Residual Connection 是结构，RMSNorm 是具体归一化算法；三者可以组合，不应作为互斥选项。
* <strong>Weight Decay 与 L2 惩罚不总等价</strong>。特别是在 AdamW 中，权重衰减与梯度中的 L2 项是不同做法，课程会用参数更新算例对照。[PyTorch AdamW 文档](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html) 提供了算法定义。
* <strong>Label Smoothing、Early Stopping、Dropout 并非每个 LLM 预训练都必须采用</strong>；要结合目标函数、训练预算与验证策略判断。
* <strong>Gradient Scaling 是泛称，Loss Scaling 是其中用于缩放 loss/梯度的具体做法</strong>，在 FP16 混合精度训练中特别常见。梯度裁剪限制梯度范数，梯度累积合并多个 micro-batch；这三类操作的目的与调用顺序需要分别解释。
* <strong>BatchNorm/GroupNorm 值得对照学习</strong>，但本项目的 Decoder-only 主线优先理解逐 token 的 LayerNorm/RMSNorm；[PyTorch 归一化 API](https://docs.pytorch.org/docs/stable/nn.html#normalization-layers) 可用于检查各层统计维度。

数据去重和混合不只是加载技巧，也会影响语言模型质量与评估可信度，可参见 [Deduplicating Training Data Makes Language Models Better](https://arxiv.org/abs/2107.06499) 和 [DataComp-LM](https://arxiv.org/abs/2406.11794)。训练循环的基础调用顺序可参考 [PyTorch 官方优化教程](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial)。
