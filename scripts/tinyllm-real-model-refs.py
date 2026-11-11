"""Generate the “在真实模型里” section of each TinyLLM chapter.

每章末尾有一小节，把本章写的零件对应到 Hugging Face transformers 里 Llama / Qwen 的真实实现，
并给出精确到行的链接。行号由本脚本从固定版本的源码里算出来（按类名、函数名定位），
正文里 `<!-- real-model:start -->` 与 `<!-- real-model:end -->` 之间的内容由它整段重写，不要手改。

用法（三步，目录可以换成别的）：

    python scripts/tinyllm-real-model-refs.py --fetch /tmp/tf   # 取源码：只下载 SPEC 里用到的文件
    python scripts/tinyllm-real-model-refs.py --check /tmp/tf   # 只检查每个名字找不找得到，不写文件
    python scripts/tinyllm-real-model-refs.py /tmp/tf           # 生成

--fetch 用 git 浅克隆固定版本 TAG，并把 sparse-checkout 设成 SPEC 里出现的文件（不用手写路径清单）；
目录已经是一个克隆时，只更新 sparse-checkout。新增 SPEC 条目或升级 TAG 后重新 --fetch 一次即可。

源码目录里缺文件时，脚本列出缺的文件并直接退出，不逐条报错。
其余找不到的名字不会中断脚本：其他条目照常生成，结束时列出全部问题并以状态码 1 退出。
已经有“在真实模型里”一节的章节，如果这次有条目找不到，保留原来的一节，不用残缺的版本覆盖。
"""

from pathlib import Path
import ast
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/tinyllm"
TAG = "v5.21"
BLOB = f"https://github.com/huggingface/transformers/blob/{TAG}/src/transformers/"
START, END = "<!-- real-model:start -->", "<!-- real-model:end -->"
REPO = os.environ.get("TINYLLM_TF_REPO", "https://github.com/huggingface/transformers.git")

LLAMA = "models/llama/modeling_llama.py"
QWEN3 = "models/qwen3/modeling_qwen3.py"
QWEN35 = "models/qwen3_5/modeling_qwen3_5.py"

