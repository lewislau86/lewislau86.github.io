<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import { computed } from 'vue'
import { useData, useRoute } from 'vitepress'
import VisitCounter from './VisitCounter.vue'
import GiscusComments from './components/GiscusComments.vue'

const route = useRoute()
const { frontmatter } = useData()
const showComments = computed(() =>
  frontmatter.value.search !== false &&
  (/^\/(tinyllm|mini-redis|burn)\//.test(route.path) || /^\/discuss(?:\.html)?$/.test(route.path)),
)
</script>

<template>
  <DefaultTheme.Layout>
    <template #doc-after>
      <ClientOnly>
        <GiscusComments v-if="showComments" :key="route.path" />
      </ClientOnly>
    </template>
    <template #layout-bottom>
      <VisitCounter />
    </template>
  </DefaultTheme.Layout>
</template>
