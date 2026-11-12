<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSvgLinkPrefetchFix } from './svgLinks'
import { withBase } from 'vitepress'

// 全书唯一的 TinyLLM 架构总图。每章开头用 <TinyLLMMap active="slug" /> 高亮本章负责的零件。
// 图分成六个区：⓪ 全局、① 数据、② 模型、③ 训练、④ 推理、⑤ 中训练、后训练与应用；每一章都有一个框。
// 高亮本章的框，以及进出这个框的连线；图下方用 io 里的文字写出本章的输入和输出。
// 新章节成文后，把它的 slug 加进 done；改布局时只改下面几组坐标。
// 布尔 prop 不写时 Vue 会当成 false，所以要显式给默认值 true
const props = withDefaults(defineProps<{ active?: string; caption?: boolean }>(), { caption: true })

const done = new Set(["first-run", "tensors-and-autograd", "architecture-evolution", "initialization-and-residuals", "normalization", "activations-and-ffn", "transformer-block", "tokenization", "self-attention", "position-encoding", "embeddings-and-output", "optimizers", "precision", "tinyllm-model", "gpu-training", "data-pipeline", "generation", "language-model-loss", "learning-rate", "regularization", "gradient-stability", "training-loop", "training-evaluation", "hyperparameter-tuning", "scaling-laws", "large-model-stability", "mixture-of-experts", "inference-efficiency", "attention-kernels", "quantization", "speculative-decoding", "batching", "kv-memory", "inference-optimization"])

// 每章在图中的输入与输出（图注里显示）
const io: Record<string, [string, string]> = {
  'first-run': ["一段唐诗文本", "训练好的字符级小模型和它写出的诗：整条流水线先走一遍"],
  'tensors-and-autograd': ["前向的计算图和损失", "每个参数的梯度（右侧 backward）"],
  'architecture-evolution': ["三代架构的设计", "TinyLLM 采用的 Block 结构"],
  'tokenization': ["清洗好的文本", "token ID 序列"],
  'embeddings-and-output': ["token ID（输入端）；最后一层的向量（输出端）", "每个 token 的向量；词表上每个词的 logits"],
  'self-attention': ["归一化后的 [B, T, d] 向量", "融合了前文信息的 [B, T, d]，加回残差"],
  'position-encoding': ["注意力里的 Q、K 和位置编号", "带上位置信息的 Q、K"],
  'activations-and-ffn': ["注意力之后、归一化过的 [B, T, d]", "逐位置变换后的 [B, T, d]，加回残差"],
  'transformer-block': ["上一层的 [B, T, d]", "下一层的 [B, T, d]，同样的 Block 叠 N 层"],
  'initialization-and-residuals': ["随机初始参数", "能稳定训练的初始模型，以及每层的两条残差路径"],
  'normalization': ["每个 token 的向量", "尺度统一的向量，交给注意力、前馈层和输出层"],
  'tinyllm-model': ["token ID", "logits，以及第一次完整的训练"],
  'gpu-training': ["同一份模型和训练代码", "在 GPU 上更快、更大的训练"],
  'data-pipeline': ["原始唐诗语料", "清洗、去重、划分好的训练集和验证集，打包成 token 流"],
  'language-model-loss': ["logits 和下一个 token", "一个标量损失，交给 backward"],
  'optimizers': ["参数和裁剪后的梯度", "更新后的参数"],
  'learning-rate': ["当前步数", "这一步的学习率，交给优化器"],
  'regularization': ["训练配置（weight decay、dropout、训练轮数）", "泛化更好的参数和保留下来的最好检查点"],
  'precision': ["FP32 的前向与反向", "BF16/FP16 混合精度下的同一份计算"],
  'gradient-stability': ["backward 得到的梯度", "裁剪、累积后交给优化器的梯度"],
  'training-loop': ["数据、模型、优化器、调度器", "逐步更新的模型，以及能逐位续训的检查点"],
  'training-evaluation': ["训练中的损失、梯度、生成样例", "“训练是否正常、哪个模型更好”的判断"],
  'hyperparameter-tuning': ["一组候选超参数和固定的预算", "交给训练循环的学习率、batch、warmup 等"],
  'scaling-laws': ["一份算力预算", "模型该多大、该训多少 token，以及从小模型外推的损失"],
  'large-model-stability': ["更大的模型和多张卡", "不发散的训练，以及分摊到各卡的显存"],
  'mixture-of-experts': ["注意力之后的 [B, T, d]", "每个 token 只经过 2 个专家的前馈输出（前馈层的替代）"],
  'generation': ["最后一个位置的 logits", "下一个 token，接到输入末尾继续生成"],
  'inference-efficiency': ["提示词和已经生成的 token", "缓存起来的 K、V，以及分开测的 prefill / decode 延迟"],
  'attention-kernels': ["每层的 Q、K、V", "同样的注意力输出，但不写出 T×T 的分数表"],
  'quantization': ["训练好的权重、激活和 KV cache", "更少位数的存储，以及它带来的质量变化"],
  'speculative-decoding': ["草稿猜的几个 token", "目标模型一次前向验证后接受的 token：贪心时输出不变，采样时分布不变"],
  'batching': ["多个长短不一、先后到达的请求", "按 token 步调度、首尾相接的同一批前向，每个请求的输出不变"],
  'kv-memory': ["各请求按需增长的 K、V", "块表、引用计数和前缀缓存管理的块池，每个请求的输出不变"],
  'inference-optimization': ["第 30～33 章的各项优化和同一份请求流", "单独打开与去掉一项的对照、多实例路由，以及一个 OpenAI 兼容的推理服务"],
  'annealing': ["稳定段的检查点和一小份高质量数据", "学习率衰减段换过数据的基础模型"],
  'long-context': ["只见过短序列的基础模型", "能用上更长上下文的基础模型（调整 RoPE 后继续训练）"],
  'continued-pretraining': ["训好的基础模型和新领域数据", "学会新领域、旧能力少忘的基础模型（混入旧数据回放）"],
  'instruction-finetuning': ["预训练好的模型和指令数据", "会按对话格式回答的模型（复用训练循环）"],
  'lora-finetuning': ["冻结的预训练权重", "一小份低秩增量权重"],
  'distillation': ["大模型老师和它的输出或概率分布", "学了老师本事的小模型"],
  'rlhf': ["SFT 模型和人类偏好数据", "奖励模型，以及用 PPO 对齐后的模型"],
  'preference-alignment': ["SFT 模型和成对的偏好数据", "不训练奖励模型、直接用 DPO 对齐后的模型"],
  'grpo': ["SFT 模型和能自动判分的任务", "用 GRPO 训练后、会先推理再回答的模型"],
  'llm-agent-interaction': ["用户问题、工具结果和记忆", "组装好的上下文（重新分词送进模型），以及从输出里解析出的动作"]
}