# 每章：导语，以及若干行 (本章的零件, 文件, 名字或 ("grep", 正则), 对照要点)
SPEC = {
    "first-run": ("第 1 章那个不到 100 行的模型，在真实代码里分散在几个类中，但流水线完全一样：", [
        ("整个模型：嵌入 → N 个 Block → 归一化 → 输出层", LLAMA, "LlamaForCausalLM", "`self.model` 就是 `LlamaModel`，后面接 `lm_head`；传入 `labels` 时顺便算损失"),
        ("主干的前向计算", LLAMA, "LlamaModel.forward", "查表、逐层调用 Block、最后一次 RMSNorm；多出来的是缓存和注意力掩码的准备"),
        ("逐个生成 token", "generation/utils.py", "GenerationMixin._sample", "每一步取最后一个位置的 logits、按概率抽一个、接到末尾，和第 1 章的 `generate` 一样，只是多了停止条件和缓存"),
        ("一步训练", "trainer.py", "Trainer.training_step", "前向算损失、反向求梯度；优化器的 `step()` 在外层训练循环里"),
    ]),
    "tensors-and-autograd": ("真实模型的代码里只写前向计算，反向传播全部交给 PyTorch 的自动求导：", [
        ("反向传播的入口", "trainer.py", ("grep", r"self\.accelerator\.backward\(loss"), "相当于本章的 `loss.backward()`；`modeling_llama.py` 整个文件里没有一行手写的求导"),
        ("一步训练", "trainer.py", "Trainer.training_step", "前向 → 损失 → backward，和本章的单参数例子是同一个骨架，只是参数有几十亿个"),
        ("梯度裁剪", "trainer.py", "Trainer._clip_grad_norm", "按全局梯度范数裁剪，第 20 章细讲"),
    ]),
    "architecture-evolution": ("第二代和第三代的区别，在 transformers 里就是两个 Block 类的区别：", [
        ("第二代：现代稠密解码器的 Block", LLAMA, "LlamaDecoderLayer", "每层都是完整注意力加 SwiGLU，TinyLLM 的主线就是它"),
        ("第三代：混合注意力的 Block", QWEN35, "Qwen3_5DecoderLayer", "`config.layer_types` 决定这一层用线性注意力（`linear_attn`）还是完整注意力（`self_attn`），对应本章的 3:1 混合"),
        ("线性注意力层", QWEN35, "Qwen3_5GatedDeltaNet", "Gated DeltaNet：在本章朴素线性注意力的基础上加了遗忘门和 delta 更新规则"),
        ("逐 token 更新状态", QWEN35, "torch_recurrent_gated_delta_rule", "一个 token 一个 token 地更新固定大小的状态，和本章 linear-attention 那段代码的写法二是同一个思路"),
    ]),
    "tokenization": ("真实模型的分词器由 Hugging Face tokenizers 库实现，和本章训练用的是同一个库：", [
        ("Qwen2 / Qwen3 的分词器", "models/qwen2/tokenization_qwen2.py", "Qwen2Tokenizer", "字节级 BPE，后端就是本章用的 `tokenizers`；特殊 token 和对话模板也在这里定义"),
        ("Qwen3.5 的分词器", "models/qwen3_5/tokenization_qwen3_5.py", "Qwen3_5Tokenizer", "同样基于 `tokenizers` 后端"),
    ]),
    "embeddings-and-output": ("本章的查表、输出层和权重共享，在真实代码里各有对应：", [
        ("词嵌入表", LLAMA, ("grep", r"self\.embed_tokens = nn\.Embedding"), "`nn.Embedding(vocab_size, hidden_size)`，和本章完全一样"),
        ("输出层与权重共享", LLAMA, "LlamaForCausalLM", "`lm_head` 是一个不带偏置的线性层；类属性 `_tied_weights_keys` 声明它可以和 `embed_tokens` 共享权重，是否共享由配置 `tie_word_embeddings` 决定"),
        ("语言模型损失", "loss/loss_utils.py", "ForCausalLMLoss", "把标签错开一位再算交叉熵，`ignore_index=-100` 的位置不计入，和本章的标签构造一致"),
    ]),
    "self-attention": ("本章的注意力在真实代码里分成两部分：投影与拆头在注意力类里，打分与加权求和在一个独立函数里：", [
        ("Q、K、V 与输出投影", LLAMA, "LlamaAttention", "`q_proj`、`k_proj`、`v_proj`、`o_proj` 四个线性层，拆成多头后交给下面的函数"),
        ("缩放点积注意力", LLAMA, "eager_attention_forward", "分数乘 `scaling`（就是 1/√d）、加上掩码、softmax、再乘 V；实际运行时通常换成 PyTorch 的 SDPA 或 FlashAttention"),
        ("GQA：几个头共用一组 K、V", LLAMA, "repeat_kv", "把较少的 K、V 头复制成和 Q 一样多"),
        ("QK Norm", QWEN3, ("grep", r"self\.q_norm = Qwen3RMSNorm"), "Qwen3 在算分数之前，对每个头的 q、k 各做一次 RMSNorm，即本章延伸一节的 QK Norm"),
    ]),
    "position-encoding": ("RoPE 在真实代码里分成“算角度”和“转 q、k”两步：", [
        ("预先算好每个位置的 cos、sin", LLAMA, "LlamaRotaryEmbedding", "`inv_freq` 就是本章的 θ_i = base^(-2i/d)；base 由配置 `rope_theta` 给出"),
        ("把维度分成两半", LLAMA, "rotate_half", "把前一半和后一半配成一对，本章是相邻两维配一对；两种都对，但加载权重时必须一致（见本章常见误区）"),
        ("旋转 q 和 k", LLAMA, "apply_rotary_pos_emb", "只转 q、k，不转 v，和本章一样"),
        ("扩展上下文：YaRN", "modeling_rope_utils.py", "_compute_yarn_parameters", "本章第 6 节提到的调整旋转频率的方法之一"),
    ]),
    "activations-and-ffn": ("本章的 SwiGLU 在 Llama 里叫 MLP，三个线性层一一对应：", [
        ("门控前馈层", LLAMA, "LlamaMLP", "`gate_proj` 对应本章的 `gate`、`up_proj` 对应 `value`、`down_proj` 对应 `down`；`act_fn` 由配置 `hidden_act` 决定，Llama 用 `silu`"),
    ]),
    "transformer-block": ("本章的 Pre-Norm 残差 Block 在 Llama 里几乎逐行对应：", [
        ("一个 Block", LLAMA, "LlamaDecoderLayer", "`residual = hidden_states` → `input_layernorm` → 注意力 → 加回；再 `post_attention_layernorm` → MLP → 加回，就是本章的两行"),
        ("叠起来", LLAMA, "LlamaModel.forward", "逐层调用 `decoder_layer`，最后再做一次 `self.norm`，和本章的 `TinyLLM.forward` 一样"),
    ]),
    "initialization-and-residuals": ("真实模型的默认初始化比本章的配方简单：", [
        ("默认初始化", "modeling_utils.py", "PreTrainedModel._init_weights", "线性层和嵌入一律用均值 0、标准差 `initializer_range` 的正态分布，不按宽度调整，也不对残差输出投影额外缩小"),
        ("标准差从哪里来", "models/llama/configuration_llama.py", ("grep", r"initializer_range: float"), "Llama 默认 0.02；本章第 1 节的实验说明了固定 0.02 会随宽度变化"),
        ("残差加法", LLAMA, "LlamaDecoderLayer.forward", "`hidden_states = residual + hidden_states` 出现两次，就是本章的两条残差"),
    ]),
    "normalization": ("RMSNorm 在真实代码里只有十几行：", [
        ("RMSNorm", LLAMA, "LlamaRMSNorm", "先转成 FP32 求均方根、归一化，再转回原来的精度乘 `weight`；没有减均值，也没有偏置"),
        ("放在哪里", LLAMA, "LlamaDecoderLayer", "`input_layernorm`、`post_attention_layernorm` 两处都在子层之前（Pre-Norm），`LlamaModel` 末尾还有一次 `norm`"),
        ("QK Norm", QWEN3, ("grep", r"self\.q_norm = Qwen3RMSNorm"), "Qwen3 额外对每个头的 q、k 做 RMSNorm"),
    ]),
    "tinyllm-model": ("本章拼出来的整机，在 transformers 里就是 Llama 的这几个类，结构一一对应：", [
        ("整机：主干 + 输出层", LLAMA, "LlamaForCausalLM", "`self.model` 是主干，后面接 `lm_head`；`_tied_weights_keys` 声明 `lm_head.weight` 可以指向 `embed_tokens.weight`，和本章的权重共享是同一件事"),
        ("主干的前向", LLAMA, "LlamaModel.forward", "查表 → 逐层调用 Block → 最后一次 `norm`；多出来的是位置编号、缓存和掩码的准备"),
        ("一个 Block", LLAMA, "LlamaDecoderLayer.forward", "`input_layernorm` → 注意力 → 残差相加，`post_attention_layernorm` → MLP → 残差相加，和本章 `Block.forward` 两行一样"),
        ("RoPE 的 cos/sin 表", LLAMA, "LlamaRotaryEmbedding", "按位置预先算 cos、sin，再交给每一层的注意力，对应本章的 `rope_tables`"),
        ("默认初始化", "modeling_utils.py", "PreTrainedModel._init_weights", "线性层和嵌入都用标准差 `initializer_range`（默认 0.02）的正态分布；本章按第 10 章改用 Xavier 和 `1/√d`，两者是不同的配方"),
    ]),
    "gpu-training": ("用 transformers 的 Trainer 在 GPU 上训练时，本章训练循环里的几件事分别在这些地方：", [
        ("梯度累积：什么时候才更新", "trainer.py", ("grep", r"do_sync_step = \(step \+ 1\) % self\.args\.gradient_accumulation_steps"), "每累积 `gradient_accumulation_steps` 个 micro-batch 才裁剪、更新一次，和本章的 `accum` 循环一样"),
        ("一个 micro-batch 的前向与反向", "trainer.py", "Trainer.training_step", "在 autocast 里算损失、按累积步数缩放后 backward"),
        ("混合精度的上下文", "trainer.py", "Trainer.compute_loss_context_manager", "把 autocast 套在前向外面，对应本章的 `autocast()`"),
        ("梯度裁剪", "trainer.py", "Trainer._clip_grad_norm", "按全局范数裁剪，和本章 `clip_grad_norm_(…, 1.0)` 相同"),
        ("保存检查点", "trainer.py", "Trainer._save_checkpoint", "模型、优化器、调度器、随机数状态和步数一起存，比本章多存了调度器和随机数状态（第 21 章）"),
    ]),
    "data-pipeline": ("transformers 不管清洗和去重（那是 datasets 等数据工具的事），但从样本到 batch 的几步都在这里：", [
        ("补齐与损失掩码", "data/data_collator.py", "DataCollatorForLanguageModeling", "`mlm=False` 时就是因果语言模型：一批样本补齐到同样长度，`<pad>` 位置的标签设成 -100，不计入损失"),
        ("不补齐、直接拼接", "data/data_collator.py", "DataCollatorWithFlattening", "把一批序列拼成一条，不加 `<pad>`；每条序列的 `position_ids` 从 0 重新数，再配合注意力内核的边界参数，效果就是本章的文档掩码"),
        ("按长度分桶", "trainer_pt_utils.py", "get_length_grouped_indices", "先随机打乱，再在几十个 batch 组成的“大批”里按长度排序：长度相近的落进同一个 batch，又保留了随机性"),
        ("多进程预取与锁页内存", "trainer.py", "Trainer._get_dataloader", "`num_workers`、`pin_memory`、`prefetch_factor` 原样交给 PyTorch 的 `DataLoader`，对应本章第 9 节的 GPU 做法"),
    ]),
    "language-model-loss": ("transformers 里因果语言模型的损失只有几十行，本章讲的错位、忽略位置和分母都在里面：", [
        ("错位与忽略位置", "loss/loss_utils.py", "ForCausalLMLoss", "先 `logits.float()` 转成 FP32；把 `labels` 末尾补一个 -100 再整体左移一位，就是本章第 1 节的错位；-100 的位置不算损失"),
        ("分母放在哪", "loss/loss_utils.py", "fixed_cross_entropy", "传入 `num_items_in_batch` 时先按 `sum` 求和，再除以整个累积批次的有效题数，正是本章第 5 节“各自求和、最后除以总题数”的做法"),
        ("统计有效题数", "trainer.py", "Trainer._get_num_items_in_batch", "把梯度累积要用的全部 micro-batch 的标签（错位后）里不是 -100 的位置加起来，作为 `num_items_in_batch`；多卡时还会把各卡的数加总"),
        ("label smoothing", "trainer_pt_utils.py", "LabelSmoother", "`label_smoothing_factor` 不为 0 时启用：普通负对数似然和“对所有候选取平均”的那一项按 ε 混合"),
    ]),
    "learning-rate": ("transformers 的学习率调度都是“给步数、返回倍数”的函数，再包进 PyTorch 的 `LambdaLR`，和本章的写法一样：", [
        ("warmup + 余弦", "optimization.py", "get_cosine_schedule_with_warmup", "先线性升到峰值，再按余弦降；默认一直降到 0，本章（和第 13 章的 `lr_at`）停在峰值的 10%"),
        ("WSD", "optimization.py", "_get_wsd_scheduler_lambda", "warmup、保持、衰减三段；衰减段可选线性、余弦或 1-sqrt，并可设最低学习率比例 `min_lr_ratio`"),
        ("按名字选调度器", "optimization.py", "get_scheduler", "`lr_scheduler_type` 是 `\"cosine\"`、`\"linear\"`、`\"warmup_stable_decay\"` 等字符串，在这里映射到具体函数"),
        ("Trainer 何时创建", "trainer.py", "Trainer.create_scheduler", "知道总步数以后才创建调度器；`warmup_steps` 不小于 1 时是步数，小于 1 时按总步数的比例换算"),
    ]),
    "quantization": ("transformers 不自己实现量化算法，而是用配置类描述格式，交给 bitsandbytes、GPTQ、AWQ 等后端；KV cache 的量化在缓存类里：", [
        ("8 位 / 4 位加载", "utils/quantization_config.py", "BitsAndBytesConfig", "`load_in_8bit` 走 LLM.int8()：超过 `llm_int8_threshold`（默认 6.0）的离群值单独用 FP16 算；`load_in_4bit` 可选 NF4 或 FP4"),
        ("GPTQ", "utils/quantization_config.py", "GPTQConfig", "`bits` 和 `group_size`（默认 128）就是本章的位数和分组大小；量化时用校准数据逐列补偿误差"),
        ("AWQ", "utils/quantization_config.py", "AwqConfig", "默认 4 位、分组 128、带零点（非对称）；`modules_to_not_convert` 用来让某些层保持原精度"),
        ("KV cache 量化", "cache_utils.py", "QuantizedLayer", "最近 `residual_length`（默认 128）个 token 保持原精度，更早的按 `q_group_size`（默认 64）分组量化成 `nbits`（默认 4）位"),
    ]),
    "attention-kernels": ("transformers 里的注意力层不自己写 softmax，而是按配置把 Q、K、V 交给某个注意力实现；默认就是本章用的 SDPA：", [
        ("选择注意力实现", LLAMA, ("grep", r"attention_interface: Callable = ALL_ATTENTION_FUNCTIONS\.get_interface\("), "按 `config._attn_implementation`（`eager`、`sdpa`、`flash_attention_2` 等）挑一个函数，找不到时退回朴素写法；注意力层本身不关心用的是哪种内核"),
        ("朴素写法", LLAMA, "eager_attention_forward", "先算出完整的分数矩阵、加掩码、softmax、再乘 V，和本章 `naive_attention` 一样，会写出整张 T×T 的表"),
        ("SDPA", "integrations/sdpa_attention.py", "sdpa_attention_forward", "整理形状和掩码后调用 `torch.nn.functional.scaled_dot_product_attention`，由 PyTorch 选分块内核"),
        ("FlashAttention", "integrations/flash_attention.py", "flash_attention_forward", "调用 flash-attn 库的 GPU 内核；需要单独安装，只支持部分 GPU 和数据类型"),
    ]),
    "mixture-of-experts": ("transformers 里的 MoE 层和本章的写法几乎一样：路由器打分、取 top-k、按分数加权求和；Qwen2-MoE 还多了一个共享专家：", [
        ("路由与专家", "models/mixtral/modeling_mixtral.py", "MixtralSparseMoeBlock", "Mixtral 的 MoE 层：8 个专家选 2 个，softmax 后取 top-2 并重新归一化，和本章 `MoE` 的做法相同"),
        ("负载均衡损失", "models/mixtral/modeling_mixtral.py", "load_balancing_loss_func", "Switch Transformer 的辅助损失：每个专家分到的比例乘以平均路由概率，再求和，即本章 `self.aux`"),
        ("共享专家", "models/qwen2_moe/modeling_qwen2_moe.py", "Qwen2MoeSparseMoeBlock", "路由专家之外，还有一个每个 token 都经过的共享专家，用一个门控决定它的输出占多少"),
    ]),
    "scaling-laws": ("transformers 的 Trainer 也用 6ND 记录训练花了多少算力，但它数参数的方式和本章不同：", [
        ("每一步的算力", "trainer.py", "Trainer.floating_point_ops", "返回 6 × token 数 × `num_parameters(exclude_embeddings=True)`，也就是不算嵌入表；输入、输出共享权重的模型（比如 TinyLLM）会因此漏掉输出层那一份乘法，正是本章第 1 节说的少算"),
        ("数参数", "modeling_utils.py", "ModuleUtilsMixin.num_parameters", "`exclude_embeddings=True` 时跳过所有 `nn.Embedding` 的权重；共享的那张表在 `named_parameters()` 里只出现一次、挂在嵌入层名下，所以一起被跳过"),
        ("累计并上报", "trainer.py", ("grep", r'metrics\["total_flos"\]'), "训练结束时把累计的算力写进指标 `total_flos`，可以用来核对一次训练一共花了多少算力"),
    ]),
    "large-model-stability": ("本章的几个手段，在 transformers 里分别对应下面这几处：", [
        ("QK Norm", QWEN3, ("grep", r"self\.q_norm = "), "Qwen3 给每个头的 q、k 各配一个 RMSNorm，和本章 `qk_norm=True` 的写法相同"),
        ("激活重计算的开关", "modeling_utils.py", "PreTrainedModel.gradient_checkpointing_enable", "给模型里的每一层打开重计算，底层就是本章用的 `torch.utils.checkpoint`"),
        ("Trainer 何时打开它", "trainer.py", ("grep", r"gradient_checkpointing_enable\("), "`TrainingArguments(gradient_checkpointing=True)` 时，训练开始前调用上面那个方法"),
    ]),
    "hyperparameter-tuning": ("transformers 的 Trainer 自带一个超参数搜索的入口，具体的搜索算法交给 Optuna、Ray Tune 等后端：", [
        ("搜索入口", "trainer.py", "Trainer.hyperparameter_search", "每个 trial 用 `model_init` 重新造一个模型，按 `direction` 取验证指标的最小或最大；算法（TPE、随机、ASHA 等）由所选的后端决定"),
        ("默认的搜索空间", "trainer_utils.py", "default_hp_space_optuna", "看一下默认都搜哪些量、范围多大；如果随机种子也在里面，挑出来的可能只是一次好运气（本章第 7 节）"),
    ]),
    "training-evaluation": ("本章埋的几个 bug，在 transformers 里分别由下面这几处代码防住；评估也有固定的入口：", [
        ("标签错位", "loss/loss_utils.py", "ForCausalLMLoss", "把 `labels` 整体左移一位再算交叉熵；调用者只要传 `labels=input_ids`，错位由这里完成，避免了“标签没错位”"),
        ("因果掩码", LLAMA, ("grep", r"create_causal_mask\("), "Llama 在主干的前向里构造因果掩码，再交给每一层注意力；本章“漏了因果掩码”就是少了这一步"),
        ("评估入口", "trainer.py", "Trainer.evaluate", "在验证集上跑一遍，返回 `eval_loss` 等指标；`Trainer` 不替你算困惑度，常见的做法是自己取 `exp(eval_loss)`"),
        ("评估循环", "trainer.py", "Trainer.evaluation_loop", "切到评估模式、关掉梯度，逐个 batch 收集损失和预测，再汇总成一个平均数"),
    ]),
    "training-loop": ("transformers 的 Trainer 存检查点、续训的做法和本章是同一套思路，只是拆成了几个文件：", [
        ("保存检查点", "trainer.py", "Trainer._save_checkpoint", "模型、优化器、调度器、随机数状态和训练进度分别存成几个文件，放在同一个 `checkpoint-<步数>` 目录里"),
        ("训练进度", "trainer_callback.py", "TrainerState", "`global_step`、`epoch`、日志历史等，存成 `trainer_state.json`，对应本章的 `progress`"),
        ("保存随机数状态", "trainer.py", "Trainer._save_rng_state", "Python、NumPy、torch 以及每张 GPU 的随机数状态都存下来，比本章多几种"),
        ("恢复随机数状态", "trainer.py", "Trainer._load_rng_state", "续训时装回去；找不到这个文件时会给出警告，提示结果可能无法逐位复现"),
        ("跳过已经用过的 batch", "trainer.py", ("grep", r"skip_first_batches"), "续训时跳过这个 epoch 已经训练过的 batch，作用和本章 `EpochShuffle` 的 `start` 相同"),
        ("只保留最近几个检查点", "trainer_utils.py", "rotate_checkpoints", "按 `save_total_limit` 删掉最旧的检查点，但始终保留最新的一个（续训要用）和验证最好的那个"),
    ]),
    "gradient-stability": ("transformers 的 Trainer 把本章的几件事都放在训练循环里：累积几步、裁剪一次、再更新：", [
        ("一个 micro-batch 的前向与反向", "trainer.py", "Trainer.training_step", "算损失、按累积步数缩放后 backward；梯度在 `.grad` 里累加，这里不裁剪、不更新"),
        ("什么时候才更新", "trainer.py", ("grep", r"do_sync_step = \(step \+ 1\) % self\.args\.gradient_accumulation_steps"), "每累积 `gradient_accumulation_steps` 个 micro-batch 才裁剪、更新一次，和本章 `train(accum=4)` 的顺序一样"),
        ("裁剪阈值", "trainer.py", ("grep", r"max_grad_norm"), "来自 `TrainingArguments.max_grad_norm`，默认 1.0；设成 0 或 `None` 就不裁剪"),
        ("按全局范数裁剪", "trainer.py", "Trainer._clip_grad_norm", "调用 PyTorch 的 `clip_grad_norm_`（多卡时由 accelerate 包一层），返回裁剪前的范数，Trainer 把它记成日志里的 `grad_norm`"),
    ]),
    "regularization": ("transformers 里和本章有关的开关都不大：weight decay 在创建优化器时分组，dropout 写在注意力里，提前停止是一个回调：", [
        ("哪些参数做 weight decay", "trainer.py", "Trainer.get_decay_parameter_names", "名字里带 `bias`、`norm` 的参数不衰减，其余（包括词嵌入）按 `weight_decay` 衰减，和本章 `p.dim() >= 2` 的分法结果相同"),
        ("weight decay 的默认值", "training_args.py", ("grep", r"weight_decay: float = field"), "`TrainingArguments` 默认 `weight_decay=0.0`，要自己设；本章的实验说明合适的值和数据量、学习率、训练步数都有关"),
        ("注意力 dropout 只在训练时打开", LLAMA, ("grep", r"dropout=0\.0 if not self\.training else self\.attention_dropout"), "评估模式下传 0，和本章 `dropout_p=... if self.training else 0.0` 一样；比例来自配置里的 `attention_dropout`"),
        ("在注意力权重上丢弃", LLAMA, "eager_attention_forward", "softmax 之后对注意力权重做 `nn.functional.dropout`，即本章的位置 ①；`LlamaDecoderLayer` 里没有本章的 ② ③ 两处"),
        ("提前停止", "trainer_callback.py", "EarlyStoppingCallback", "`early_stopping_patience` 次评估没有改进就停止训练；配合 `load_best_model_at_end=True` 才会在结束时换回最好的检查点"),
        ("label smoothing", "trainer_pt_utils.py", "LabelSmoother", "`label_smoothing_factor` 不为 0 时启用；评估指标仍应看普通交叉熵（第 15 章）"),
    ]),
    "optimizers": ("用 transformers 的 Trainer 训练时，优化器在这里创建：", [
        ("创建优化器", "trainer.py", "Trainer.create_optimizer", "默认 AdamW；参数分成“衰减”和“不衰减”两组"),
        ("哪些参数不做权重衰减", "trainer.py", "Trainer.get_decay_parameter_names", "名字里带 `bias`、`norm` 的参数不衰减，和本章 AdamW 一节的参数分组一致"),
    ]),
    "precision": ("真实代码里有好几处故意转成 FP32 计算，正对应本章讲的数值风险：", [
        ("RMSNorm 在 FP32 里算", LLAMA, "LlamaRMSNorm.forward", "`hidden_states.to(torch.float32)` 后再求均方根，算完转回原精度"),
        ("softmax 在 FP32 里算", LLAMA, "eager_attention_forward", "`softmax(..., dtype=torch.float32)` 再转回 `query.dtype`"),
        ("损失在 FP32 里算", "loss/loss_utils.py", "ForCausalLMLoss", "第一行就是 `logits = logits.float()`"),
        ("混合精度的上下文", "trainer.py", "Trainer.autocast_smart_context_manager", "按训练参数打开 `autocast`"),
    ]),
    "generation": ("本章的采样步骤在 transformers 里由 `generate()` 调度，真正的取样发生在 `_sample` 里：", [
        ("生成入口", "generation/utils.py", "GenerationMixin.generate", "准备输入、准备缓存、进入循环；本章的 `generate` 就是这个循环的最小版本"),
        ("一步一步生成", "generation/utils.py", "GenerationMixin._sample", "每步前向、取最后一个位置的 logits、调处理器改打分、抽样、拼接，和本章的四步一样"),
        ("温度", "generation/logits_process.py", "TemperatureLogitsWarper", "`scores / self.temperature` 之后再 softmax，就是本章第 1 节除一下"),
        ("重复惩罚", "generation/logits_process.py", "RepetitionPenaltyLogitsProcessor", "正负 logits 分开处理：正的除以 penalty、负的乘 penalty，和本章第 8 节逐行对应"),
        ("top-k", "generation/logits_process.py", "TopKLogitsWarper", "取 topk 后把其余位置填成 `-inf`，即本章的 `masked_fill`"),
        ("top-p", "generation/logits_process.py", "TopPLogitsWarper", "排序、累加，把累计概率超过 p 的部分填成 `-inf`，和本章 `truncate` 同一个算法"),
        ("约束解码", "generation/logits_process.py", "PrefixConstrainedLogitsProcessor", "按已生成的前缀查允许列表并填 `-inf`，正是本章第 9 节的做法"),
        ("固定随机数流", "trainer_utils.py", "set_seed", "同时设置 Python、NumPy 与 torch 的随机种子；本章把 `torch.Generator` 直接传给 `multinomial`，作用相同"),
    ]),
    "inference-efficiency": ("KV cache 在真实代码里由缓存类管理，注意力每一层把新的 K、V 交给它：", [
        ("创建缓存", LLAMA, ("grep", r"past_key_values = DynamicCache\(config=self\.config\)"), "`use_cache=True` 且没有传入缓存时新建一个"),
        ("每层写入缓存", LLAMA, ("grep", r"key_states, value_states = past_key_values\.update"), "拿到这一层新 token 的 K、V 后交给缓存，换回包含全部历史的 K、V"),
        ("追加到末尾", "cache_utils.py", "DynamicLayer.update", "`torch.cat([self.keys, key_states], dim=-2)`：沿序列维拼接，和本章逐步缓存的写法一样"),
    ]),
    "batching": ("transformers 里有两条批处理的路：普通的 `generate` 用左补齐的矩形批；`generate_batch` 走连续批，调度器每次前向重新决定放谁、各送几个 token：", [
        ("左补齐时的位置", "generation/utils.py", "GenerationMixin._prepare_position_ids_for_generation", "有 `attention_mask` 时位置是 `attention_mask.long().cumsum(-1) - 1`，pad 处填 0，和本章第 2 节的写法相同"),
        ("连续批的入口", "generation/continuous_batching/continuous_api.py", "ContinuousMixin.generate_batch", "一次交进一批提示词，后台循环按 token 步调度；`ContinuousBatchingConfig` 的 `max_batch_tokens` 是每次前向的 token 额度，`max_requests_per_batch` 相当于本章的槽位数"),
        ("FIFO 调度", "generation/continuous_batching/scheduler.py", "FIFOScheduler.schedule_batch", "先排正在 decode 的请求，再排没送完的提示词，最后是等待队列，和本章“连续批 + 分块 prefill”的顺序相同"),
        ("提示词分块", "generation/continuous_batching/scheduler.py", "Scheduler._schedule_request", "额度够就整段送；不够就先送 `token_budget` 个，剩下的记在 `remaining_prefill_tokens`，下一次接着送"),
        ("首尾相接的一批", "generation/continuous_batching/input_outputs.py", "ContinuousBatchingIOs.prepare_batch_tensors", "所有请求的新 token 接成一行，位置是 `range(past_length, past_length + query_length)`，`cumulative_seqlens_q` 记每段的边界，`logits_indices` 只取每段最后一个位置，和本章 `Engine.step` 一一对应"),
    ]),
    "speculative-decoding": ("transformers 把投机解码叫“辅助生成”（assisted generation）：`generate(assistant_model=...)` 用小模型起草，`generate(prompt_lookup_num_tokens=...)` 在已有文本里查，起草和验证分在两个地方：", [
        ("小模型起草", "generation/candidate_generator.py", "AssistedCandidateGenerator", "`num_assistant_tokens` 就是每轮起草的个数 γ；`update_candidate_strategy` 里有一条启发式：草稿全部被接受就 +2，否则 −1"),
        ("在已有文本里查", "generation/candidate_generator.py", "PromptLookupCandidateGenerator", "`max_matching_ngram_size` 默认 2：先找最后 2 个 token、找不到再找最后 1 个，取从左往右第一处匹配（本章只找 2 个、取最近的一处）；都找不到就返回原输入，这一轮退回普通 decode"),
        ("MTP 模块起草", "generation/candidate_generator.py", "MTPCandidateGenerator", "模型配置里有 `num_mtp_layers` 时可用：拿主模型最后一层的隐藏状态送进 MTP 层猜后面的 token"),
        ("一次前向验证", "generation/utils.py", "GenerationMixin._assisted_decoding", "目标模型一次前向全部候选；贪心时 `n_matches` 是第一处不同之前的长度，保留匹配的 token 再加目标模型自己的一个，然后 `crop` 掉多余的 KV"),
        ("拒绝采样", "generation/utils.py", "_speculative_sampling", "`p_i / q_i` 当接受概率，第一次被拒后从 `clamp(p - q, min=0)` 归一化的分布里重抽，全部接受时从最后一个位置多抽一个，和本章 `speculative_sample` 一一对应"),
        ("KV cache 回滚", "cache_utils.py", "DynamicLayer.crop", "沿序列维去掉末尾若干个位置，对应本章的 `KVCache.crop`；线性注意力层（第 3 章）的状态没有序列维，要先记录历史状态才能回滚"),
    ]),
}


