<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
// q、k 就是 position-encoding.py 里 rope-relative 那段代码用的 q_vec、k_vec（8 维），
// 旋转公式与本章的 rope() 函数相同：第 i 对维度在位置 m 上转 m·θ_i，θ_i = base^(-2i/d)。
import d from '../../../../scripts/data/tinyllm-rope-demo.json'

const D = d.q.length
const thetas = Array.from({ length: D / 2 }, (_, i) => Math.pow(d.base, (-2 * i) / D))
const MAX = 40

const m = ref(3)
const n = ref(1)
const pair = ref(1)

function rotate(v: number[], i: number, pos: number): [number, number] {
  const a = pos * thetas[i], x1 = v[2 * i], x2 = v[2 * i + 1]
  return [x1 * Math.cos(a) - x2 * Math.sin(a), x1 * Math.sin(a) + x2 * Math.cos(a)]
}
const dot = (a: [number, number], b: [number, number]) => a[0] * b[0] + a[1] * b[1]
const contrib = (i: number) => dot(rotate(d.q, i, m.value), rotate(d.k, i, n.value))
const total = computed(() => thetas.reduce((s, _, i) => s + contrib(i), 0))

// 画图：当前这一对维度
const R = 92, C = 120
const scale = computed(() => R / Math.max(Math.hypot(d.q[2 * pair.value], d.q[2 * pair.value + 1]), Math.hypot(d.k[2 * pair.value], d.k[2 * pair.value + 1])))
const qv = computed(() => rotate(d.q, pair.value, m.value))
const kv = computed(() => rotate(d.k, pair.value, n.value))
const pt = (v: [number, number]) => [C + v[0] * scale.value, C - v[1] * scale.value]
// 标签放在箭头末端旁边，但不超出画布（标签约 72 像素宽）
const lx = (v: [number, number]) => (v[0] >= 0 ? Math.min(pt(v)[0] + 6, 240 - 74) : Math.max(pt(v)[0] - 6, 74))
const deg = (v: [number, number]) => (Math.atan2(v[1], v[0]) * 180) / Math.PI
const between = computed(() => {
  let a = deg(qv.value) - deg(kv.value)
  a = ((a + 540) % 360) - 180
  return a
})
const arc = computed(() => {
  const a0 = Math.atan2(kv.value[1], kv.value[0]), a1 = a0 + (between.value * Math.PI) / 180
  const r = 30, large = Math.abs(between.value) > 180 ? 1 : 0, sweep = between.value > 0 ? 0 : 1
  return `M${C + r * Math.cos(a0)} ${C - r * Math.sin(a0)} A${r} ${r} 0 ${large} ${sweep} ${C + r * Math.cos(a1)} ${C - r * Math.sin(a1)}`
})

// “保持相隔不变，一起往后移”
const moving = ref(false)
let timer: ReturnType<typeof setInterval> | undefined
function stopMove() { moving.value = false; if (timer) clearInterval(timer); timer = undefined }
function moveTogether() {
  if (moving.value) return stopMove()
  if (m.value >= MAX || n.value >= MAX) { const gap = m.value - n.value; n.value = Math.max(0, -gap); m.value = n.value + gap }
  moving.value = true
  timer = setInterval(() => {
    if (m.value >= MAX || n.value >= MAX) return stopMove()
    m.value++; n.value++
  }, 500)
}
function reset() { stopMove(); m.value = 3; n.value = 1 }
onBeforeUnmount(stopMove)
const f4 = (x: number) => x.toFixed(4)
const thetaLabel = (t: number) => (t >= 0.1 ? t.toFixed(1) : t >= 0.01 ? t.toFixed(2) : t.toFixed(3))
</script>

