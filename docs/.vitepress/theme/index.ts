import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import TinyLLMMap from './components/TinyLLMMap.vue'
import MiniRedisMap from './components/MiniRedisMap.vue'
import NextTokenPlayer from './components/NextTokenPlayer.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    // 课程地图组件在 Markdown 中直接使用：<TinyLLMMap active="normalization" />
    app.component('TinyLLMMap', TinyLLMMap)
    app.component('MiniRedisMap', MiniRedisMap)
    // 逐字生成动画，数据来自 first-run.py 的真实记录：<NextTokenPlayer stage="after" />
    app.component('NextTokenPlayer', NextTokenPlayer)
  }
} satisfies Theme
