<script setup lang="ts">
// 动画共用的控制条：从头 / 上一步 / 播放·暂停 / 下一步 / 进度滑块。
// p 是 reactive(usePlayer(...)) 的结果。
const props = defineProps<{ p: any; label?: string }>()
</script>

<template>
  <div class="pc">
    <button @click="p.restart()">从头</button>
    <button @click="p.prev()">上一步</button>
    <button class="pc-play" @click="p.toggle()">
      <svg v-if="!p.playing" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1L9 5L2 9Z" /></svg>
      <svg v-else viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1H4V9H2ZM6 1H8V9H6Z" /></svg>
      {{ p.playing ? '暂停' : '播放' }}
    </button>
    <button @click="p.step()">下一步</button>
    <input type="range" min="0" :max="p.total - 1" :value="p.frame" @input="p.seek(+($event.target as HTMLInputElement).value)" aria-label="拖动到任意一步" />
    <span class="pc-count">{{ label ?? `${p.frame + 1} / ${p.total}` }}</span>
  </div>
</template>

<style scoped>
.pc { display: flex; align-items: center; gap: 0.45rem; margin-top: 0.9rem; flex-wrap: wrap; }
.pc button { padding: 0.15rem 0.6rem; border-radius: 6px; border: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); font-size: 0.9rem; }
.pc button:hover { border-color: var(--vp-c-brand-1); }
.pc-play { color: var(--vp-c-brand-1); font-weight: 600; min-width: 4.8rem; display: inline-flex; align-items: center; gap: 0.3rem; }
.pc-play svg { width: 0.7rem; height: 0.7rem; fill: currentColor; }
.pc input[type=range] { flex: 1; min-width: 8rem; accent-color: var(--vp-c-brand-1); }
.pc-count { font-size: 0.85rem; color: var(--vp-c-text-2); font-variant-numeric: tabular-nums; min-width: 3.6rem; text-align: right; }
</style>
