<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 数据由 docs/public/tinyllm/code/quickstart.py 真实运行导出（quickstart_attention.json），这里只负责播放。
// before：步骤 3 里随机投影的注意力（训练前）；after：训练好的模型第 1 层、第 1 个注意力头。
import d from '../../../../scripts/data/tinyllm-quickstart-attention.json'

type Set = { scores: number[][]; weights: number[][]; v: number[][]; out: number[][] }
const SETS: Record<'before' | 'after', { label: string; root: string; data: Set }> = {
  before: { label: '训练前（步骤 3 的随机投影）', root: '√96', data: d.before },
  after: { label: '训练后（模型第 1 层第 1 个头）', root: '√24', data: d.after },
}
const which = ref<'before' | 'after'>('before')
const s = computed(() => SETS[which.value].data)
const names: string[] = d.names
const N = names.length
const PHASES = ['① 打分', '② 遮住后面', '③ softmax 变权重', '④ 按权重把 v 加起来']
const p = reactive(usePlayer(() => N * 4, { interval: 1400, start: 'last' }))
const r = computed(() => Math.floor(p.frame / 4))
const ph = computed(() => p.frame % 4)

const f2 = (x: number) => (Math.abs(x) < 0.005 ? '0.00' : x.toFixed(2))
const future = (i: number, j: number) => j > i
const done = (row: number, phase: number) => row < r.value || (row === r.value && ph.value >= phase)
const vmax = computed(() => Math.max(...s.value.v.flat().map(Math.abs), ...s.value.out.flat().map(Math.abs)))
const shade = (x: number) => {
  const a = Math.min(1, Math.abs(x) / vmax.value) * 0.75
  return { background: x >= 0 ? `rgba(37, 99, 235, ${a})` : `rgba(180, 83, 9, ${a})` }
}
const wshade = (w: number) => ({ background: `rgba(15, 118, 110, ${w * 0.7})` })

const caption = computed(() => {
  const i = r.value, n = names[i], S = s.value, root = SETS[which.value].root
  if (ph.value === 0)
    return `<b>第 ${i + 1} 行“${n}”打分</b>：拿“${n}”的 q 和 5 个字的 k 各做一次点积，再除以 ${root}：` +
      names.map((m, j) => `${m} ${f2(S.scores[i][j])}`).join('，') + '。分数越高，表示“越想看这个字”。'
  if (ph.value === 1) {
    const fut = names.filter((_, j) => future(i, j))
    return fut.length
      ? `<b>遮住后面</b>：“${n}”只能看自己和前面的字，${fut.map(m => `“${m}”`).join('、')}的分数改成 −∞（还没写出来的字不许偷看）。`
      : `<b>遮住后面</b>：“${n}”是最后一个字，前面的字都能看，这一行不用遮。`
  }
  if (ph.value === 2)
    return `<b>softmax</b>：把这一行变成加起来等于 1 的权重：` +
      names.map((m, j) => (future(i, j) ? null : `${m} ${f2(S.weights[i][j])}`)).filter(Boolean).join('，') + '。−∞ 变成 0。'
  const terms = names.map((m, j) => (future(i, j) ? null : `${f2(S.weights[i][j])}×v(${m})`)).filter(Boolean)
  return `<b>按权重把 v 加起来</b>：“${n}”位置的输出 = ${terms.join(' + ')}。下面 v 的每一行按权重变深变浅，输出的每个数都是它们的加权和。`
})
</script>

