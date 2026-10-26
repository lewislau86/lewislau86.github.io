<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useData } from 'vitepress'

const { page } = useData()
const enabled = ref(false)
const siteViews = ref<number | null>(null)
const pageViews = ref<number | null>(null)
const failed = ref(false)
let requestId = 0

async function updateCount() {
  const currentRequest = ++requestId
  failed.value = false
  pageViews.value = null

  try {
    // The public Busuanzi API needs the viewed URL on every client-side navigation.
    const response = await fetch('https://busuanzi.9420.ltd/api', {
      method: 'POST',
      headers: { 'x-bsz-referer': `${location.origin}${location.pathname}` }
    })
    if (!response.ok) throw new Error(`Busuanzi returned ${response.status}`)

    const result = await response.json() as {
      success?: boolean
      data?: { site_pv?: unknown; page_pv?: unknown }
    }
    const site = result.data?.site_pv
    const currentPage = result.data?.page_pv
    if (!result.success || typeof site !== 'number' || typeof currentPage !== 'number') {
      throw new Error('Busuanzi returned invalid counts')
    }

    if (currentRequest !== requestId) return
    siteViews.value = site
    pageViews.value = currentPage
  } catch {
    if (currentRequest === requestId) failed.value = true
  }
}

onMounted(() => {
  // Busuanzi does not accept localhost; previews should not alter public counts.
  enabled.value = location.hostname === 'lewislau86.github.io'
  if (enabled.value) void updateCount()
})

watch(() => page.value.relativePath, () => {
  if (enabled.value) void updateCount()
})
</script>

<template>
  <footer v-if="enabled" class="visit-counter" aria-label="访问统计">
    <span v-if="failed">访问量暂不可用</span>
    <template v-else>
      <span>本站访问量 <strong>{{ siteViews ?? '…' }}</strong> 次</span>
      <span>本页阅读量 <strong>{{ pageViews ?? '…' }}</strong> 次</span>
    </template>
  </footer>
</template>
