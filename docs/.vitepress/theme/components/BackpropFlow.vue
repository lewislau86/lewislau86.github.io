<script setup lang="ts">
import { computed, reactive } from 'vue'
import { withBase } from 'vitepress'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 数值由 docs/public/tinyllm/code/tensors-and-autograd.py 用 PyTorch 真实算出（retain_grad 取中间梯度），这里只负责播放。
import d from '../../../../scripts/data/tinyllm-autograd-chain.json'

const v = d.values, g = d.grads
const nodes = [
  { name: 'w', sub: '参数', val: d.w, grad: g.w, gname: '∂L/∂w' },
  { name: 'p = w·x', sub: `乘以 x = ${d.x}`, val: v.p, grad: g.p, gname: '∂L/∂p' },
  { name: 'd = p − t', sub: `减去 t = ${d.target}`, val: v.d, grad: g.d, gname: '∂L/∂d' },
  { name: 'L = d²', sub: '平方', val: v.L, grad: g.L, gname: '∂L/∂L' }
]
const local = [`× x = ×${d.x}`, '× 1', `× 2d = ×${2 * v.d}`]   // 第 i 条边的局部导数
const XS = [90, 270, 450, 630]

// 帧：0 只有 w；1–3 前向；4–7 反向；8 更新
const p = reactive(usePlayer(() => 9, { interval: 1300, start: 'last' }))
const fwd = (i: number) => p.frame >= i                      // 第 i 个节点的值已算出
const bwd = (i: number) => p.frame >= 4 + (3 - i)            // 第 i 个节点的梯度已算出
const fwdEdge = computed(() => (p.frame >= 1 && p.frame <= 3 ? p.frame - 1 : -1))   // 正在前向通过的边
const bwdEdge = computed(() => (p.frame >= 5 && p.frame <= 7 ? 7 - p.frame : -1))   // 正在反向通过的边
const n = (x: number) => (Number.isInteger(x) ? String(x) : x.toFixed(2))

const caption = computed(() => {
  const f = p.frame
  if (f === 0) return `<b>起点</b>：参数 w = ${n(d.w)}，输入 x = ${n(d.x)}，目标 t = ${n(d.target)}。点“播放”，先从左往右算一遍。`
  if (f === 1) return `<b>前向 ①</b>：p = w · x = ${n(d.w)} × ${n(d.x)} = ${n(v.p)}。PyTorch 一边算，一边把“这里做了乘法”记进计算图。`
  if (f === 2) return `<b>前向 ②</b>：d = p − t = ${n(v.p)} − ${n(d.target)} = ${n(v.d)}。`
  if (f === 3) return `<b>前向 ③</b>：L = d² = ${n(v.L)}。前向结束，得到损失。接下来调用 loss.backward()，沿原路往回走。`
  if (f === 4) return `<b>反向 ①</b>：从终点出发，∂L/∂L = ${n(g.L)}。`
  if (f === 5) return `<b>反向 ②</b>：经过“平方”，乘它的局部导数 2d = ${n(2 * v.d)}：∂L/∂d = ${n(g.L)} × ${n(2 * v.d)} = ${n(g.d)}。`
  if (f === 6) return `<b>反向 ③</b>：经过“减去 t”，局部导数是 1：∂L/∂p = ${n(g.d)} × 1 = ${n(g.p)}。`
  if (f === 7) return `<b>反向 ④</b>：经过“乘以 x”，局部导数是 x = ${n(d.x)}：∂L/∂w = ${n(g.p)} × ${n(d.x)} = ${n(g.w)}。这就是 w.grad。`
  return `<b>更新</b>：梯度为正，说明 w 变大损失会变大，所以往反方向走一小步：w ← ${n(d.w)} − ${d.lr} × ${n(g.w)} = ${n(d.new_w)}，损失从 ${n(v.L)} 降到 ${d.new_loss.toFixed(2)}。`
})
</script>