class Missing(Exception):
    """SPEC 里的某个文件或名字在源码里找不到。"""


def locate(src: Path, target):
    """返回 (起始行, 结束行)。target 是“类名”“类名.方法名”“函数名”，或 ("grep", 正则) 取单行。"""
    if not src.exists():
        raise Missing(f"文件不存在：{src}（重新运行 --fetch）")
    text = src.read_text(encoding="utf-8")
    if isinstance(target, tuple):
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(target[1], line):
                return i, i
        raise Missing(f"{src.name} 里找不到正则 {target[1]}")
    parts = target.split(".")
    nodes = ast.parse(text).body
    node = None
    for part in parts:
        node = next((n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part), None)
        if node is None:
            raise Missing(f"{src.name} 里找不到 {target}")
        nodes = node.body
    return node.lineno, node.end_lineno


def section(slug: str, base: Path, problems: list) -> str | None:
    """生成一章的“在真实模型里”。找不到的条目记进 problems 并跳过；一条都没找到时返回 None。"""
    intro, rows = SPEC[slug]
    out = [START, "", "## 在真实模型里", "",
           f"{intro.rstrip('：')}。下表的链接都指向 Hugging Face transformers 的固定版本 `{TAG}`，精确到行。"
           "读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。", "",
           "| 本章的零件 | 真实代码 | 对照要点 |", "| --- | --- | --- |"]
    found = 0
    for what, file, target, note in rows:
        try:
            start, end = locate(base / "src/transformers" / file, target)
        except Missing as e:
            problems.append((slug, what, str(e)))
            continue
        found += 1
        name = target if isinstance(target, str) else f"{Path(file).name} 第 {start} 行"
        anchor = f"#L{start}" if start == end else f"#L{start}-L{end}"
        out.append(f"| {what} | [`{name}`]({BLOB}{file}{anchor}) | {note} |")
    if found == 0:
        return None
    out += ["", "想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。", "", END]
    return "\n".join(out)


