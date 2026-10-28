<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 数据由 docs/public/tinyllm/code/transformer-block.py 的 lens 段在训练好的 4 层模型上真实读出，这里只负责播放。
import d from '../../../../scripts/data/tinyllm-block-depth.json'

type Stop = { where: string; top: [string, number][]; rms: number; update?: number; attn?: number[][] }
const prompts = Object.keys(d.lens)
const prompt = ref(prompts[0])
const cur = computed(() => (d.lens as any)[prompt.value] as { answer: string; stops: Stop[] })
const stops = computed(() => cur.value.stops)
const p = reactive(usePlayer(() => stops.value.length, { interval: 1400, start: 'last' }))
const stop = computed(() => stops.value[p.frame])
const ctx = computed(() => [...prompt.value])
const last = computed(() => ctx.value[ctx.value.length - 1])

const answerP = (s: Stop) => s.top.find(([c]) => c === cur.value.answer)?.[1]
const pct = (x: number) => (x >= 0.995 ? '>99%' : x >= 0.01 ? Math.round(x * 100) + '%' : '<1%')

const caption = computed(() => {
  const s = stop.value, a = cur.value.answer, ap = answerP(s)
  const read = ap === undefined ? `正确答案“${a}”还不在前 5 名` : `读出“${a}”的概率是 ${pct(ap)}`
  if (p.frame === 0)
    return `<b>嵌入</b>：刚查完词表，还没进任何 Block。输入和输出共用一张表，“${last.value}”的向量最像的就是“${last.value}”自己，所以这时读出来几乎全是“${s.top[0][0]}”。`
  const isAttn = !!s.attn
  const what = isAttn
    ? `最后一个字“${last.value}”从前面的字里取回信息（下方是 4 个头各自看向哪里），结果加回残差流`
    : '只加工当前这个位置，不看别的字，结果加回残差流'
  const end = p.frame === stops.value.length - 1 ? '这就是模型最终交给输出层的结果。' : ''
  return `<b>${s.where}</b>：${what}。${read}。${end}`
})
function choose(pr: string) { p.stop(); prompt.value = pr; p.frame = stops.value.length - 1 }
const heat = (w: number, row: number[]) => `color-mix(in srgb, var(--vp-c-brand-1) ${Math.round((w / Math.max(...row)) * 85)}%, transparent)`
</script>

<template>
  <figure class="anim-card rsl">
    <div class="rsl-prompts">
      <button v-for="pr in prompts" :key="pr" :class="{ on: pr === prompt }" @click="choose(pr)">{{ pr }}<b>?</b></button>
    </div>

    <div class="rsl-body">
      <ol class="rsl-route">
        <li v-for="(s, k) in stops" :key="k" :class="{ on: k === p.frame, past: k < p.frame }" @click="p.seek(k)">
          <span class="nm">{{ s.where }}</span>
          <span class="mini"><span :style="{ width: (k <= p.frame ? (answerP(s) ?? 0) * 100 : 0) + '%' }" /></span>
          <span class="pv">{{ k <= p.frame ? (answerP(s) === undefined ? '—' : pct(answerP(s)!)) : '' }}</span>
        </li>
      </ol>

      <div class="rsl-main">
        <div class="rsl-sub">如果在这里就把残差流交给输出层，模型会猜：</div>
        <div v-for="([c, pr], k) in stop.top" :key="k" :class="['rsl-row', { ans: c === cur.answer }]">
          <span class="ch">{{ c === '\n' ? '⏎' : c }}</span>
          <span class="tr"><span class="bar" :style="{ width: Math.max(pr * 100, 0.5) + '%' }" /></span>
          <span class="pv">{{ pct(pr) }}</span>
        </div>
        <div class="rsl-meta">残差流长度（RMS）{{ stop.rms.toFixed(2) }}<template v-if="stop.update !== undefined"> · 这一站加上去 {{ stop.update.toFixed(2) }}</template></div>

        <div v-if="stop.attn" class="rsl-attn">
          <div class="rsl-sub">“{{ last }}”在看谁（4 个头，颜色越深权重越大）：</div>
          <div class="hm" :style="{ gridTemplateColumns: `3rem repeat(${ctx.length}, 1fr)` }">
            <span />
            <span v-for="(c, j) in ctx" :key="'c' + j" class="hc">{{ c }}</span>
            <template v-for="(row, h) in stop.attn" :key="h">
              <span class="hl">头 {{ h + 1 }}</span>
              <span v-for="(w, j) in row" :key="j" class="cell" :style="{ background: heat(w, row) }" :title="w.toFixed(3)" />
            </template>
          </div>
        </div>
        <div v-else-if="p.frame > 0" class="rsl-note">前馈层不看别的字，这一站没有注意力权重。</div>
      </div>
    </div>

    <p class="anim-caption" aria-live="polite" v-html="caption" />
    <PlayerControls :p="p" :label="stop.where" />
    <figcaption>本章 transformer-block.py 里训练好的 4 层 Pre-Norm 模型的真实读数：在每一站之后，直接用最后的 RMSNorm 和输出层读出当前的残差流。一开始显示最后一站；点“播放”从嵌入开始，或点左边任意一站。</figcaption>
  </figure>
