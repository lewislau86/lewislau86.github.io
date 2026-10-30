<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSvgLinkPrefetchFix } from './svgLinks'
import { withBase } from 'vitepress'

// 全书唯一的 TinyLLM 架构总图。每章开头用 <TinyLLMMap active="slug" /> 高亮本章负责的零件。
// 新章节成文后，把它的 slug 加进 done；架构变化时只改这里的 nodes。
const props = defineProps<{ active?: string; caption?: boolean }>()

const done = new Set([
  'first-run', 'tensors-and-autograd', 'architecture-evolution', 'initialization-and-residuals', 'normalization',
  'activations-and-ffn', 'transformer-block', 'tokenization', 'self-attention', 'position-encoding', 'embeddings-and-output', 'optimizers', 'precision',
  'tinyllm-model', 'gpu-training'
])

type Node = { id: string; label: string; ch: number; slug: string; x: number; y: number; w: number; h: number }
const nodes: Node[] = [
  { id: 'tok', label: '分词器：文本 → token ID', ch: 4, slug: 'tokenization', x: 140, y: 52, w: 240, h: 36 },
  { id: 'emb', label: '词嵌入：ID → 向量', ch: 5, slug: 'embeddings-and-output', x: 140, y: 108, w: 240, h: 36 },
  { id: 'n1', label: 'RMSNorm', ch: 11, slug: 'normalization', x: 160, y: 196, w: 200, h: 32 },
  { id: 'att', label: '因果自注意力', ch: 6, slug: 'self-attention', x: 160, y: 244, w: 200, h: 36 },
  { id: 'pos', label: '位置 RoPE', ch: 7, slug: 'position-encoding', x: 400, y: 244, w: 120, h: 36 },
  { id: 'n2', label: 'RMSNorm', ch: 11, slug: 'normalization', x: 160, y: 334, w: 200, h: 32 },
  { id: 'ffn', label: 'SwiGLU 前馈层', ch: 8, slug: 'activations-and-ffn', x: 160, y: 382, w: 200, h: 36 },
  { id: 'nf', label: '最终 RMSNorm', ch: 11, slug: 'normalization', x: 140, y: 494, w: 240, h: 34 },
  { id: 'out', label: '输出层：向量 → logits', ch: 5, slug: 'embeddings-and-output', x: 140, y: 546, w: 240, h: 36 },
  { id: 'gen', label: '逐个生成 token', ch: 25, slug: 'generation', x: 140, y: 604, w: 240, h: 34 },
  { id: 'loss', label: '交叉熵损失', ch: 15, slug: 'language-model-loss', x: 470, y: 546, w: 190, h: 34 },
  { id: 'grad', label: 'backward 求梯度', ch: 2, slug: 'tensors-and-autograd', x: 470, y: 494, w: 190, h: 34 },
  { id: 'opt', label: '优化器更新参数', ch: 16, slug: 'optimizers', x: 470, y: 442, w: 190, h: 34 },
  { id: 'prec', label: '数值精度 / 混合精度', ch: 19, slug: 'precision', x: 470, y: 390, w: 190, h: 34 }
]

const activeSet = computed(() => new Set((props.active ?? '').split(',').map(s => s.trim()).filter(Boolean)))
const isActive = (slug: string) => activeSet.value.has(slug)
const blockActive = computed(() => isActive('transformer-block') || isActive('tinyllm-model'))
const residualActive = computed(() => isActive('initialization-and-residuals'))
const modelActive = computed(() => isActive('tinyllm-model') || isActive('first-run'))
const href = (slug: string) => withBase(`/tinyllm/${slug}`)
const svgRoot = ref<SVGSVGElement | null>(null)
useSvgLinkPrefetchFix(svgRoot)
</script>

