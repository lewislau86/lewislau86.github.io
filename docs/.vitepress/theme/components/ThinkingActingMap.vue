<script setup lang="ts">
import { computed } from 'vue'

// active：本章所在部分的序号（从 0 开始）；label：在高亮框里显示的本章说明。
const props = withDefaults(defineProps<{ active?: number; label?: string }>(), {
  active: 0,
  label: '本章：Transformer',
})

// 每部分已成文的章节；新章节成文后在这里登记。
const parts = [
  { name: 'Transformer 与 GPT', written: ['Transformer'] },
  { name: '模型效率与推理', written: [] as string[] },
  { name: 'Agent 基础', written: ['Agent 记忆', 'Claude Code 记忆案例'] },
  { name: 'Agent 自我改进', written: [] as string[] },
  { name: '评测与开放问题', written: [] as string[] },
]

const ariaLabel = computed(() => `全书学习路线，本章位于${parts[props.active]?.name ?? ''}`)

function status(i: number) {
  if (i === props.active) return props.label
  const n = parts[i].written.length
  return n ? `已成文：${parts[i].written.join('、')}` : '规划中'
}
</script>

<template>
  <figure class="paper-map" :aria-label="ariaLabel">
    <div class="paper-map-title">全书学习路线 · 本章位置</div>
    <div class="paper-map-path">
      <div v-for="(part, i) in parts" :key="part.name" class="paper-map-step" :class="{ active: i === props.active }">
        <span>{{ i + 1 }}</span><strong>{{ part.name }}</strong>
        <small>{{ status(i) }}</small>
      </div>
    </div>
    <figcaption>从模型架构出发，逐步走向推理、行动、自我改进与评测。</figcaption>
  </figure>
</template>

<style scoped>
.paper-map { margin: 1.5rem 0 2rem; padding: 1rem; border: 1px solid var(--vp-c-divider); border-radius: 12px; background: var(--vp-c-bg-soft); }
.paper-map-title { font-weight: 600; margin-bottom: .8rem; }
.paper-map-path { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: .5rem; }
.paper-map-step { display: flex; flex-direction: column; gap: .25rem; padding: .7rem; border: 1px dashed var(--vp-c-divider); border-radius: 8px; background: var(--vp-c-bg); font-size: .85rem; }
.paper-map-step.active { border: 2px solid var(--vp-c-brand-1); background: var(--vp-c-brand-soft); }
.paper-map-step span, .paper-map-step small, .paper-map figcaption { color: var(--vp-c-text-2); }
.paper-map figcaption { font-size: .8rem; text-align: center; margin-top: .7rem; }
</style>
