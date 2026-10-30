"""Generate the “在真实模型里” section of each TinyLLM chapter.

每章末尾有一小节，把本章写的零件对应到 Hugging Face transformers 里 Llama / Qwen 的真实实现，
并给出精确到行的链接。行号由本脚本从固定版本的源码里算出来（按类名、函数名定位），
正文里 `<!-- real-model:start -->` 与 `<!-- real-model:end -->` 之间的内容由它整段重写，不要手改。

升级 transformers 版本时：改 TAG，重新取源码，再运行本脚本；找不到的名字会直接报错。

    git clone --depth 1 --branch v5.21 --filter=blob:none --sparse https://github.com/huggingface/transformers.git /tmp/tf
    cd /tmp/tf && git sparse-checkout set src/transformers/models/llama src/transformers/models/qwen2 \\
        src/transformers/models/qwen3 src/transformers/models/qwen3_5 src/transformers/loss src/transformers/generation
    git sparse-checkout add src/transformers/modeling_utils.py src/transformers/cache_utils.py \\
        src/transformers/modeling_rope_utils.py src/transformers/trainer.py
    python scripts/tinyllm-real-model-refs.py /tmp/tf
"""

from pathlib import Path
import ast
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/tinyllm"
TAG = "v5.21"
BLOB = f"https://github.com/huggingface/transformers/blob/{TAG}/src/transformers/"
START, END = "<!-- real-model:start -->", "<!-- real-model:end -->"

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
    "inference-efficiency": ("KV cache 在真实代码里由缓存类管理，注意力每一层把新的 K、V 交给它：", [
        ("创建缓存", LLAMA, ("grep", r"past_key_values = DynamicCache\(config=self\.config\)"), "`use_cache=True` 且没有传入缓存时新建一个"),
        ("每层写入缓存", LLAMA, ("grep", r"key_states, value_states = past_key_values\.update"), "拿到这一层新 token 的 K、V 后交给缓存，换回包含全部历史的 K、V"),
        ("追加到末尾", "cache_utils.py", "DynamicLayer.update", "`torch.cat([self.keys, key_states], dim=-2)`：沿序列维拼接，和本章逐步缓存的写法一样"),
    ]),
}


def locate(src: Path, target):
    """返回 (起始行, 结束行)。target 是“类名”“类名.方法名”“函数名”，或 ("grep", 正则) 取单行。"""
    text = src.read_text(encoding="utf-8")
    if isinstance(target, tuple):
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(target[1], line):
                return i, i
        raise SystemExit(f"{src}: 找不到 {target[1]}")
    parts = target.split(".")
    nodes = ast.parse(text).body
    node = None
    for part in parts:
        node = next((n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part), None)
        if node is None:
            raise SystemExit(f"{src}: 找不到 {target}")
        nodes = node.body
    return node.lineno, node.end_lineno


def section(slug: str, base: Path) -> str:
    intro, rows = SPEC[slug]
    out = [START, "", "## 在真实模型里", "",
           f"{intro.rstrip('：')}。下表的链接都指向 Hugging Face transformers 的固定版本 `{TAG}`，精确到行。"
           "读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。", "",
           "| 本章的零件 | 真实代码 | 对照要点 |", "| --- | --- | --- |"]
    for what, file, target, note in rows:
        start, end = locate(base / "src/transformers" / file, target)
        name = target if isinstance(target, str) else f"{Path(file).name} 第 {start} 行"
        anchor = f"#L{start}" if start == end else f"#L{start}-L{end}"
        out.append(f"| {what} | [`{name}`]({BLOB}{file}{anchor}) | {note} |")
    out += ["", "想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。", "", END]
    return "\n".join(out)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    base = Path(sys.argv[1])
    for slug in SPEC:
        md = DOCS / f"{slug}.md"
        text = md.read_text(encoding="utf-8")
        block = section(slug, base)
        if START in text:
            text = text[: text.index(START)] + block + text[text.index(END) + len(END):]
        else:
            # 放在本章结论之前；规划中的章节还没有结论，就放在检查理解之前
            anchor = text.index("\n## 本章结论") if "\n## 本章结论" in text else text.index("\n## 检查理解")
            text = text[:anchor] + "\n" + block + "\n" + text[anchor:]
        md.write_text(text, encoding="utf-8")
        print(f"[real-model] {md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
