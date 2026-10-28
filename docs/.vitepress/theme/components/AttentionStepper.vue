<script setup lang="ts">
import { computed, reactive } from 'vue'
import { withBase } from 'vitepress'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 数据由 docs/public/tinyllm/code/self-attention.py 的 hand/causal 两段代码算出并保存，这里只负责播放。
import d from '../../../../scripts/data/tinyllm-attention-steps.json'

const names: string[] = d.names
const PHASES = ['① 打分', '② 遮住未来', '③ softmax', '④ 按权重取 V']
const p = reactive(usePlayer(() => names.length * 4, { interval: 1300, start: 'last' }))
const r = computed(() => Math.floor(p.frame / 4))     // 正在计算第几行
const ph = computed(() => p.frame % 4)                // 这一行进行到第几步

const f2 = (x: number) => x.toFixed(2)
const shown = (row: number, phase: number) => row < r.value || (row === r.value && ph.value >= phase)
const isFuture = (i: number, j: number) => d.future[i][j]

const caption = computed(() => {
  const i = r.value, n = names[i], q = d.Q[i]
  if (ph.value === 0) {
    const parts = names.map((m, j) => `${m} (${q[0]}·${d.K[j][0]} + ${q[1]}·${d.K[j][1]}) / √2 = ${f2(d.scores[i][j])}`)
    return `<b>第 ${i + 1} 行“${n}”打分</b>：它的 q = [${q.join(', ')}] 和每个位置的 k 做点积，再除以 √2。${parts.join('；')}。`
  }
  if (ph.value === 1) {
    const fut = names.filter((_, j) => isFuture(i, j))
    return fut.length
      ? `<b>遮住未来</b>：“${n}”只能看自己和前面，把 ${fut.map(m => `“${m}”`).join('、')} 的分数改成 −∞，softmax 之后它们的权重就是 0。`
      : `<b>遮住未来</b>：“${n}”是最后一个位置，前面的字都能看，这一行没有要遮的。`
  }
  if (ph.value === 2) {
    const vis = names.map((m, j) => (isFuture(i, j) ? null : `${m} ${f2(d.weights[i][j])}`)).filter(Boolean)
    return `<b>softmax</b>：把这一行的分数取指数再归一化，变成加起来等于 1 的权重：${vis.join('，')}。分数高的位置分到的权重多，−∞ 变成 0。`
  }
  const terms = names.map((m, j) => (isFuture(i, j) ? null : `${f2(d.weights[i][j])}×v${m}`)).filter(Boolean)
  return `<b>按权重取 V</b>：输出 = ${terms.join(' + ')} = [${d.out[i].map(f2).join(', ')}]。“${n}”这个位置就这样从前文取回了信息。`
})

// 当前步骤在 Q/K/V 中高亮的行
const hl = (mat: 'Q' | 'K' | 'V', row: number) => {
  if (ph.value === 0) return mat === 'Q' ? row === r.value : mat === 'K'
  if (ph.value === 3) return mat === 'V' && !isFuture(r.value, row)
  return false
}
</script>

<template>
  <figure class="anim-card att">
    <div class="att-inputs">
      <div v-for="mat in (['Q', 'K', 'V'] as const)" :key="mat" class="att-mat small">
        <div class="att-title">{{ mat }}</div>
        <div class="att-grid" :style="{ gridTemplateColumns: `3rem repeat(2, 2.4rem)` }">
          <template v-for="(row, i) in d[mat]" :key="i">
            <span class="att-rl">{{ names[i] }}</span>
            <span v-for="(v, j) in row" :key="j" :class="['att-cell', { hl: hl(mat, i) }]">{{ v }}</span>
          </template>
        </div>
      </div>
    </div>

    <div class="att-steps">
      <div v-for="(title, k) in PHASES" :key="k" :class="['att-mat', { active: ph === k }]">
        <div class="att-title">{{ title }}</div>
        <div class="att-grid" :style="{ gridTemplateColumns: `3rem repeat(${k === 3 ? 2 : 3}, 2.9rem)` }">
          <span class="att-rl" />
          <span v-for="(c, j) in (k === 3 ? ['d0', 'd1'] : names)" :key="'h' + j" class="att-ch">{{ c }}</span>
          <template v-for="(_, i) in names" :key="i">
            <span :class="['att-rl', { cur: i === r }]">{{ names[i] }}</span>
            <template v-if="k < 3">
              <span v-for="(_, j) in names" :key="j"
                :class="['att-cell', { cur: i === r && ph === k, off: k > 0 && isFuture(i, j) && shown(i, k), blank: !shown(i, k) }]">
                <template v-if="shown(i, k)">{{
                  k === 0 ? f2(d.scores[i][j]) : k === 1 ? (isFuture(i, j) ? '−∞' : f2(d.scores[i][j])) : (isFuture(i, j) ? '0' : f2(d.weights[i][j]))
                }}</template>
              </span>
            </template>
            <template v-else>
              <span v-for="(v, j) in d.out[i]" :key="j" :class="['att-cell', { cur: i === r && ph === 3, blank: !shown(i, 3) }]">
                <template v-if="shown(i, 3)">{{ f2(v) }}</template>
              </span>
            </template>
          </template>
        </div>
      </div>
    </div>

    <p class="anim-caption" aria-live="polite" v-html="caption" />
    <PlayerControls :p="p" :label="`第 ${r + 1} 行 · ${PHASES[ph]}`" />
    <figcaption>数值来自本章 self-attention.py 里 hand、causal 两段代码的真实输出。一开始显示的是全部算完的结果；点“播放”从第一行重演，每一行依次经过打分、遮住未来、softmax、按权重取 V 四步。<a :href="withBase('/tinyllm/figures/attention-steps.svg')" target="_blank">打开静态图</a>（打印或不便播放时使用）。</figcaption>
  </figure>
</template>

<style scoped>
.att-inputs, .att-steps { display: flex; flex-wrap: wrap; gap: 0.9rem 1.2rem; }
.att-inputs { margin-bottom: 1rem; padding-bottom: 0.9rem; border-bottom: 1px dashed var(--vp-c-divider); }
.att-mat { padding: 0.45rem 0.55rem 0.55rem; border-radius: 10px; border: 1.5px solid transparent; }
.att-mat.active { border-color: var(--vp-c-brand-1); background: var(--vp-c-bg); }
.att-title { font-size: 0.85rem; font-weight: 600; color: var(--vp-c-text-2); margin-bottom: 0.35rem; }
.att-mat.active .att-title { color: var(--vp-c-brand-1); }
.att-grid { display: grid; gap: 3px; }
.att-ch { font-size: 0.75rem; color: var(--vp-c-text-3); text-align: center; }
.att-rl { font-size: 0.8rem; color: var(--vp-c-text-2); display: flex; align-items: center; }
.att-rl.cur { color: var(--vp-c-brand-1); font-weight: 700; }
.att-cell { font-size: 0.82rem; font-variant-numeric: tabular-nums; text-align: center; padding: 0.2rem 0; border-radius: 5px; background: var(--vp-c-bg); border: 1px solid var(--vp-c-divider); transition: background 0.3s, border-color 0.3s; min-height: 1.75rem; }
.small .att-cell { font-size: 0.8rem; }
.att-cell.blank { background: transparent; border-style: dashed; }
.att-cell.off { color: var(--vp-c-text-3); background: var(--vp-c-default-soft); }
.att-cell.cur { border-color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); font-weight: 700; }
.att-cell.hl { border-color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); }
@media (prefers-reduced-motion: reduce) { .att-cell { transition: none; } }
</style>
