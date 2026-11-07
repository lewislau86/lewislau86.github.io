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

::: tip 只有半小时？
先按[实验环境](./setup.md)装好 PyTorch，再读[30 分钟快速体验](./quickstart.md)：一个独立脚本，八步量出词表、嵌入、注意力、位置、损失、梯度、训练和生成的具体数字，配一张损失曲线图。不想深入的读者走完它就够了；想深入某一块，那一页按兴趣列了从哪章读起。不需要先读任何一章。
:::

## 从哪里开始

如果你刚学完大学基础数学与 Python，按顺序读即可：

1. **先读[第 1 章](./first-run.md)，把整条流水线跑起来。** 半分钟训练一个会背唐诗的小模型，看到损失怎样下降、输出怎样从乱码变成诗句。这一章不讲原理，只建立整体印象。
2. **再读第 2、3 章，补两样背景。** [第 2 章](./tensors-and-autograd.md)备好工具：张量、形状和自动求导，后面每一章都要用；[第 3 章](./architecture-evolution.md)讲架构的来历：从翻译用的 Transformer，到只有解码器的 GPT，再到今天的稀疏混合架构，TinyLLM 的每个零件都能在这里找到出处。
3. **然后顺着总图从上往下搭模型（第 4～9 章）。** 文字变编号、编号变向量、注意力让向量互相看见、前馈层各自加工，最后装进 Block。
4. **把 Block 叠深，它会训不动；第 10～12 章修好它。** 残差、初始化、归一化三件工具让深层网络稳定，再组装出完整的 TinyLLM；第 13 章把同一份代码搬到 GPU 上放大训练。
5. **之后是数据与训练（第 14～25 章），再到推理（第 26～33 章）、后训练（第 34～37 章）和应用（第 38 章）。** 已成文的章节之间如果隔着规划中的章节，可以先跳过，侧栏的“下一篇”会直接带你到下一章已完成的内容。

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
| [第 12 章 · 完整 TinyLLM](./tinyllm-model.md) | 把 BPE、RoPE、SwiGLU、Pre-RMSNorm、初始化与权重共享装成一个模型；先估后数参数量、三项体检；固定数据划分、batch 计划与验证口径，训练出后半本书的基线 | [查看](/tinyllm/notebooks/tinyllm-model) |
| [第 13 章 · TinyLLM 在 GPU 上完整实现](./gpu-training.md) | 模型代码不变，换配置和训练循环：显存估算、BF16、梯度累积、学习率调度、检查点；点出 GPU 上的七个优化点 | [查看](/tinyllm/notebooks/gpu-training) |
| [第 14 章 · 语料与数据管线](./data-pipeline.md) | 跟着一首诗从原始记录走到 batch：清洗漏斗、先繁转简再去重、字二元组重合度找近重复、按哈希划分；在统一语料上查出 36 首漏网的近亲并做泄漏实验；补齐、分桶与拼接成流，batch 计划的覆盖率，喂数据的速度 | [查看](/tinyllm/notebooks/data-pipeline) |
| [第 15 章 · 语言模型目标函数](./language-model-loss.md) | 拆开第 12 章的验证损失 5.579：错位出题、整首诗的概率与下溢、log-sum-exp、nats/比特/困惑度的换算；padding 与梯度累积的分母、`<eos>` 的监督；按题型拆损失、可靠性图，label smoothing 与 z-loss | [查看](/tinyllm/notebooks/language-model-loss) |
| [第 16 章 · 优化器](./optimizers.md) | SGD、Momentum、Adam、AdamW、Adafactor；参数组与优化器状态 | [查看](/tinyllm/notebooks/optimizers) |
| [第 17 章 · 学习率策略](./learning-rate.md) | 学习率调度写成按优化器步调用的函数；代理模型上 17 次对照（3 个种子）：固定学习率扫描、加余弦反而变差、衰减要配更高峰值、WSD 与余弦、去掉 warmup；损失曲线的“下台阶”，与 batch 和宽度的关系 | [查看](/tinyllm/notebooks/learning-rate) |
| [第 18 章 · 正则化与泛化](./regularization.md) | 只给 300 首诗让模型过拟合，29 次对照（3 个种子）：更多数据、提前停止、weight decay 的时间尺度 1/(lr·wd)、dropout 的三个位置与 train/eval 模式、label smoothing；用验证集挑、用测试集报；回到全部数据，同样的手段反而变差 | [查看](/tinyllm/notebooks/regularization) |
| [第 19 章 · 数值精度与混合精度](./precision.md) | FP32/FP16/BF16、舍入与溢出、autocast；归一化与精度的关系 | [查看](/tinyllm/notebooks/precision) |
| [第 20 章 · 梯度稳定与累积](./gradient-stability.md) | 全局梯度范数与两种裁剪；代理模型 3 个种子：AdamW 下裁剪阈值改一百倍几乎无影响，一次 1000 倍的梯度尖峰不裁剪就毁掉训练；梯度累积的一步对拍，FP16 的下溢、`GradScaler` 的动态调整与先 `unscale_` 后裁剪；训练时该盯的监测量 | [查看](/tinyllm/notebooks/gradient-stability) |
| [第 21 章 · 训练循环与检查点](./training-loop.md) | `Dataset`、`Sampler`、`DataLoader` 与按 epoch 组织的训练循环；检查点存模型、优化器、调度器、训练进度、随机数状态和配置，断电后接着训和一口气训完逐位相同；找出 DataLoader 偷用全局随机数的坑，逐项去掉一样看偏差；原子保存、只留最新几个、`weights_only` | [查看](/tinyllm/notebooks/training-loop) |
| [第 22 章 · 训练诊断与评估](./training-evaluation.md) | 故意埋 6 个常见 bug（漏因果掩码、标签没错位、双重 softmax、忘了清梯度、每步同一个 batch、初始化放大），用初始损失、单 batch 过拟合、因果性、训练/验证曲线、生成样例、梯度范数 6 项检查去抓；验证损失的 bootstrap 误差与配对比较；损失与生成质量的关系 | [查看](/tinyllm/notebooks/training-evaluation) |
| [第 23 章 · 超参数与自动化调参](./hyperparameter-tuning.md) | 5 个种子量噪声底线（σ = 0.018）；每次只改一个超参数排敏感度（学习率、batch 最敏感，β2、衰减比例在噪声以内）；batch 与学习率的耦合；同样约 9 次训练的预算比较网格、随机、逐轮淘汰（借 WSD 分叉衰减评估）；按中间结果挑的陷阱、赢家换种子复核；TPE、PBT 与从小到大的迁移 | [查看](/tinyllm/notebooks/hyperparameter-tuning) |
| [第 24 章 · 大规模训练稳定性](./large-model-stability.md) | 在小模型上用大学习率复现注意力分数失控（从 36 涨到 22 万），QK Norm 压住它、拓宽可用学习率，z-loss 在这里不起作用；DeepNorm；μP 让最佳学习率不随宽度漂移；ZeRO/FSDP 显存账、激活重计算、数据并行与张量并行的模拟；放大以后的稳定性清单 | [查看](/tinyllm/notebooks/large-model-stability) |
| [第 25 章 · 稀疏专家（MoE）](./mixture-of-experts.md) | 路由器、top-k 与总参数/激活参数；与三种稠密模型的 3 种子对照；负载均衡（辅助损失与无辅助损失的偏置）；路由器自己学出“标点各用一个专家”；稀疏升级把稠密模型无损改成 MoE；专题：能否后期改成 MoE、使用体验的差别、厂商为何选 MoE（以小米 MiMo 为例） | [查看](/tinyllm/notebooks/mixture-of-experts) |
| [第 26 章 · 自回归生成](./generation.md) | 温度、top-k 与 top-p、重复惩罚、随机种子与停止条件；把格式写进掩码的约束解码，同一批请求格式合法率从 0/12 到 12/12 | [查看](/tinyllm/notebooks/generation) |
| [第 27 章 · 推理效率](./inference-efficiency.md) | prefill 与 decode 两段的耗时分开量；KV cache 省下的投影行数与缓存字节数；TTFT、TPOT、ITL、E2EL 与 goodput；chunked prefill 与一次算完逐元素一致 | [查看](/tinyllm/notebooks/inference-efficiency) |
| [第 28 章 · 注意力内核与算子融合](./attention-kernels.md) | 用挂在算子分发上的记账员量出朴素注意力的峰值与读写；手写 online softmax 与分块注意力，和 SDPA 对齐；块大小与 K、V 重读；反向只存每行一个 lse；torch.compile 把一层 37 个算子融合成 6 个内核 | [查看](/tinyllm/notebooks/attention-kernels) |
| [第 29 章 · 量化](./quantization.md) | 对称与非对称量化；按张量、按通道、分组的误差与位数；INT8/INT4 在 3 个种子上的损失、KL 与一致率；嵌入表最敏感；激活离群通道与 SmoothQuant；KV cache 量化；真实模型的体积与带宽上限 | [查看](/tinyllm/notebooks/quantization) |

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
- [第 12 章 · 完整 TinyLLM](./tinyllm-model.md)
- [第 13 章 · TinyLLM 在 GPU 上完整实现](./gpu-training.md)：同一份代码放大配置，在 GPU 上完整训练，并点出后面要做的 GPU 优化

