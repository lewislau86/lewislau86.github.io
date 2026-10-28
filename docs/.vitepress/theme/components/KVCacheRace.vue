<script setup lang="ts">
import { computed, reactive } from 'vue'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 每一步投影的 K/V 行数由 docs/public/tinyllm/code/inference-efficiency.py 的 count 段真实数出，这里只负责播放。
import d from '../../../../scripts/data/tinyllm-kv-cache-counts.json'

const tokens: string[] = d.tokens
const T = tokens.length
const p = reactive(usePlayer(() => T, { interval: 900, start: 'last' }))
const t = computed(() => p.frame)
const sum = (a: number[], k: number) => a.slice(0, k + 1).reduce((s, x) => s + x, 0)

const panels = computed(() => [
  { key: 'full', title: '不缓存：每一步把前面所有字重新算一遍 K、V', now: d.no_cache[t.value], total: sum(d.no_cache, t.value),
    state: (j: number) => (j > t.value ? 'future' : 'recompute') },
  { key: 'cache', title: 'KV cache：旧字的 K、V 从缓存里拿，只算新来的一个', now: d.with_cache[t.value], total: sum(d.with_cache, t.value),
    state: (j: number) => (j > t.value ? 'future' : j === t.value ? 'new' : 'cached') }
])
</script>

<template>
  <figure class="anim-card kv">
    <div v-for="pn in panels" :key="pn.key" class="kv-panel">
      <div class="kv-title">{{ pn.title }}</div>
      <div class="kv-grid" :style="{ gridTemplateColumns: `2.4rem repeat(${T}, minmax(1.6rem, 1fr))` }">
        <span class="kv-rl" />
        <span v-for="(c, j) in tokens" :key="'t' + j" :class="['kv-tok', { cur: j === t, fut: j > t }]">{{ c }}</span>
        <template v-for="row in ['K', 'V']" :key="row">
          <span class="kv-rl">{{ row }}</span>
          <span v-for="(_, j) in tokens" :key="row + j" :class="['kv-cell', pn.state(j)]" />
        </template>
      </div>
      <div class="kv-count">这一步算了 <b>{{ pn.now }}</b> 行 K、V · 累计 <b>{{ pn.total }}</b> 行</div>
    </div>
    <div class="kv-key">
      <span><i class="kv-cell recompute" />本步重新计算</span>
      <span><i class="kv-cell new" />本步新算</span>
      <span><i class="kv-cell cached" />从缓存读取</span>
    </div>
    <p class="anim-caption">
      生成第 {{ t + 1 }} 个字“{{ tokens[t] }}”时，新字的 Q 都要和前面所有字的 K 打分、对所有 V 加权求和。区别只在 K、V 从哪里来：
      不缓存时前面 {{ t + 1 }} 个字全部重算，生成 {{ T }} 个字一共算 {{ sum(d.no_cache, T - 1) }} 行；有缓存时每步只算 1 行，一共 {{ sum(d.with_cache, T - 1) }} 行，两种做法的输出完全一样。
    </p>
    <PlayerControls :p="p" :label="`第 ${t + 1} / ${T} 个字`" />
    <figcaption>每一步的行数由本章 inference-efficiency.py 中 count 那段代码真实数出，并核对了两种做法输出一致；字只是位置的标签。一开始显示生成完 {{ T }} 个字时的状态；点“播放”从第一个字重演。</figcaption>
  </figure>
</template>

<style scoped>
.kv-panel { padding: 0.5rem 0.6rem 0.6rem; border-radius: 10px; background: var(--vp-c-bg); margin-bottom: 0.7rem; }
.kv-title { font-size: 0.88rem; font-weight: 600; margin-bottom: 0.45rem; }
.kv-grid { display: grid; gap: 3px; }
.kv-rl { font-size: 0.78rem; color: var(--vp-c-text-2); display: flex; align-items: center; }
.kv-tok { font-size: 0.95rem; text-align: center; }
.kv-tok.cur { color: var(--vp-c-brand-1); font-weight: 700; }
.kv-tok.fut { color: var(--vp-c-text-3); opacity: 0.45; }
.kv-cell { height: 1.2rem; border-radius: 4px; border: 1px solid var(--vp-c-divider); transition: background 0.3s; display: inline-block; }
.kv-cell.future { background: transparent; border-style: dashed; opacity: 0.5; }
.kv-cell.recompute { background: #f59e0b; border-color: #d97706; }
.kv-cell.new { background: #10b981; border-color: #059669; }
.kv-cell.cached { background: var(--vp-c-default-soft); }
.kv-count { font-size: 0.85rem; color: var(--vp-c-text-2); margin-top: 0.4rem; }
.kv-count b { color: var(--vp-c-text-1); font-variant-numeric: tabular-nums; }
.kv-key { display: flex; flex-wrap: wrap; gap: 0.3rem 1rem; font-size: 0.8rem; color: var(--vp-c-text-2); }
.kv-key span { display: inline-flex; align-items: center; gap: 0.35rem; }
.kv-key .kv-cell { width: 1rem; height: 0.8rem; }
@media (prefers-reduced-motion: reduce) { .kv-cell { transition: none; } }
</style>