def needed_files() -> list[str]:
    """SPEC 里用到的全部源码文件（相对 src/transformers/）。"""
    return sorted({row[1] for _, rows in SPEC.values() for row in rows})


def fetch(dest: Path) -> None:
    """浅克隆 transformers 的 TAG，只检出 needed_files()。"""
    def git(*cmd):
        print("$ git " + " ".join(cmd))
        subprocess.run(["git", *cmd], check=True)
    paths = [f"/src/transformers/{f}" for f in needed_files()]
    if not (dest / ".git").exists():
        if dest.exists() and any(dest.iterdir()):
            raise SystemExit(f"{dest} 已存在但不是 git 克隆，换一个目录或先删掉它")
        git("clone", "--depth", "1", "--branch", TAG, "--filter=blob:none", "--no-checkout", REPO, str(dest))
    git("-C", str(dest), "sparse-checkout", "set", "--no-cone", *paths)
    git("-C", str(dest), "checkout", "--detach", TAG)
    missing = [f for f in needed_files() if not (dest / "src/transformers" / f).exists()]
    if missing:
        raise SystemExit("检出后仍然缺这些文件（TAG 里可能没有它们，改 SPEC）：\n  " + "\n  ".join(missing))
    print(f"已取到 {len(needed_files())} 个文件：{dest}（transformers {TAG}）")