### 第五部分 · 数据与训练

数据、目标函数、优化器、学习率、正则化、精度与训练诊断，再把这些超参数放在一起系统地调；最后把模型做大：大规模训练的稳定性与稀疏专家（MoE）。

- [第 14 章 · 语料与数据管线](./data-pipeline.md)
- [第 15 章 · 语言模型目标函数](./language-model-loss.md)
- [第 16 章 · 优化器](./optimizers.md)
- [第 17 章 · 学习率策略](./learning-rate.md)
- [第 18 章 · 正则化与泛化](./regularization.md)
- [第 19 章 · 数值精度与混合精度](./precision.md)
- [第 20 章 · 梯度稳定与累积](./gradient-stability.md)
- [第 21 章 · 训练循环与检查点](./training-loop.md)
- [第 22 章 · 训练诊断与评估](./training-evaluation.md)
- [第 23 章 · 超参数与自动化调参](./hyperparameter-tuning.md)
- [第 24 章 · 大规模训练稳定性](./large-model-stability.md)
- [第 25 章 · 稀疏专家（MoE）](./mixture-of-experts.md)

### 第六部分 · 推理

模型训好以后怎样用、怎样用得省。前五章只看一个请求：每一步怎样选字，怎样不重算前文，注意力内核为什么快，怎样少搬字节，怎样少走几步。后三章处理很多请求同时来的情况：怎样排进同一批，显存里的 KV 怎样分配和复用，最后把各项优化逐一对照，并接上服务。