<template>
  <figure class="anim-card bp">
    <svg viewBox="0 0 720 250" class="bp-svg" role="img" aria-label="单参数计算图：前向从左往右算出 p、d、L，反向从 L 往左乘局部导数得到 w 的梯度">
      <defs>
        <marker id="bp-f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" class="f-fill" /></marker>
        <marker id="bp-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" class="b-fill" /></marker>
      </defs>
      <g v-for="i in 3" :key="'e' + i">
        <line :x1="XS[i - 1] + 62" y1="108" :x2="XS[i] - 64" y2="108" :class="['edge-f', { lit: fwd(i), now: fwdEdge === i - 1 }]" marker-end="url(#bp-f)" />
        <line :x1="XS[i] - 62" y1="142" :x2="XS[i - 1] + 64" y2="142" :class="['edge-b', { lit: bwd(i - 1), now: bwdEdge === i - 1 }]" marker-end="url(#bp-b)" />
        <text :x="(XS[i - 1] + XS[i]) / 2" y="164" :class="['local', { lit: bwd(i - 1) }]">{{ local[i - 1] }}</text>
        <circle v-if="fwdEdge === i - 1" :key="'pf' + p.frame" :cx="XS[i - 1] + 62" cy="108" r="6" class="pulse f" :style="{ '--dx': (XS[i] - XS[i - 1] - 126) + 'px' }" />
        <circle v-if="bwdEdge === i - 1" :key="'pb' + p.frame" :cx="XS[i] - 62" cy="142" r="6" class="pulse b" :style="{ '--dx': -(XS[i] - XS[i - 1] - 126) + 'px' }" />
      </g>
      <g v-for="(nd, i) in nodes" :key="nd.name">
        <rect :x="XS[i] - 60" y="90" width="120" height="70" rx="10" :class="['node', { param: i === 0 }]" />
        <text :x="XS[i]" y="121" class="nname">{{ nd.name }}</text>
        <text :x="XS[i]" y="145" class="nsub">{{ nd.sub }}</text>
        <text :x="XS[i]" y="70" :class="['val', { show: fwd(i) }]">值 {{ i === 0 && p.frame === 8 ? `${n(d.w)} → ${n(d.new_w)}` : n(nd.val) }}</text>
        <text :x="XS[i]" y="200" :class="['grad', { show: bwd(i) }]">{{ nd.gname }} = {{ n(nd.grad) }}</text>
      </g>
      <text x="20" y="30" class="legend f">前向：从左往右算数值</text>
      <text x="700" y="30" class="legend b" text-anchor="end">反向：从右往左，每过一个运算乘它的局部导数</text>
      <text v-if="p.frame === 8" x="360" y="236" class="upd">L：{{ n(v.L) }} → {{ d.new_loss.toFixed(2) }}</text>
    </svg>
    <p class="anim-caption" aria-live="polite" v-html="caption" />
    <PlayerControls :p="p" :label="p.frame === 0 ? '起点' : p.frame <= 3 ? `前向 ${p.frame}/3` : p.frame <= 7 ? `反向 ${p.frame - 3}/4` : '更新'" />
    <figcaption>数值来自本章 tensors-and-autograd.py 的真实运行（retain_grad 取出中间结果的梯度）。一开始显示全部算完的状态；点“播放”从头重演：先前向，再反向，最后更新一次参数。<a :href="withBase('/tinyllm/figures/compute-graph.svg')" target="_blank">打开静态图</a>（打印或不便播放时使用）。</figcaption>
  </figure>
</template>

<style scoped>
.bp-svg { width: 100%; height: auto; display: block; background: var(--vp-c-bg); border-radius: 10px; }
.node { fill: var(--vp-c-bg-soft); stroke: var(--vp-c-divider); stroke-width: 1.5; }
.node.param { stroke: #2563eb; stroke-width: 2; }
.nname { font-size: 17px; font-weight: 700; text-anchor: middle; fill: var(--vp-c-text-1); }
.nsub { font-size: 12px; text-anchor: middle; fill: var(--vp-c-text-2); }
.val, .grad { font-size: 15px; font-weight: 700; text-anchor: middle; opacity: 0; transition: opacity 0.35s; }
.val { fill: #0d9488; } .grad { fill: #d97706; }
.val.show, .grad.show { opacity: 1; }
.edge-f, .edge-b { stroke-width: 2.5; opacity: 0.25; transition: opacity 0.3s; }
.edge-f { stroke: #0d9488; } .edge-b { stroke: #d97706; }
.edge-f.lit, .edge-b.lit { opacity: 1; }
.edge-f.now, .edge-b.now { stroke-width: 4; }
.f-fill { fill: #0d9488; } .b-fill { fill: #d97706; }
.local { font-size: 12px; text-anchor: middle; fill: #d97706; opacity: 0.3; }
.local.lit { opacity: 1; font-weight: 600; }
.legend { font-size: 12.5px; } .legend.f { fill: #0d9488; } .legend.b { fill: #d97706; }
.upd { font-size: 14px; font-weight: 700; text-anchor: middle; fill: var(--vp-c-brand-1); }
.pulse { animation: bp-move 0.8s ease-in-out forwards; }
.pulse.f { fill: #0d9488; } .pulse.b { fill: #d97706; }
@keyframes bp-move { from { transform: translateX(0); } to { transform: translateX(var(--dx)); } }
@media (prefers-reduced-motion: reduce) { .pulse { display: none; } .val, .grad, .edge-f, .edge-b { transition: none; } }
</style>
