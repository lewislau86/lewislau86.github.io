import { ref, computed, onBeforeUnmount, type Ref } from 'vue'

// 所有动画共用的播放逻辑：帧号、播放/暂停、单步、从头。
// start 为初始帧；教学动画通常从最后一帧开始，没运行脚本的读者也能看到完整结果，点“播放”再从头重演。
export function usePlayer(total: Ref<number> | (() => number), options: { interval?: number; start?: 'first' | 'last' } = {}) {
  const n = typeof total === 'function' ? computed(total) : total
  const frame = ref(options.start === 'last' ? n.value - 1 : 0)
  const playing = ref(false)
  let timer: ReturnType<typeof setInterval> | undefined

  function stop() {
    playing.value = false
    if (timer) clearInterval(timer)
    timer = undefined
  }
  function next() {
    if (frame.value < n.value - 1) frame.value++
    else stop()
  }
  function step() { stop(); next() }
  function prev() { stop(); if (frame.value > 0) frame.value-- }
  function restart() { stop(); frame.value = 0 }
  function toggle() {
    if (playing.value) return stop()
    if (frame.value >= n.value - 1) frame.value = 0
    playing.value = true
    timer = setInterval(next, options.interval ?? 900)
  }
  function seek(f: number) { stop(); frame.value = Math.max(0, Math.min(n.value - 1, f)) }
  onBeforeUnmount(stop)
  return { frame, playing, total: n, next, step, prev, restart, toggle, seek, stop }
}