- [第 26 章 · 自回归生成](./generation.md)
- [第 27 章 · 推理效率：prefill、decode 与 KV cache](./inference-efficiency.md)
- [第 28 章 · 注意力内核与算子融合](./attention-kernels.md)
- [第 29 章 · 量化](./quantization.md)
- [第 30 章 · 投机解码](./speculative-decoding.md)（规划中）
- [第 31 章 · 批处理与调度](./batching.md)（规划中）
- [第 32 章 · KV 显存管理：分页与前缀缓存](./kv-memory.md)（规划中）
- [第 33 章 · 推理优化：逐项对照与推理服务](./inference-optimization.md)（规划中）

### 第七部分 · 后训练

在预训练模型上继续训练：指令微调、参数高效微调，再用 RLHF、DPO、GRPO 让回答符合人的偏好、学会推理。

- [第 34 章 · 指令微调](./instruction-finetuning.md)（规划中）
- [第 35 章 · 参数高效微调（LoRA）](./lora-finetuning.md)（规划中）
- [第 36 章 · RLHF：奖励模型与 PPO](./rlhf.md)（规划中）
- [第 37 章 · DPO 与 GRPO](./preference-alignment.md)（规划中）

### 第八部分 · 应用

模型参数不动，靠往上下文里放信息让它更有用。

