import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import TinyLLMMap from './components/TinyLLMMap.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    // 课程地图组件在 Markdown 中直接使用：<TinyLLMMap active="normalization" />
    app.component('TinyLLMMap', TinyLLMMap)
  }
} satisfies Theme