type Section = { id: string; title: string; x: number; y: number; w: number; h: number; slugs: string[] }
type Container = { id: string; label: string; ch: number; slug: string; x: number; y: number; w: number; h: number; slugs: string[] }
type Node = { id: string; label: string; ch: number; slug: string; x: number; y: number; w: number; h: number; small: boolean }
type Edge = { f: string | null; t: string | null; d: string; kind: string; label: string | null; at: number[] | null }

const sections: Section[] = [
  {"id": "start", "title": "⓪ 全局", "x": 10, "y": 312, "w": 232, "h": 230, "slugs": []},
  {"id": "data", "title": "① 数据", "x": 10, "y": 40, "w": 232, "h": 262, "slugs": []},
  {"id": "model", "title": "② 模型：一次前向", "x": 256, "y": 40, "w": 366, "h": 502, "slugs": ["tinyllm-model", "first-run"]},
  {"id": "train", "title": "③ 训练", "x": 636, "y": 40, "w": 354, "h": 502, "slugs": ["gpu-training"]},
  {"id": "infer", "title": "④ 推理", "x": 10, "y": 562, "w": 612, "h": 228, "slugs": []},
  {"id": "post", "title": "⑤ 中训练、后训练与应用", "x": 636, "y": 562, "w": 354, "h": 228, "slugs": []}
]

const containers: Container[] = [
  {"id": "block", "label": "Transformer Block × N", "ch": 9, "slug": "transformer-block", "x": 278, "y": 116, "w": 324, "h": 302, "slugs": ["transformer-block", "tinyllm-model", "architecture-evolution"]},
  {"id": "loop", "label": "训练循环与检查点", "ch": 21, "slug": "training-loop", "x": 648, "y": 168, "w": 330, "h": 362, "slugs": ["training-loop", "gpu-training"]}
]