<template>
  <figure :class="['tinyllm-map', { compact: !!active }]">
    <svg ref="svgRoot" viewBox="0 0 700 660" role="img" aria-label="TinyLLM 架构总图：文本经分词、词嵌入、N 个 Transformer Block、最终归一化与输出层得到 logits；训练时由损失、反向传播与优化器更新参数">
      <defs>
        <marker id="tm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" class="tm-arrowhead" />
        </marker>
      </defs>

      <rect v-if="modelActive" x="120" y="40" width="280" height="610" rx="14" class="tm-model-glow" />

      <text x="260" y="26" text-anchor="middle" class="tm-plain">“我在学习 TinyLLM”</text>
      <line x1="260" y1="32" x2="260" y2="50" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="88" x2="260" y2="106" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="144" x2="260" y2="170" class="tm-edge" marker-end="url(#tm-arrow)" />

      <!-- Transformer Block -->
      <a :href="href('transformer-block')">
        <rect x="120" y="172" width="280" height="290" rx="12" :class="['tm-block', { active: blockActive, planned: !done.has('transformer-block') }]" />
        <text x="408" y="186" class="tm-block-label">Transformer Block</text>
        <text x="408" y="202" class="tm-block-label">× N · 第 9 章</text>
      </a>

      <!-- 主干与残差 -->
      <line x1="260" y1="228" x2="260" y2="242" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="280" x2="260" y2="300" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="324" x2="260" y2="332" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="366" x2="260" y2="380" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="418" x2="260" y2="430" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="454" x2="260" y2="492" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="174" x2="260" y2="194" class="tm-edge" marker-end="url(#tm-arrow)" />

      <a :href="href('initialization-and-residuals')">
        <path d="M260,184 H146 V312 H246" :class="['tm-residual', { active: residualActive }]" marker-end="url(#tm-arrow)" />
        <path d="M260,326 H146 V442 H246" :class="['tm-residual', { active: residualActive }]" marker-end="url(#tm-arrow)" />
        <circle cx="260" cy="312" r="12" :class="['tm-add', { active: residualActive }]" />
        <text x="260" y="317" text-anchor="middle" class="tm-add-text">+</text>
        <circle cx="260" cy="442" r="12" :class="['tm-add', { active: residualActive }]" />
        <text x="260" y="447" text-anchor="middle" class="tm-add-text">+</text>
        <text x="135" y="380" text-anchor="middle" class="tm-side-label" transform="rotate(-90 135 380)">残差 · 第 10 章</text>
      </a>

      <line x1="400" y1="262" x2="362" y2="262" class="tm-edge" marker-end="url(#tm-arrow)" />

      <!-- 输出与训练 -->
      <line x1="260" y1="528" x2="260" y2="544" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="260" y1="582" x2="260" y2="602" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="380" y1="563" x2="468" y2="563" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="565" y1="546" x2="565" y2="530" class="tm-edge" marker-end="url(#tm-arrow)" />
      <line x1="565" y1="494" x2="565" y2="478" class="tm-edge" marker-end="url(#tm-arrow)" />
      <path d="M470,459 H420 V330 H402" class="tm-train" marker-end="url(#tm-arrow)" />
      <text x="565" y="378" text-anchor="middle" class="tm-side-label">训练时才走右侧这一列</text>
      <text x="424" y="320" class="tm-side-label">更新参数</text>

      <a v-for="n in nodes" :key="n.id" :href="href(n.slug)">
        <rect :x="n.x" :y="n.y" :width="n.w" :height="n.h" rx="8"
          :class="['tm-node', { active: isActive(n.slug), planned: !done.has(n.slug) }]" />
        <text :x="n.x + n.w / 2" :y="n.y + n.h / 2 - 1" text-anchor="middle" dominant-baseline="middle" class="tm-label">{{ n.label }}</text>
        <text :x="n.x + n.w - 6" :y="n.y + n.h - 5" text-anchor="end" class="tm-ch">{{ n.ch }}</text>
      </a>
    </svg>
    <figcaption v-if="caption !== false">
      TinyLLM 全书地图。<span class="tm-key active">高亮</span>是本章负责的零件；实线框已成文，虚线框还在规划中；右下角数字是章节号，点击任一零件可跳到对应章节。
    </figcaption>
  </figure>
</template>

<style scoped>
.tinyllm-map { margin: 1.25rem 0 1.75rem; }
.tinyllm-map a, .tinyllm-map a:hover { text-decoration: none; }
.tinyllm-map svg text { text-decoration: none; }
.tinyllm-map.compact svg { max-width: 500px; }
.tinyllm-map svg { width: 100%; max-width: 640px; height: auto; display: block; margin: 0 auto; font-family: var(--vp-font-family-base); }
.tinyllm-map figcaption { font-size: 0.85rem; color: var(--vp-c-text-2); text-align: center; margin-top: 0.5rem; line-height: 1.6; }
.tm-node { fill: var(--vp-c-bg-soft); stroke: var(--vp-c-text-3); stroke-width: 1.2; transition: fill .15s; }
.tm-node.planned { stroke-dasharray: 5 4; }
.tm-node.active { fill: var(--vp-c-brand-soft); stroke: var(--vp-c-brand-1); stroke-width: 2.4; }
a:hover .tm-node { fill: var(--vp-c-default-soft); }
a:hover .tm-node.active { fill: var(--vp-c-brand-soft); }
.tm-label { font-size: 14px; fill: var(--vp-c-text-1); pointer-events: none; }
.tm-ch { font-size: 10px; fill: var(--vp-c-text-3); pointer-events: none; }
.tm-plain { font-size: 14px; fill: var(--vp-c-text-2); }
.tm-block { fill: none; stroke: var(--vp-c-text-3); stroke-width: 1.2; }
.tm-block.planned { stroke-dasharray: 6 5; }
.tm-block.active { stroke: var(--vp-c-brand-1); stroke-width: 2.4; fill: var(--vp-c-brand-soft); }
.tm-block-label { font-size: 12px; fill: var(--vp-c-text-2); }
.tm-model-glow { fill: var(--vp-c-brand-soft); stroke: var(--vp-c-brand-1); stroke-width: 1.5; stroke-dasharray: 4 4; }
.tm-edge { stroke: var(--vp-c-text-2); stroke-width: 1.4; fill: none; }
.tm-arrowhead { fill: var(--vp-c-text-2); }
.tm-residual { stroke: var(--vp-c-text-3); stroke-width: 1.6; fill: none; }
.tm-residual.active { stroke: var(--vp-c-brand-1); stroke-width: 3; }
.tm-train { stroke: var(--vp-c-text-3); stroke-width: 1.4; fill: none; stroke-dasharray: 3 3; }
.tm-add { fill: var(--vp-c-bg); stroke: var(--vp-c-text-2); stroke-width: 1.4; }
.tm-add.active { stroke: var(--vp-c-brand-1); stroke-width: 2.4; fill: var(--vp-c-brand-soft); }
.tm-add-text { font-size: 16px; font-weight: 600; fill: var(--vp-c-text-1); pointer-events: none; }
.tm-side-label { font-size: 11px; fill: var(--vp-c-text-3); }
.tm-key.active { background: var(--vp-c-brand-soft); border: 1.5px solid var(--vp-c-brand-1); border-radius: 4px; padding: 0 4px; }
</style>
