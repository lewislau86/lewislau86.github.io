<script setup lang="ts">
import { computed } from 'vue'
import { withBase } from 'vitepress'
import course from '../../../../scripts/learn-agent-rust-lessons.json'

const props = defineProps<{ active: string }>()
const current = computed(() => course.lessons.find(lesson => lesson.slug === props.active))
const parts = computed(() => course.parts.map(part => ({
  ...part,
  lessons: course.lessons.filter(lesson => lesson.part === part.id)
})))
</script>

<template>
  <nav class="agent-map" aria-label="Learn Agent by Rust 课程地图">
    <p class="map-title">本章在全书中的位置</p>
    <p v-if="current" class="current">{{ current.id }} · {{ current.title }}：{{ current.question }}</p>
    <ol class="parts">
      <li v-for="part in parts" :key="part.id" :class="{ active: current?.part === part.id }">
        <a :href="withBase('/learn-agent-rust/learning-path.html#' + part.lessons[0].id.toLowerCase())">
          {{ part.title }}
        </a>
        <span>{{ part.lessons[0].id }}—{{ part.lessons[part.lessons.length - 1].id }}</span>
      </li>
    </ol>
    <details>
      <summary>展开章节位置与状态</summary>
      <div v-for="part in parts" :key="part.id" class="chapter-group">
        <a v-for="lesson in part.lessons" :key="lesson.id"
           :href="withBase('/learn-agent-rust/' + lesson.slug + '.html')"
           :aria-current="lesson.slug === active ? 'page' : undefined"
           :class="{ selected: lesson.slug === active }">
          {{ lesson.id }} {{ lesson.title }}{{ lesson.status === 'planned' ? '（规划）' : '' }}
        </a>
      </div>
    </details>
    <p class="map-note">模块卡片链接到学习路径；正文与实验状态以章节页为准。</p>
  </nav>
</template>

<style scoped>
.agent-map { margin: 1.8rem 0; padding: 1rem 1.1rem; border: 1px solid var(--vp-c-divider); border-radius: 12px; background: var(--vp-c-bg-soft); }
.map-title { margin: 0; font-weight: 700; }
.current { margin: .5rem 0 1rem; color: var(--vp-c-text-2); font-size: .9rem; }
.parts { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: .6rem; padding: 0; list-style: none; }
.parts li { margin: 0; padding: .65rem .8rem; border: 1px solid var(--vp-c-divider); border-radius: 8px; background: var(--vp-c-bg); }
.parts li.active { border-color: var(--vp-c-brand-1); background: var(--vp-c-brand-soft); }
.parts a { font-size: .85rem; font-weight: 600; text-decoration: none; }
.parts span { display: block; color: var(--vp-c-text-2); font-size: .8rem; }
summary { cursor: pointer; font-size: .85rem; }
.chapter-group { display: flex; flex-wrap: wrap; gap: .4rem .8rem; margin: .65rem 0; }
.chapter-group a { font-size: .8rem; }
.chapter-group a.selected { font-weight: 700; }
.map-note { margin: .65rem 0 0; color: var(--vp-c-text-2); font-size: .8rem; }
</style>
