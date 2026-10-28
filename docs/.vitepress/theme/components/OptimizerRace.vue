<script setup lang="ts">
import { computed, reactive } from 'vue'
import { withBase } from 'vitepress'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 轨迹由 scripts/tinyllm-figure-data.py 用 PyTorch 的真实优化器在 f = 0.5(a² + 25b²) 上跑出来，这里只负责播放。
import d from '../../../../scripts/data/tinyllm-optimizer-paths.json'

const [ca, cb] = d.curvature as number[]
const runs = Object.entries(d.paths as Record<string, number[][]>)
const COLORS = ['#dc2626', '#d97706', '#7c3aed', '#0d9488']
const steps = runs[0][1].length
const p = reactive(usePlayer(() => steps, { interval: 260, start: 'last' }))

// 坐标：a ∈ [-5, 1.5]，b ∈ [-2, 2]，每单位 100 像素
const X = (a: number) => (a + 5) * 100
const Y = (b: number) => (2 - b) * 100
const LEVELS = [0.5, 2, 5, 10, 20, 35]
const f = (a: number, b: number) => 0.5 * (ca * a * a + cb * b * b)
const poly = (pts: number[][]) => pts.slice(0, p.frame + 1).map(([a, b]) => `${X(a)},${Y(b)}`).join(' ')
const cur = computed(() => runs.map(([, pts]) => pts[p.frame]))
</script>

<template>
  <figure class="anim-card opt">
    <svg viewBox="0 0 650 400" class="opt-svg" role="img" aria-label="四种优化器在狭长山谷里从同一点出发，逐步走向最低点">
      <defs><clipPath id="opt-clip"><rect width="650" height="400" /></clipPath></defs>
      <g clip-path="url(#opt-clip)">
        <ellipse v-for="L in LEVELS" :key="L" :cx="X(0)" :cy="Y(0)" :rx="Math.sqrt((2 * L) / ca) * 100" :ry="Math.sqrt((2 * L) / cb) * 100" class="lvl" />
        <text :x="X(0) + 10" :y="Y(0) + 34" class="lbl">最低点</text>
        <path :d="`M${X(0) - 7} ${Y(0)}h14M${X(0)} ${Y(0) - 7}v14`" class="star" />
        <text :x="X(runs[0][1][0][0]) - 4" :y="Y(runs[0][1][0][1]) - 12" class="lbl">起点</text>
        <g v-for="([name, pts], k) in runs" :key="name">
          <polyline :points="poly(pts)" :stroke="COLORS[k]" class="path" />
          <circle v-for="(q, s) in pts.slice(0, p.frame + 1)" :key="s" :cx="X(q[0])" :cy="Y(q[1])" r="2.4" :fill="COLORS[k]" />
          <circle :cx="X(cur[k][0])" :cy="Y(cur[k][1])" r="7" :fill="COLORS[k]" class="head" />
        </g>
      </g>
    </svg>
    <div class="opt-legend">
      <div v-for="([name], k) in runs" :key="name" class="opt-item">
        <span class="sw" :style="{ background: COLORS[k] }" />
        <span class="nm">{{ name }}</span>
        <span class="lv">损失 {{ f(cur[k][0], cur[k][1]).toFixed(3) }}</span>
      </div>
    </div>
    <p class="anim-caption">
      损失 f = 0.5(a² + 25b²)：b 方向比 a 方向陡 25 倍，像一条狭长的山谷，椭圆是等高线。四种优化器从同一点出发，各走 {{ steps - 1 }} 步。
      SGD 在陡的 b 方向来回折返，沿缓的 a 方向挪得很慢；Momentum 记住过去的方向，越走越快，冲过了谷底；RMSProp 给每个方向单独定步长，几乎直达最低点；Adam 两者兼有，这次也冲过了头。
    </p>
    <PlayerControls :p="p" :label="`第 ${p.frame} / ${steps - 1} 步`" />
    <figcaption>轨迹是 PyTorch 自带优化器的真实运行记录（scripts/tinyllm-figure-data.py）。一开始显示全部 {{ steps - 1 }} 步的结果；点“播放”从起点重演，四种优化器同时走。<a :href="withBase('/tinyllm/figures/optimizer-paths.svg')" target="_blank">打开静态图</a>（打印或不便播放时使用）。</figcaption>
  </figure>
</template>

<style scoped>
.opt-svg { width: 100%; height: auto; background: var(--vp-c-bg); border-radius: 10px; display: block; }
.lvl { fill: none; stroke: var(--vp-c-divider); stroke-width: 1.2; }
.lbl { font-size: 13px; fill: var(--vp-c-text-2); }
.star { stroke: var(--vp-c-text-1); stroke-width: 2.5; }
.path { fill: none; stroke-width: 1.8; opacity: 0.85; }
.head { stroke: var(--vp-c-bg); stroke-width: 2; }
.opt-legend { display: flex; flex-wrap: wrap; gap: 0.3rem 1.2rem; margin-top: 0.7rem; font-size: 0.85rem; }
.opt-item { display: flex; align-items: center; gap: 0.4rem; }
.sw { width: 0.8rem; height: 0.8rem; border-radius: 50%; display: inline-block; }
.lv { color: var(--vp-c-text-2); font-variant-numeric: tabular-nums; }
</style>
