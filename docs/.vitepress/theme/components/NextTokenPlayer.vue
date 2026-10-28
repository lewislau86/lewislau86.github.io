<script setup lang="ts">
import { ref, computed, watch, reactive } from 'vue'
import { usePlayer } from './usePlayer'
import PlayerControls from './PlayerControls.vue'
// 数据由 docs/public/tinyllm/code/first-run.py 在真实训练过程中记录，
// scripts/build-tinyllm-code.py 复制到 scripts/data。这里不手写任何概率。
import trace from '../../../../scripts/data/tinyllm-first-run-generation.json'

type Step = { top: [string, number][]; pick: string; p: number; rank: number }
type Trace = { prompt: string; steps: Step[] }

const props = withDefaults(defineProps<{ stage?: 'before' | 'after' }>(), { stage: 'after' })
const stage = ref<'before' | 'after'>(props.stage)
const data = computed<Trace>(() => (trace as any)[stage.value])
const vocab = (trace as any).vocab_size as number

// 每个字分两帧：先算出概率（还没抽），再按概率抽一个接上
const p = reactive(usePlayer(() => data.value.steps.length * 2, { interval: 750 }))
const i = computed(() => Math.floor(p.frame / 2))
const revealed = computed(() => p.frame % 2 === 1)
const step = computed(() => data.value.steps[i.value])

const shown = (c: string) => (c === '\n' ? '⏎' : c)
const done = computed(() => data.value.steps.slice(0, i.value).map(s => shown(s.pick)).join(''))
const rest = computed(() => Math.max(0, 1 - step.value.top.reduce((a, [, p]) => a + p, 0)))
const pickInTop = computed(() => step.value.rank <= step.value.top.length)

function pct(p: number) {
  if (p >= 0.01) return (p * 100).toFixed(1) + '%'
  if (p >= 0.0001) return (p * 100).toFixed(2) + '%'
  return '<0.01%'
}

function switchStage(s: 'before' | 'after') { p.stop(); stage.value = s; p.frame = 0 }
watch(() => props.stage, s => switchStage(s))
</script>

<template>
  <figure class="anim-card ntp">
    <div class="ntp-tabs" role="tablist">
      <button role="tab" :aria-selected="stage === 'before'" :class="{ on: stage === 'before' }" @click="switchStage('before')">训练前（随机参数）</button>
      <button role="tab" :aria-selected="stage === 'after'" :class="{ on: stage === 'after' }" @click="switchStage('after')">训练 600 步之后</button>
    </div>

    <div class="ntp-text" aria-label="已经写出的文字">
      <span class="ntp-prompt">{{ data.prompt }}</span><span class="ntp-done">{{ done }}</span><span
        :class="['ntp-slot', { filled: revealed }]">{{ revealed ? shown(step.pick) : '?' }}</span>
    </div>

    <p class="ntp-caption" aria-live="polite">
      <template v-if="!revealed">
        第 {{ i + 1 }} 步：模型读入前面 {{ data.prompt.length + i }} 个字，给词表里 {{ vocab }} 个字各算出一个概率。下面是最高的 5 个：
      </template>
      <template v-else>
        按概率抽签，抽中“{{ shown(step.pick) }}”：概率 {{ pct(step.p) }}，在 {{ vocab }} 个字里排第 {{ step.rank }}。把它接在后面，进入下一步。
      </template>
    </p>

    <div class="ntp-bars">
      <div v-for="([c, p], k) in step.top" :key="k" :class="['ntp-row', { pick: revealed && pickInTop && k === step.rank - 1 }]">
        <span class="ntp-char">{{ shown(c) }}</span>
        <span class="ntp-track"><span class="ntp-bar" :style="{ width: Math.max(p * 100, 0.4) + '%' }" /></span>
        <span class="ntp-p">{{ pct(p) }}</span>
      </div>
      <div v-if="revealed && !pickInTop" class="ntp-row pick">
        <span class="ntp-char">{{ shown(step.pick) }}</span>
        <span class="ntp-track"><span class="ntp-bar" :style="{ width: Math.max(step.p * 100, 0.4) + '%' }" /></span>
        <span class="ntp-p">{{ pct(step.p) }} · 第 {{ step.rank }} 名</span>
      </div>
      <div class="ntp-row ntp-rest">
        <span class="ntp-char">…</span>
        <span class="ntp-track"><span class="ntp-bar" :style="{ width: rest * 100 + '%' }" /></span>
        <span class="ntp-p">其余 {{ vocab - 5 }} 个字合计 {{ pct(rest) }}</span>
      </div>
    </div>

    <PlayerControls :p="p" :label="`${i + 1} / ${data.steps.length}`" />
    <figcaption>
      真实记录：第 1 章的模型以“{{ data.prompt }}”开头、温度 0.8、随机种子 1 时每一步的概率。播放、单步或拖动滑块查看任意一步。
    </figcaption>
  </figure>
</template>

<style scoped>
.ntp-tabs { display: flex; gap: 0.5rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
.ntp-tabs button { font-size: 0.85rem; padding: 0.2rem 0.75rem; border-radius: 999px; border: 1px solid var(--vp-c-divider); color: var(--vp-c-text-2); background: var(--vp-c-bg); }
.ntp-tabs button.on { border-color: var(--vp-c-brand-1); color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); font-weight: 600; }
.ntp-text { font-size: 1.35rem; line-height: 1.9; letter-spacing: 0.06em; min-height: 2.6rem; padding: 0.35rem 0.7rem; border-radius: 8px; background: var(--vp-c-bg); word-break: break-all; }
.ntp-prompt { color: var(--vp-c-text-1); font-weight: 700; }
.ntp-done { color: var(--vp-c-text-1); }
.ntp-slot { display: inline-block; min-width: 1.4em; text-align: center; margin-left: 0.1em; border-radius: 6px; border: 2px dashed var(--vp-c-brand-1); color: var(--vp-c-brand-1); }
.ntp-slot.filled { border-style: solid; background: var(--vp-c-brand-soft); font-weight: 700; }
.ntp-caption { font-size: 0.9rem; color: var(--vp-c-text-2); margin: 0.6rem 0 0.5rem; min-height: 3em; line-height: 1.6; }
.ntp-bars { display: grid; gap: 0.3rem; }
.ntp-row { display: grid; grid-template-columns: 2rem 1fr 11.5rem; align-items: center; gap: 0.6rem; font-size: 0.9rem; border-radius: 6px; padding: 0.05rem 0.25rem; }
.ntp-char { font-size: 1.1rem; text-align: center; font-weight: 600; }
.ntp-track { height: 0.85rem; border-radius: 4px; background: var(--vp-c-default-soft); overflow: hidden; }
.ntp-bar { display: block; height: 100%; border-radius: 4px; background: var(--vp-c-text-3); transition: width 0.35s ease; }
.ntp-p { font-variant-numeric: tabular-nums; color: var(--vp-c-text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ntp-row.pick { background: var(--vp-c-brand-soft); }
.ntp-row.pick .ntp-bar { background: var(--vp-c-brand-1); }
.ntp-row.pick .ntp-p, .ntp-row.pick .ntp-char { color: var(--vp-c-brand-1); font-weight: 700; }
.ntp-rest .ntp-bar { background: var(--vp-c-divider); }
.ntp-rest .ntp-char { color: var(--vp-c-text-3); }
@media (prefers-reduced-motion: reduce) { .ntp-bar { transition: none; } }
@media (max-width: 560px) { .ntp-row { grid-template-columns: 1.6rem 1fr 8.5rem; font-size: 0.8rem; } }
</style>