- [第 38 章 · LLM 和 Agent 的交互](./llm-agent-interaction.md)（规划中）

## 贯穿全书的主线选择 {#mainline-choices}

每章结尾都有一节“本章结论：TinyLLM 的选择”，回答三个问题：**主线具体选什么、为什么、什么情况下换方案**。下表把它们汇总在一起。这是从零训练一个小型、稠密、Decoder-only 语言模型的教学基线，不是“所有现代大模型的唯一最优配方”；规划章节的选择还要用相同数据、参数预算和训练条件验证。

<details>
<summary>展开全书主线选择汇总表（37 行）</summary>

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
| [12 完整模型](./tinyllm-model.md) | 稠密 Decoder-only Transformer，最后 RMSNorm 接词表 logits | 先形成可训练、可生成的闭环；MoE 作为对照变体放在[第 25 章](./mixture-of-experts.md)。 |
| [13 GPU 完整实现](./gpu-training.md) | 同一份模型代码只改配置，在 GPU 上用 BF16 autocast、SDPA 注意力和 AdamW 完整训练 | 先保证结果与 CPU 基线口径一致，再逐项打开 GPU 优化；每一项都要单独测吞吐和显存，不叠加后再归功于某一项。 |
| [14 数据](./data-pipeline.md) | 逐条规则清洗，先归一化（繁转简）再去重，用字二元组重合度去近重复；按正文哈希固定划分，划分后再做泄漏检查；整个训练集预先分词、拼成用 `<eos>` 隔开的 token 流 | 哈希划分不随语料增减而变；不补齐、不浪费计算。长文档或多轮训练时再评估文档掩码与按轮打乱；混合比例取决于任务与语料质量。 |
| [15 损失](./language-model-loss.md) | 下一个 token 的交叉熵，`F.cross_entropy` 直接吃原始 logits，按有效 token 数平均；`<eos>` 计入，`<pad>` 用 -100 屏蔽；梯度累积先求和、最后除以总有效 token 数；不用 label smoothing | 与自回归生成目标一致，分母不随 batch 切法变化；指令微调只算回答部分，模型放大、换低精度后再考虑 z-loss。 |
| [16 优化器](./optimizers.md) | AdamW；对归一化权重及偏置关闭 weight decay | 自适应更新适合基线，衰减与梯度惩罚分离；状态内存不足再比较 Adafactor 等。 |
| [17 学习率](./learning-rate.md) | 按优化器步调度：线性 warmup 后默认 WSD（最后约 20% 线性降到 0）；总步数确定、只训练一次时也可用 warmup + 余弦降到峰值的 10%；加衰减后重新调峰值 | 代理模型 3 个种子：衰减要配更高峰值才有好处，WSD 最好，去掉 warmup 变差；WSD 便于从检查点继续训练。换 batch 或宽度要重扫峰值。 |
| [18 正则化](./regularization.md) | 主线预训练不加 dropout、不用 label smoothing；AdamW 对矩阵权重保留 `weight_decay=0.1`；按验证损失保留最好的检查点，测试集只报告一次 | 代理模型 3 个种子：300 首诗过 20 遍时，weight decay 3 与 dropout 0.3 明显改善，但不如把数据翻两番；全部数据只过一遍时，同样的手段都变差。数据有限、多遍训练或微调时，先加数据，再按 1/(lr·wd) 调 weight decay、试 dropout。 |
| [19 精度](./precision.md) | 支持时用 BF16 混合精度，关键归约保持稳定实现；否则用 FP32 | BF16 指数范围较宽；缺 BF16 且需 FP16 时再配合 GradScaler。 |
| [20 梯度](./gradient-stability.md) | 每个优化器步按全局范数裁到 1.0 并记录裁剪前范数；梯度累积时只在累积完以后裁剪、更新、推进调度器各一次；优先 BF16，FP16 才用 `GradScaler` 且先 `unscale_` 再裁剪 | 代理模型 3 个种子：AdamW 下阈值几乎不影响结果，但裁剪能完全挡住一次 1000 倍的梯度尖峰；累积写错时最终损失看不出来，要用一步对拍检查。用 SGD 时阈值直接决定步长，要和学习率一起调。 |
| [21 训练循环](./training-loop.md) | 每步 `zero_grad → 前向 → backward → 裁剪 → optimizer.step → scheduler.step`，用 progress（step、epoch、epoch 内 batch 数）记进度；数据顺序只由 (种子, epoch) 决定，DataLoader 用自己的 generator；检查点存模型、优化器、调度器、进度、随机数状态与配置，先写临时文件再替换 | 代理模型单种子：完整恢复与一口气训完逐位相同；缺任何一样都会偏离，缺调度器还会让 WSD 衰减段消失。GPU 上另存每张卡的随机数状态，需要逐位复现时打开确定性算法。 |
| [22 评估](./training-evaluation.md) | 训练前先跑初始损失 ≈ ln V、因果性测试、单 batch 过拟合（用同一份训练代码）；训练中记训练/验证损失、梯度范数与学习率；训练后看固定提示词的生成样例和简单结构指标；比较模型时在同一验证集上配对 bootstrap，并结合多个种子 | 代理模型单种子：6 个 bug 没有一项检查能全部抓住，训练前三项几秒内抓住其中 4 个；有 bug 的验证损失可以比正确代码低几十倍；配对后差的区间约为单独区间的八分之一。阈值随模型和训练时长重定。 |
| [23 调参](./hyperparameter-tuning.md) | 先用 3～5 个种子量噪声底线，小于约 2σ 不算改进；预算先给学习率（连同 batch 与步数），再确认 warmup、weight decay，β2 与衰减比例用默认值；自动搜索用随机搜索，配置多时用逐轮淘汰并在 WSD 峰值阶段分叉衰减后比较；赢家换新种子复核，测试集只报告一次 | 代理模型：学习率偏离 26.5σ、batch 16.3σ，β2 与衰减比例在 1.2σ 以内；同预算下随机搜索与逐轮淘汰好于网格，但复核后都没有可靠地超过第 17 章的主线。大模型上数值要重扫或改用 μP（第 24 章）。 |
| [24 大规模稳定性](./large-model-stability.md) | 主线保持 Pre-RMSNorm 与残差输出缩放，记录注意力分数与输出 logits 的尺度；放大时先加 QK Norm，跨宽度迁移学习率时整套采用 μP，输出 logits 漂移或低精度时再加 z-loss；显存不够按激活重计算 → ZeRO-1/2 → FSDP → 张量并行的顺序考虑 | 代理模型单种子：大学习率下 QK Norm 让 5 个学习率上的平均验证损失从 5.304 降到 5.034，主线学习率上无差别；SP 最佳学习率随宽度从 3e-2 移到 3e-3，μP 都是 1e-2；重计算省九成激活、梯度逐位相同。 |
| [25 MoE](./mixture-of-experts.md) | 主线保持稠密；MoE 作为对照变体，前馈层换成路由器加 SwiGLU 专家、选 top-k、按归一化分数加权，负载均衡用无辅助损失的偏置；已有稠密模型时先用稀疏升级 | 代理模型 3 个种子：MoE 与激活参数相同的稠密模型打平，优势要在数据多、模型大时才显现；偏置均衡把最忙专家从 44% 压到 14%；稀疏升级输出与稠密只差 3.3e-6。显存看总参数、速度看激活参数：端侧选稠密，云端高并发选 MoE。 |
| [26 生成](./generation.md) | 可复现评估用贪心解码；开放式生成提供温度与 top-p，并固定种子 | 评估稳定，交互时可调多样性；采样参数需随任务调节。 |
| [27 推理效率](./inference-efficiency.md) | 自回归 decode 用 KV cache，分别测 prefill 与 decode；注意力用 PyTorch 的缩放点积注意力接口 | 避免每步重算前缀；长上下文和并发会增加显存，必要时配合 GQA。报告以“前向次数、投影行数、缓存字节”这类与硬件无关的量为主，墙钟时间标注环境。 |
| [28 注意力内核](./attention-kernels.md) | 注意力调用 `F.scaled_dot_product_attention`，让 PyTorch 选 FlashAttention 一类的分块内核；逐元素小算子交给 `torch.compile` 融合；手写的朴素与分块版本只用于理解和核对 | 长度 4096 时朴素写法峰值 536 MiB、读写 2120 MiB，SDPA 峰值 2.06 MiB；分块读写约 $T^2 d/B$，块大小受片上存储限制。需要 SDPA 不支持的掩码时换可编程内核或数学实现，先核对结果再在 GPU 上测速度与显存。 |
| [29 量化](./quantization.md) | 训练和评估不量化；部署受限时先做 INT8 按通道的权重量化，再到 INT4 分组 32（输出层和嵌入表保留高精度）；KV cache 先 INT8 | 3 个种子：INT8 损失变化在 ±0.0002 以内；INT4 按张量涨 0.032，分组 32 只涨 0.008；KV INT4 涨 0.004。要压到 4 位以下或要求更高时换 GPTQ、AWQ 等带校准的方法；速度要在有整数内核的硬件上测。 |
| [30 投机解码](./speculative-decoding.md) | 贪心解码下用“起草 → 验证”一次接受多个 token，并要求输出与基线逐 token 一致 | 只在起草模型和目标模型接近时有效；接受率要实测，采样模式下必须用拒绝采样才不改变分布。 |
| [31 批处理](./batching.md) | 主线先单请求；多个请求时用连续批处理按 token 步调度，并记录每个请求的等待时间 | 短请求不必等最长的那个；chunked prefill 能减少长提示词对其他请求的阻塞，代价是调度开销。 |
| [32 KV 显存管理](./kv-memory.md) | 缓存按固定大小的块分配，用一张块表拼出逻辑序列；相同前缀的块共享 | 分页解决碎片与超配，前缀共享解决重复计算；两者都要淘汰策略，命中率必须按工作负载实测。 |
| [33 推理优化](./inference-optimization.md) | 以第 27 章的 KV cache 为基线，逐项单独打开前面的优化并各测一次 | 每项都用同一组请求测首字延迟、每 token 延迟和吞吐；输出必须与基线一致（或在同一验证集上质量不降），几项叠加的提升不归给其中某一项。 |
| [34 指令微调](./instruction-finetuning.md) | 在预训练模型上做 SFT，只对助手答案计算 loss | 让监督信号对应目标回答；模板和终止 token 必须与推理一致。 |
| [35 LoRA](./lora-finetuning.md) | 小模型先全参数微调；显存受限时再用 LoRA | LoRA 节省可训练参数及优化器状态，不减少基础权重的推理存储。 |
| [36 RLHF](./rlhf.md) | 在小任务上完整实现一遍：奖励模型 + PPO + KL 惩罚 | 理解偏好对齐的完整流程；四个模型、训练不稳，实际对齐方法见第 37 章。 |
| [37 DPO 与 GRPO](./preference-alignment.md) | 在 SFT 模型上先用 DPO；有能自动判分的任务时再用 GRPO | DPO 不需要单独的奖励模型；对齐后同时检查目标任务和原有能力。 |
| [38 LLM 与 Agent](./llm-agent-interaction.md) | 只通过文本消息交互：与 SFT 相同的对话模板渲染四种角色，工具调用写成一行 JSON，解析或校验失败把错误送回模型，循环设步数上限；跨会话事实带来源和时间存在模型外，检索后放回上下文 | 调工具、记事情的能力来自 Agent 和模型约定的格式；小模型能否稳定按格式调用要实测，不稳时加约束解码。参数和 KV cache 不保存可更新的跨会话事实，按规模决定是否加向量索引。 |

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