<template>
  <figure class="anim-card rope">
    <div class="rope-body">
      <svg viewBox="0 0 240 240" class="rope-svg" role="img" :aria-label="`第 ${pair + 1} 对维度：q 转了 ${m}θ，k 转了 ${n}θ，夹角 ${Math.abs(between).toFixed(0)} 度`">
        <defs>
          <marker id="rope-q" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" class="q-fill" /></marker>
          <marker id="rope-k" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" class="k-fill" /></marker>
        </defs>
        <circle :cx="C" :cy="C" :r="R" class="ring" />
        <line :x1="C - R - 8" :y1="C" :x2="C + R + 8" :y2="C" class="axis" />
        <line :x1="C" :y1="C - R - 8" :x2="C" :y2="C + R + 8" class="axis" />
        <path :d="arc" class="arc" />
        <line :x1="C" :y1="C" :x2="pt(kv)[0]" :y2="pt(kv)[1]" class="k-line" marker-end="url(#rope-k)" />
        <line :x1="C" :y1="C" :x2="pt(qv)[0]" :y2="pt(qv)[1]" class="q-line" marker-end="url(#rope-q)" />
        <text :x="lx(qv)" :y="pt(qv)[1] - 6" :text-anchor="qv[0] >= 0 ? 'start' : 'end'" class="q-text">q（位置 {{ m }}）</text>
        <text :x="lx(kv)" :y="pt(kv)[1] + 14" :text-anchor="kv[0] >= 0 ? 'start' : 'end'" class="k-text">k（位置 {{ n }}）</text>
      </svg>

      <div class="rope-panel">
        <label class="rope-slider q">
          <span>q 的位置 m = <b>{{ m }}</b></span>
          <input type="range" min="0" :max="MAX" v-model.number="m" @input="stopMove" />
        </label>
        <label class="rope-slider k">
          <span>k 的位置 n = <b>{{ n }}</b></span>
          <input type="range" min="0" :max="MAX" v-model.number="n" @input="stopMove" />
        </label>
        <div class="rope-read">
          <div>相隔 m − n = <b>{{ m - n }}</b></div>
          <div>图中这一对：夹角 {{ Math.abs(between).toFixed(1) }}°，贡献 {{ f4(contrib(pair)) }}</div>
          <div class="score">4 对加起来（8 维 q·k）= <b>{{ f4(total) }}</b></div>
        </div>
        <div class="rope-btns">
          <button class="go" @click="moveTogether">{{ moving ? '停下' : '保持相隔，一起往后移' }}</button>
          <button @click="reset">回到 m=3, n=1</button>
        </div>
      </div>
    </div>

    <div class="rope-pairs">
      <span>看哪一对维度：</span>
      <button v-for="(t, i) in thetas" :key="i" :class="{ on: pair === i }" @click="pair = i">第 {{ i + 1 }} 对 · 每个位置转 {{ thetaLabel(t) }} 弧度</button>
    </div>
    <p class="anim-caption">
      拖动两个滑块：q、k 各自按自己的位置旋转。点“保持相隔，一起往后移”，两根箭头一起转，夹角不变，右边的分数也一直不变。只改变相隔的距离，分数才会变。
    </p>
    <figcaption>q、k 是本章 position-encoding.py 里 rope-relative 那段代码的 8 维 q_vec、k_vec，旋转方式与 rope() 函数相同；m=3、n=1 时分数为 {{ f4(d.check['3,1']) }}，与代码输出一致。8 维被分成 4 对，每对转速不同，图中画的是其中一对。</figcaption>
  </figure>
</template>

<style scoped>
.rope-body { display: flex; flex-wrap: wrap; gap: 1rem 1.4rem; align-items: center; }
.rope-svg { width: 240px; height: 240px; flex: none; background: var(--vp-c-bg); border-radius: 10px; }
.ring { fill: none; stroke: var(--vp-c-divider); stroke-dasharray: 4 4; }
.axis { stroke: var(--vp-c-divider); }
.arc { fill: none; stroke: var(--vp-c-text-3); stroke-width: 2; }
.q-line { stroke: #2563eb; stroke-width: 3; }
.k-line { stroke: #d97706; stroke-width: 3; }
.q-fill { fill: #2563eb; }
.k-fill { fill: #d97706; }
.q-text { fill: #2563eb; font-size: 12px; font-weight: 600; }
.k-text { fill: #d97706; font-size: 12px; font-weight: 600; }
.dark .q-line { stroke: #60a5fa; } .dark .q-fill, .dark .q-text { fill: #60a5fa; }
.rope-panel { flex: 1; min-width: 15rem; display: grid; gap: 0.6rem; }
.rope-slider { display: grid; gap: 0.15rem; font-size: 0.9rem; }
.rope-slider.q b { color: #2563eb; } .rope-slider.k b { color: #b45309; }
.rope-slider.q input { accent-color: #1d4ed8; } .rope-slider.k input { accent-color: #b45309; }
.rope-read { font-size: 0.9rem; line-height: 1.75; padding: 0.45rem 0.7rem; border-radius: 8px; background: var(--vp-c-bg); }
.rope-read .score b { color: var(--vp-c-brand-1); font-size: 1.05rem; font-variant-numeric: tabular-nums; }
.rope-btns { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.rope-btns button, .rope-pairs button { padding: 0.15rem 0.65rem; border-radius: 6px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); font-size: 0.85rem; }
.rope-btns .go { color: var(--vp-c-brand-1); font-weight: 600; border-color: var(--vp-c-brand-1); }
.rope-pairs { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-top: 0.8rem; font-size: 0.85rem; color: var(--vp-c-text-2); }
.rope-pairs button.on { border-color: var(--vp-c-brand-1); color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); font-weight: 600; }
</style>