const nodes: Node[] = [
  {"id": "ch1", "label": "先跑通：一个文件走完全程", "ch": 1, "slug": "first-run", "x": 24, "y": 344, "w": 204, "h": 34, "small": false},
  {"id": "ch2", "label": "张量与自动求导", "ch": 2, "slug": "tensors-and-autograd", "x": 24, "y": 390, "w": 204, "h": 34, "small": false},
  {"id": "ch3", "label": "架构演进：三代对照", "ch": 3, "slug": "architecture-evolution", "x": 24, "y": 436, "w": 204, "h": 34, "small": false},
  {"id": "ch12", "label": "完整模型：拼起来训一遍", "ch": 12, "slug": "tinyllm-model", "x": 24, "y": 482, "w": 204, "h": 34, "small": false},
  {"id": "pipe", "label": "数据管线：清洗 去重 划分", "ch": 14, "slug": "data-pipeline", "x": 24, "y": 92, "w": 204, "h": 34, "small": false},
  {"id": "tok", "label": "分词器：文本 → token ID", "ch": 4, "slug": "tokenization", "x": 24, "y": 160, "w": 204, "h": 34, "small": false},
  {"id": "emb", "label": "词嵌入：token ID → 向量", "ch": 5, "slug": "embeddings-and-output", "x": 300, "y": 66, "w": 240, "h": 34, "small": false},
  {"id": "n1", "label": "RMSNorm", "ch": 11, "slug": "normalization", "x": 330, "y": 138, "w": 180, "h": 28, "small": false},
  {"id": "att", "label": "因果自注意力", "ch": 6, "slug": "self-attention", "x": 330, "y": 184, "w": 180, "h": 34, "small": false},
  {"id": "pos", "label": "RoPE", "ch": 7, "slug": "position-encoding", "x": 522, "y": 184, "w": 70, "h": 34, "small": true},
  {"id": "kern", "label": "内核", "ch": 29, "slug": "attention-kernels", "x": 522, "y": 226, "w": 70, "h": 28, "small": true},
  {"id": "n2", "label": "RMSNorm", "ch": 11, "slug": "normalization", "x": 330, "y": 286, "w": 180, "h": 28, "small": false},
  {"id": "ffn", "label": "SwiGLU 前馈层", "ch": 8, "slug": "activations-and-ffn", "x": 330, "y": 332, "w": 180, "h": 34, "small": false},
  {"id": "moe", "label": "MoE", "ch": 26, "slug": "mixture-of-experts", "x": 522, "y": 332, "w": 70, "h": 34, "small": true},
  {"id": "nf", "label": "最终 RMSNorm", "ch": 11, "slug": "normalization", "x": 330, "y": 434, "w": 180, "h": 28, "small": false},
  {"id": "out", "label": "输出层：向量 → logits", "ch": 5, "slug": "embeddings-and-output", "x": 300, "y": 484, "w": 240, "h": 34, "small": false},
  {"id": "eval", "label": "诊断与评估", "ch": 22, "slug": "training-evaluation", "x": 650, "y": 118, "w": 160, "h": 34, "small": false},
  {"id": "hp", "label": "超参数与调参", "ch": 23, "slug": "hyperparameter-tuning", "x": 820, "y": 118, "w": 160, "h": 34, "small": false},
  {"id": "gpu", "label": "GPU 上训练", "ch": 13, "slug": "gpu-training", "x": 650, "y": 72, "w": 104, "h": 34, "small": false},
  {"id": "scale", "label": "缩放定律", "ch": 24, "slug": "scaling-laws", "x": 762, "y": 72, "w": 104, "h": 34, "small": false},
  {"id": "big", "label": "稳定性与并行", "ch": 25, "slug": "large-model-stability", "x": 874, "y": 72, "w": 106, "h": 34, "small": false},
  {"id": "prec", "label": "数值精度 / 混合精度", "ch": 19, "slug": "precision", "x": 664, "y": 196, "w": 190, "h": 34, "small": false},
  {"id": "reg", "label": "正则化", "ch": 18, "slug": "regularization", "x": 866, "y": 252, "w": 100, "h": 34, "small": false},
  {"id": "opt", "label": "优化器更新参数", "ch": 16, "slug": "optimizers", "x": 664, "y": 300, "w": 190, "h": 34, "small": false},
  {"id": "lr", "label": "学习率调度", "ch": 17, "slug": "learning-rate", "x": 866, "y": 300, "w": 100, "h": 34, "small": false},
  {"id": "clip", "label": "梯度裁剪 / 累积", "ch": 20, "slug": "gradient-stability", "x": 664, "y": 364, "w": 190, "h": 34, "small": false},
  {"id": "bwd", "label": "backward 求梯度", "ch": 2, "slug": "tensors-and-autograd", "x": 664, "y": 418, "w": 190, "h": 34, "small": false},
  {"id": "loss", "label": "交叉熵损失", "ch": 15, "slug": "language-model-loss", "x": 664, "y": 474, "w": 190, "h": 34, "small": false},
  {"id": "gen", "label": "采样：logits → 下一个 token", "ch": 27, "slug": "generation", "x": 300, "y": 578, "w": 240, "h": 34, "small": false},
  {"id": "kv", "label": "KV cache", "ch": 28, "slug": "inference-efficiency", "x": 24, "y": 660, "w": 140, "h": 34, "small": false},
  {"id": "quant", "label": "量化", "ch": 30, "slug": "quantization", "x": 174, "y": 660, "w": 140, "h": 34, "small": false},
  {"id": "spec", "label": "投机解码", "ch": 31, "slug": "speculative-decoding", "x": 324, "y": 660, "w": 140, "h": 34, "small": false},
  {"id": "batch", "label": "批处理与调度", "ch": 32, "slug": "batching", "x": 474, "y": 660, "w": 140, "h": 34, "small": false},
  {"id": "kvmem", "label": "KV 显存管理", "ch": 33, "slug": "kv-memory", "x": 24, "y": 712, "w": 140, "h": 34, "small": false},
  {"id": "serve", "label": "推理优化：逐项对照与服务", "ch": 34, "slug": "inference-optimization", "x": 174, "y": 712, "w": 290, "h": 34, "small": false},
  {"id": "mid1", "label": "退火与配比", "ch": 35, "slug": "annealing", "x": 650, "y": 590, "w": 104, "h": 34, "small": false},
  {"id": "mid2", "label": "长上下文", "ch": 36, "slug": "long-context", "x": 762, "y": 590, "w": 104, "h": 34, "small": false},
  {"id": "mid3", "label": "继续预训练", "ch": 37, "slug": "continued-pretraining", "x": 874, "y": 590, "w": 106, "h": 34, "small": false},
  {"id": "sft", "label": "指令微调 SFT", "ch": 38, "slug": "instruction-finetuning", "x": 650, "y": 636, "w": 104, "h": 34, "small": false},
  {"id": "lora", "label": "LoRA", "ch": 39, "slug": "lora-finetuning", "x": 762, "y": 636, "w": 104, "h": 34, "small": false},
  {"id": "distill", "label": "蒸馏", "ch": 40, "slug": "distillation", "x": 874, "y": 636, "w": 106, "h": 34, "small": false},
  {"id": "rlhf", "label": "RLHF + PPO", "ch": 41, "slug": "rlhf", "x": 650, "y": 682, "w": 104, "h": 34, "small": false},
  {"id": "dpo", "label": "DPO", "ch": 42, "slug": "preference-alignment", "x": 762, "y": 682, "w": 104, "h": 34, "small": false},
  {"id": "grpo", "label": "GRPO", "ch": 43, "slug": "grpo", "x": 874, "y": 682, "w": 106, "h": 34, "small": false},
  {"id": "agent", "label": "Agent：组装上下文 → 模型 → 调工具", "ch": 44, "slug": "llm-agent-interaction", "x": 650, "y": 732, "w": 330, "h": 40, "small": false}
]