def main() -> None:
    args = sys.argv[1:]
    check, do_fetch = "--check" in args, "--fetch" in args
    args = [a for a in args if a not in ("--check", "--fetch")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    base = Path(args[0])
    if do_fetch:
        fetch(base)
        return
    missing = [f for f in needed_files() if not (base / "src/transformers" / f).exists()]
    if missing:
        print(f"{base} 下缺 {len(missing)}/{len(needed_files())} 个源码文件：")
        for f in missing:
            print(f"  src/transformers/{f}")
        raise SystemExit(f"先运行：python scripts/tinyllm-real-model-refs.py --fetch {base}")
    problems = []
    for slug in SPEC:
        md = DOCS / f"{slug}.md"
        before = len(problems)
        block = section(slug, base, problems)
        status = f"{len(SPEC[slug][1]) - (len(problems) - before)}/{len(SPEC[slug][1])} 条找到"
        if check or block is None:
            print(f"[{'check' if check else 'skip'}] {slug}: {status}")
            continue
        newline = "\r\n" if b"\r\n" in md.read_bytes() else "\n"   # 保持原文件的换行风格，避免 Windows 上整篇文件都显示为改动
        text = md.read_text(encoding="utf-8")
        if START in text and len(problems) > before:              # 已经有一节，这次又不完整：保留原样，不拿残缺的覆盖
            print(f"[keep] {slug}: {status}，保留已有的一节")
            continue
        if START in text:
            text = text[: text.index(START)] + block + text[text.index(END) + len(END):]
        else:
            # 放在本章结论之前；规划中的章节还没有结论，就放在检查理解之前
            anchor = text.index("\n## 本章结论") if "\n## 本章结论" in text else text.index("\n## 检查理解")
            text = text[:anchor] + "\n" + block + "\n" + text[anchor:]
        md.write_text(text, encoding="utf-8", newline=newline)
        print(f"[real-model] {md.relative_to(ROOT)}（{status}）")
    if problems:
        print(f"\n{len(problems)} 个条目找不到，已跳过（改 SPEC 后重新运行即可）：")
        for slug, what, msg in problems:
            print(f"  {slug} · {what}：{msg}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
