import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import TinyLLMMap from './components/TinyLLMMap.vue'
import MiniRedisMap from './components/MiniRedisMap.vue'
import NextTokenPlayer from './components/NextTokenPlayer.vue'
import AttentionStepper from './components/AttentionStepper.vue'
import RopeSlider from './components/RopeSlider.vue'
import OptimizerRace from './components/OptimizerRace.vue'
import BackpropFlow from './components/BackpropFlow.vue'
import KVCacheRace from './components/KVCacheRace.vue'
import ResidualStreamLens from './components/ResidualStreamLens.vue'
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
    // 其余教学动画：数据都来自 scripts/data，由各章配套脚本真实运行得到
    app.component('AttentionStepper', AttentionStepper)   // 第 5 章
    app.component('RopeSlider', RopeSlider)               // 第 6 章
    app.component('OptimizerRace', OptimizerRace)         // 第 16 章
    app.component('BackpropFlow', BackpropFlow)           // 第 2 章
    app.component('KVCacheRace', KVCacheRace)             // 第 26 章
    app.component('ResidualStreamLens', ResidualStreamLens) // 第 8 章
  }
} satisfies Theme