const edges: Edge[] = [
  {"f": null, "t": "pipe", "d": "M126,70 V92", "kind": "flow", "label": "唐诗原文", "at": [126, 62]},
  {"f": "pipe", "t": "tok", "d": "M126,126 V160", "kind": "flow", "label": null, "at": null},
  {"f": "tok", "t": "emb", "d": "M126,194 V232 H248 V83 H300", "kind": "flow", "label": "token ID [B, T]", "at": [184, 248]},
  {"f": "emb", "t": "n1", "d": "M420,100 V138", "kind": "flow", "label": null, "at": null},
  {"f": "n1", "t": "att", "d": "M420,166 V184", "kind": "flow", "label": null, "at": null},
  {"f": "pos", "t": "att", "d": "M522,201 H510", "kind": "side", "label": null, "at": null},
  {"f": "kern", "t": "att", "d": "M522,240 H500 V218", "kind": "side", "label": null, "at": null},
  {"f": "att", "t": "n2", "d": "M420,218 V250", "kind": "flow", "label": null, "at": null},
  {"f": "n2", "t": "ffn", "d": "M420,314 V332", "kind": "flow", "label": null, "at": null},
  {"f": "moe", "t": "ffn", "d": "M522,349 H510", "kind": "side", "label": null, "at": null},
  {"f": "ffn", "t": "nf", "d": "M420,366 V388", "kind": "flow", "label": null, "at": null},
  {"f": "nf", "t": "out", "d": "M420,462 V484", "kind": "flow", "label": null, "at": null},
  {"f": "out", "t": "loss", "d": "M540,501 H664", "kind": "flow", "label": "logits", "at": [600, 494]},
  {"f": "loss", "t": "bwd", "d": "M759,474 V452", "kind": "flow", "label": null, "at": null},
  {"f": "bwd", "t": "clip", "d": "M759,418 V398", "kind": "flow", "label": null, "at": null},
  {"f": "clip", "t": "opt", "d": "M759,364 V334", "kind": "flow", "label": null, "at": null},
  {"f": "lr", "t": "opt", "d": "M866,317 H854", "kind": "side", "label": null, "at": null},
  {"f": "reg", "t": "opt", "d": "M916,286 V296 H854", "kind": "side", "label": null, "at": null},
  {"f": "opt", "t": "ffn", "d": "M664,317 H632 V262 H604", "kind": "train", "label": "更新参数", "at": [634, 254]},
  {"f": "prec", "t": "block", "d": "M664,213 H604", "kind": "side", "label": "计算格式", "at": [634, 228]},
  {"f": "hp", "t": "loop", "d": "M900,152 V168", "kind": "side", "label": null, "at": null},
  {"f": "loop", "t": "eval", "d": "M730,168 V152", "kind": "side", "label": null, "at": null},
  {"f": "out", "t": "gen", "d": "M420,518 V578", "kind": "flow", "label": null, "at": null},
  {"f": "gen", "t": "tok", "d": "M300,595 H264 V252 H250", "kind": "loop", "label": "新 token 接到输入末尾", "at": [196, 590]},
  {"f": "gen", "t": null, "d": "M420,612 V632", "kind": "flow", "label": null, "at": null},
  {"f": "mid3", "t": "loop", "d": "M927,590 V548 H812 V530", "kind": "train", "label": "换数据和目标，复用训练循环", "at": [820, 556]},
  {"f": "sft", "t": "loop", "d": "M650,653 H642 V548 H812 V530", "kind": "train", "label": null, "at": null},
  {"f": "agent", "t": "tok", "d": "M650,752 H630 V553 H244 V177 H228", "kind": "loop", "label": "改上下文：重新分词", "at": [574, 578]}
]

