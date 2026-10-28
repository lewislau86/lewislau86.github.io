<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useData } from 'vitepress'

const { isDark } = useData()
const container = ref<HTMLElement | null>(null)

onMounted(() => {
  if (!container.value) return

  const script = document.createElement('script')
  script.src = 'https://giscus.app/client.js'
  script.async = true
  script.crossOrigin = 'anonymous'
  script.setAttribute('data-repo', 'lewislau86/lewislau86.github.io')
  script.setAttribute('data-repo-id', 'MDEwOlJlcG9zaXRvcnkxODUxMzQ5OTM=')
  script.setAttribute('data-category', 'General')
  script.setAttribute('data-category-id', 'DIC_kwDOCwjvkc4DJzn9')
  script.setAttribute('data-mapping', 'specific')
  script.setAttribute('data-term', location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/')
  script.setAttribute('data-strict', '1')
  script.setAttribute('data-reactions-enabled', '1')
  script.setAttribute('data-emit-metadata', '0')
  script.setAttribute('data-input-position', 'top')
  script.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  script.setAttribute('data-lang', 'zh-CN')
  script.setAttribute('data-loading', 'lazy')
  container.value.appendChild(script)
})

watch(isDark, (dark) => {
  const frame = container.value?.querySelector<HTMLIFrameElement>('iframe.giscus-frame')
  frame?.contentWindow?.postMessage(
    { giscus: { setConfig: { theme: dark ? 'dark' : 'light' } } },
    'https://giscus.app',
  )
})
</script>

<template>
  <section class="reader-comments" aria-label="读者讨论">
    <h2>读者讨论</h2>
    <p>欢迎交流疑问、补充资料和勘误。使用 GitHub 账号参与讨论。</p>
    <div ref="container" />
    <p class="reader-comments-link">
      评论区无法加载时，可前往
      <a href="https://github.com/lewislau86/lewislau86.github.io/discussions" target="_blank" rel="noopener noreferrer">GitHub 讨论区</a>。
    </p>
  </section>
</template>