</template>

<style scoped>
.rsl-prompts { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.8rem; }
.rsl-prompts button { font-size: 0.85rem; padding: 0.2rem 0.7rem; border-radius: 999px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); color: var(--vp-c-text-2); letter-spacing: 0.04em; }
.rsl-prompts button b { color: var(--vp-c-brand-1); margin-left: 0.15em; }
.rsl-prompts button.on { border-color: var(--vp-c-brand-1); color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); font-weight: 600; }
.rsl-body { display: flex; flex-wrap: wrap; gap: 0.8rem 1.1rem; align-items: flex-start; }
.rsl-route { list-style: none; margin: 0; padding: 0; flex: 0 0 14rem; display: grid; gap: 0.2rem; align-content: start; }
.rsl-route li { display: grid; grid-template-columns: 6.6rem 1fr 2.6rem; align-items: center; gap: 0.4rem; font-size: 0.82rem; padding: 0.18rem 0.45rem; border-radius: 6px; cursor: pointer; color: var(--vp-c-text-3); margin: 0; }
.rsl-route li.past { color: var(--vp-c-text-2); }
.rsl-route li.on { background: var(--vp-c-brand-soft); color: var(--vp-c-brand-1); font-weight: 700; }
.rsl-route .mini { height: 0.45rem; border-radius: 3px; background: var(--vp-c-default-soft); overflow: hidden; }
.rsl-route .mini span { display: block; height: 100%; background: var(--vp-c-brand-1); transition: width 0.35s; }
.rsl-route .pv { text-align: right; font-variant-numeric: tabular-nums; }
.rsl-main { flex: 1; min-width: 16rem; padding: 0.55rem 0.7rem; border-radius: 10px; background: var(--vp-c-bg); }
.rsl-sub { font-size: 0.8rem; color: var(--vp-c-text-2); margin-bottom: 0.35rem; }
.rsl-row { display: grid; grid-template-columns: 1.6rem 1fr 3rem; align-items: center; gap: 0.5rem; font-size: 0.88rem; padding: 0.05rem 0.2rem; border-radius: 5px; }
.rsl-row .ch { font-size: 1.05rem; text-align: center; font-weight: 600; }
.rsl-row .tr { height: 0.8rem; border-radius: 4px; background: var(--vp-c-default-soft); overflow: hidden; }
.rsl-row .bar { display: block; height: 100%; background: var(--vp-c-text-3); transition: width 0.35s; }
.rsl-row .pv { text-align: right; color: var(--vp-c-text-2); font-variant-numeric: tabular-nums; }
.rsl-row.ans { background: var(--vp-c-brand-soft); }
.rsl-row.ans .bar { background: var(--vp-c-brand-1); }
.rsl-row.ans .ch, .rsl-row.ans .pv { color: var(--vp-c-brand-1); font-weight: 700; }
.rsl-meta { font-size: 0.78rem; color: var(--vp-c-text-3); margin: 0.4rem 0 0.2rem; }
.rsl-attn { margin-top: 0.6rem; }
.hm { display: grid; gap: 2px; }
.hc { font-size: 0.85rem; text-align: center; }
.hl { font-size: 0.72rem; color: var(--vp-c-text-3); display: flex; align-items: center; }
.cell { height: 1.05rem; border-radius: 3px; border: 1px solid var(--vp-c-divider); }
.rsl-note { font-size: 0.8rem; color: var(--vp-c-text-3); margin-top: 0.6rem; }
@media (prefers-reduced-motion: reduce) { .rsl-row .bar { transition: none; } }
</style>