<template>
  <figure class="anim-card qa">
    <div class="qa-switch" role="group" aria-label="选择数据">
      <button v-for="(v, k) in SETS" :key="k" :class="{ on: which === k }" @click="which = k as any">{{ v.label }}</button>
    </div>

    <div class="qa-row">
      <div v-for="(title, k) in PHASES.slice(0, 3)" :key="k" :class="['qa-box', { active: ph === k }]">
        <div class="qa-title">{{ title }}</div>
        <div class="qa-grid" :style="{ gridTemplateColumns: `1.6rem repeat(${N}, 2.6rem)` }">
          <span />
          <span v-for="m in names" :key="'h' + m" class="qa-ch">{{ m }}</span>
          <template v-for="(_, i) in names" :key="i">
            <span :class="['qa-rl', { cur: i === r }]">{{ names[i] }}</span>
            <span v-for="(_, j) in names" :key="j"
              :class="['qa-cell', { blank: !done(i, k), off: k > 0 && future(i, j) && done(i, k), cur: i === r && ph === k }]"
              :style="k === 2 && done(i, 2) && !future(i, j) ? wshade(s.weights[i][j]) : undefined">
              <template v-if="done(i, k)">{{
                k === 0 ? f2(s.scores[i][j]) : future(i, j) ? (k === 1 ? '−∞' : '0') : k === 1 ? f2(s.scores[i][j]) : f2(s.weights[i][j])
              }}</template>
            </span>
          </template>
        </div>
      </div>
    </div>

    <div class="qa-row">
      <div :class="['qa-box', { active: ph === 3 }]">
        <div class="qa-title">每个字的 v（前 6 个数）</div>
        <div class="qa-grid" :style="{ gridTemplateColumns: `1.6rem 2.6rem repeat(6, 2.6rem)` }">
          <template v-for="(row, j) in s.v" :key="j">
            <span class="qa-rl">{{ names[j] }}</span>
            <span class="qa-w">{{ ph === 3 ? (future(r, j) ? '×0' : '×' + f2(s.weights[r][j])) : '' }}</span>
            <span v-for="(x, c) in row" :key="c" class="qa-cell vec"
              :style="{ ...shade(x), opacity: ph === 3 ? (future(r, j) ? 0.15 : 0.25 + 0.75 * s.weights[r][j]) : 1 }">{{ f2(x) }}</span>
          </template>
        </div>
      </div>
      <div :class="['qa-box', { active: ph === 3 }]">
        <div class="qa-title">④ 输出（前 6 个数）</div>
        <div class="qa-grid" :style="{ gridTemplateColumns: `1.6rem repeat(6, 2.6rem)` }">
          <template v-for="(row, i) in s.out" :key="i">
            <span :class="['qa-rl', { cur: i === r }]">{{ names[i] }}</span>
            <span v-for="(x, c) in row" :key="c" :class="['qa-cell vec', { blank: !done(i, 3), cur: i === r && ph === 3 }]"
              :style="done(i, 3) ? shade(x) : undefined"><template v-if="done(i, 3)">{{ f2(x) }}</template></span>
          </template>
        </div>
      </div>
    </div>

    <p class="anim-caption" aria-live="polite" v-html="caption" />
    <PlayerControls :p="p" :label="`第 ${r + 1} 行 · ${PHASES[ph]}`" />
    <figcaption>数值来自 quickstart.py 的真实运行：“训练前”是步骤 3 用随机投影算出的注意力，“训练后”是步骤 7 训练完以后，模型第 1 层第 1 个注意力头在同一句上的结果（3 层 × 4 个头里的一个）。一开始显示全部算完的结果；点“播放”从第一行重演，每一行依次经过打分、遮住后面、softmax、按权重加 v 四步。蓝色是正数、橙色是负数，颜色越深绝对值越大。</figcaption>
  </figure>
</template>

<style scoped>
.qa-switch { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.8rem; }
.qa-switch button { padding: 0.2rem 0.7rem; border-radius: 6px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); font-size: 0.85rem; }
.qa-switch button.on { border-color: var(--vp-c-brand-1); color: var(--vp-c-brand-1); font-weight: 600; background: var(--vp-c-brand-soft); }
.qa-row { display: flex; flex-wrap: wrap; gap: 0.8rem 1rem; margin-bottom: 0.6rem; }
.qa-box { padding: 0.45rem 0.55rem 0.55rem; border-radius: 10px; border: 1.5px solid transparent; }
.qa-box.active { border-color: var(--vp-c-brand-1); background: var(--vp-c-bg); }
.qa-title { font-size: 0.85rem; font-weight: 600; color: var(--vp-c-text-2); margin-bottom: 0.35rem; }
.qa-box.active .qa-title { color: var(--vp-c-brand-1); }
.qa-grid { display: grid; gap: 3px; }
.qa-ch { font-size: 0.75rem; color: var(--vp-c-text-3); text-align: center; }
.qa-rl { font-size: 0.85rem; color: var(--vp-c-text-2); display: flex; align-items: center; }
.qa-rl.cur { color: var(--vp-c-brand-1); font-weight: 700; }
.qa-w { font-size: 0.75rem; color: var(--vp-c-text-2); display: flex; align-items: center; justify-content: flex-end; font-variant-numeric: tabular-nums; }
.qa-cell { font-size: 0.78rem; font-variant-numeric: tabular-nums; text-align: center; padding: 0.2rem 0; border-radius: 5px; background: var(--vp-c-bg); border: 1px solid var(--vp-c-divider); min-height: 1.7rem; transition: background 0.3s, opacity 0.3s, border-color 0.3s; }
.qa-cell.vec { color: var(--vp-c-text-1); }
.qa-cell.blank { background: transparent !important; border-style: dashed; }
.qa-cell.off { color: var(--vp-c-text-3); background: var(--vp-c-default-soft); }
.qa-cell.cur { border-color: var(--vp-c-brand-1); font-weight: 700; }
@media (prefers-reduced-motion: reduce) { .qa-cell { transition: none; } }
</style>