const residuals = ["M420,126 H296 V262 H408", "M420,274 H296 V400 H408"]
const adds = [[420, 262], [420, 400]]
const notes = [[318, 650, "这几章不改输出，只让每一步生成更快、更省"]]

const activeSet = computed(() => new Set((props.active ?? '').split(',').map(s => s.trim()).filter(Boolean)))
const isActive = (slug: string) => activeSet.value.has(slug)
const anyActive = (slugs: string[]) => slugs.some(isActive)
const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]))
const containerById = Object.fromEntries(containers.map(c => [c.id, c]))
const endpointActive = (id: string | null) => {
  if (!id) return false
  if (nodeById[id]) return isActive(nodeById[id].slug)
  if (containerById[id]) return anyActive(containerById[id].slugs)
  return false
}
const edgeActive = (e: Edge) => endpointActive(e.f) || endpointActive(e.t)
const residualActive = computed(() => isActive('initialization-and-residuals'))
const ioLines = computed(() => [...activeSet.value].filter(s => io[s]).map(s => io[s]))
const href = (slug: string) => withBase(`/tinyllm/${slug}`)
const svgRoot = ref<SVGSVGElement | null>(null)
useSvgLinkPrefetchFix(svgRoot)
</script>

<template>
  <figure :class="['tinyllm-map', { compact: !!active }]">
    <svg ref="svgRoot" viewBox="0 0 1000 800" role="img" aria-label="TinyLLM 全书地图：数据经数据管线和分词器变成 token，模型做一次前向得到 logits；训练时经损失、反向传播、梯度处理和优化器更新参数；推理时从 logits 采样下一个 token 接回输入；后训练复用训练循环，Agent 组装上下文再送回模型">
      <defs>
        <marker id="tm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" class="tm-arrowhead" />
        </marker>
        <marker id="tm-arrow-hot" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" class="tm-arrowhead hot" />
        </marker>
      </defs>

      <g v-for="s in sections" :key="s.id">
        <rect :x="s.x" :y="s.y" :width="s.w" :height="s.h" rx="12" :class="['tm-section', { active: anyActive(s.slugs) }]" />
        <text :x="s.x + 12" :y="s.y + 20" class="tm-section-title">{{ s.title }}</text>
      </g>

      <a v-for="c in containers" :key="c.id" :href="href(c.slug)">
        <rect :x="c.x" :y="c.y" :width="c.w" :height="c.h" rx="10" :class="['tm-container', { active: anyActive(c.slugs), planned: !done.has(c.slug) }]" />
        <text :x="c.x + c.w - 8" :y="c.y + 16" text-anchor="end" class="tm-container-label">{{ c.label }} · {{ c.ch }}</text>
      </a>

      <a :href="href('initialization-and-residuals')">
        <path v-for="(d, i) in residuals" :key="'r' + i" :d="d" :class="['tm-residual', { active: residualActive }]"
          :marker-end="residualActive ? 'url(#tm-arrow-hot)' : 'url(#tm-arrow)'" />
        <text x="290" y="340" text-anchor="middle" class="tm-side-label" transform="rotate(-90 290 340)">残差 · 10</text>
      </a>

      <g v-for="(e, i) in edges" :key="'e' + i">
        <path :d="e.d" :class="['tm-edge', e.kind, { hot: edgeActive(e) }]" :marker-end="edgeActive(e) ? 'url(#tm-arrow-hot)' : 'url(#tm-arrow)'" />
        <text v-if="e.label && e.at" :x="e.at[0]" :y="e.at[1]" text-anchor="middle" :class="['tm-edge-label', { hot: edgeActive(e) }]">{{ e.label }}</text>
      </g>

      <text v-for="(n, i) in notes" :key="'n' + i" :x="n[0]" :y="n[1]" text-anchor="middle" class="tm-note">{{ n[2] }}</text>

      <g v-for="(a, i) in adds" :key="'a' + i">
        <circle :cx="a[0]" :cy="a[1]" r="11" :class="['tm-add', { active: residualActive }]" />
        <text :x="a[0]" :y="a[1] + 5" text-anchor="middle" class="tm-add-text">+</text>
      </g>

      <a v-for="n in nodes" :key="n.id" :href="href(n.slug)">
        <rect :x="n.x" :y="n.y" :width="n.w" :height="n.h" rx="7"
          :class="['tm-node', { active: isActive(n.slug), planned: !done.has(n.slug) }]" />
        <text :x="n.x + n.w / 2" :y="n.y + n.h / 2 + 1" text-anchor="middle" dominant-baseline="middle" :class="['tm-label', { small: n.small }]">{{ n.label }}</text>
        <text :x="n.x + n.w - 4" :y="n.y + n.h - 4" text-anchor="end" class="tm-ch">{{ n.ch }}</text>
      </a>
    </svg>
    <figcaption v-if="props.caption">
      <template v-if="ioLines.length">
        <span v-for="(l, i) in ioLines" :key="i" class="tm-io"><strong>本章输入：</strong>{{ l[0] }}<span class="tm-io-arrow">→</span><strong>输出：</strong>{{ l[1] }}</span>
      </template>
      <span class="tm-legend">TinyLLM 全书地图。<span class="tm-key active">高亮</span>的是本章，蓝色连线是它的输入和输出；实线框已成文，虚线框还在规划中；右下角数字是章节号，点击可跳到对应章节。</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.tinyllm-map { margin: 1.25rem 0 1.75rem; }
