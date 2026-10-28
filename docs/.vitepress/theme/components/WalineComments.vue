<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { WalineInstance } from '@waline/client'
import '@waline/client/style'

const serverURL = import.meta.env.VITE_WALINE_SERVER_URL?.trim()
const container = ref<HTMLElement | null>(null)
const loadFailed = ref(false)
let instance: WalineInstance | undefined

onMounted(async () => {
  if (!serverURL || !container.value) return

  try {
    const { init } = await import('@waline/client')
    if (!container.value) return

    instance = init({
      el: container.value,
      serverURL,
      path: location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/',
      lang: 'zh-CN',
      dark: 'html.dark',
      login: 'disable',
      meta: ['nick'],
      requiredMeta: [],
      imageUploader: false,
      wordLimit: 2000,
    })
  } catch {
    loadFailed.value = true
  }
})

onBeforeUnmount(() => instance?.destroy())
</script>

<template>
  <section class="reader-comments" aria-label="读者讨论">
    <h2>读者讨论</h2>
    <p>无需登录即可留言；昵称可留空。留言经审核后显示。</p>
    <div v-if="serverURL && !loadFailed" ref="container" />
    <p v-else>评论服务正在配置或暂时不可用，请稍后再来。</p>
  </section>
</template>
