<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import VisitCounter from './VisitCounter.vue'
</script>

<template>
  <DefaultTheme.Layout>
    <template #layout-bottom>
      <VisitCounter />
    </template>
  </DefaultTheme.Layout>
</template>