.tinyllm-map a, .tinyllm-map a:hover { text-decoration: none; }
.tinyllm-map svg text { text-decoration: none; }
.tinyllm-map svg { width: 100%; max-width: 820px; height: auto; display: block; margin: 0 auto; font-family: var(--vp-font-family-base); }
.tinyllm-map figcaption { font-size: 0.85rem; color: var(--vp-c-text-2); text-align: center; margin-top: 0.5rem; line-height: 1.6; }
.tm-io { display: block; color: var(--vp-c-text-1); margin-bottom: 0.25rem; }
.tm-io-arrow { margin: 0 0.5em; color: var(--vp-c-brand-1); }
.tm-legend { display: block; }
.tm-section { fill: var(--vp-c-bg-soft); stroke: var(--vp-c-divider); stroke-width: 1.2; }
.tm-section.active { fill: var(--vp-c-brand-soft); stroke: var(--vp-c-brand-1); }
.tm-section-title { font-size: 13px; font-weight: 600; fill: var(--vp-c-text-2); }
.tm-container { fill: none; stroke: var(--vp-c-text-3); stroke-width: 1.2; }
.tm-container.planned { stroke-dasharray: 6 5; }
.tm-container.active { stroke: var(--vp-c-brand-1); stroke-width: 2.4; fill: var(--vp-c-brand-soft); }
.tm-container-label { font-size: 12px; fill: var(--vp-c-text-2); }
.tm-node { fill: var(--vp-c-bg); stroke: var(--vp-c-text-3); stroke-width: 1.1; transition: fill .15s; }
.tm-node.planned { stroke-dasharray: 5 4; }
.tm-node.active { fill: var(--vp-c-brand-soft); stroke: var(--vp-c-brand-1); stroke-width: 2.4; }
a:hover .tm-node { fill: var(--vp-c-default-soft); }
a:hover .tm-node.active { fill: var(--vp-c-brand-soft); }
.tm-label { font-size: 13.5px; fill: var(--vp-c-text-1); pointer-events: none; }
.tm-label.small { font-size: 12.5px; }
.tm-ch { font-size: 9.5px; fill: var(--vp-c-text-3); pointer-events: none; }
.tm-edge { stroke: var(--vp-c-text-2); stroke-width: 1.3; fill: none; }
.tm-edge.side { stroke-dasharray: 4 3; }
.tm-edge.loop { stroke-dasharray: 5 4; }
.tm-edge.train { stroke-dasharray: 3 3; }
.tm-edge.hot { stroke: var(--vp-c-brand-1); stroke-width: 2.4; }
.tm-edge-label { font-size: 11px; fill: var(--vp-c-text-2); }
.tm-edge-label.hot { fill: var(--vp-c-brand-1); font-weight: 600; }
.tm-note { font-size: 12px; fill: var(--vp-c-text-2); }
.tm-arrowhead { fill: var(--vp-c-text-2); }
.tm-arrowhead.hot { fill: var(--vp-c-brand-1); }
.tm-residual { stroke: var(--vp-c-text-3); stroke-width: 1.6; fill: none; }
.tm-residual.active { stroke: var(--vp-c-brand-1); stroke-width: 3; }
.tm-add { fill: var(--vp-c-bg); stroke: var(--vp-c-text-2); stroke-width: 1.4; }
.tm-add.active { stroke: var(--vp-c-brand-1); stroke-width: 2.4; fill: var(--vp-c-brand-soft); }
.tm-add-text { font-size: 15px; font-weight: 600; fill: var(--vp-c-text-1); pointer-events: none; }
.tm-side-label { font-size: 11px; fill: var(--vp-c-text-3); }
.tm-key.active { background: var(--vp-c-brand-soft); border: 1.5px solid var(--vp-c-brand-1); border-radius: 4px; padding: 0 4px; }
</style>
