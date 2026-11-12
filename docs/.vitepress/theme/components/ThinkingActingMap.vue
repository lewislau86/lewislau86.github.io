<script setup lang="ts">
const parts = ['Transformer 与 GPT', '模型效率与推理', 'Agent 基础', 'Agent 自我改进', '评测与开放问题']
</script>

<template>
  <figure class="paper-map" aria-label="全书学习路线，本章位于 Transformer 与 GPT">
    <div class="paper-map-title">全书学习路线 · 本章位置</div>
    <div class="paper-map-path">
      <div v-for="(part, i) in parts" :key="part" class="paper-map-step" :class="{ active: i === 0 }">
        <span>{{ i + 1 }}</span><strong>{{ part }}</strong>
        <small>{{ i === 0 ? '本章：Transformer' : '规划中' }}</small>
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
