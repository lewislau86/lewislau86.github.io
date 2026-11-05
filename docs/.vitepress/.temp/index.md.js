import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"文档首页","description":"","frontmatter":{"title":"文档首页"},"headers":[],"relativePath":"index.md","filePath":"index.md"}');
const _sfc_main = { name: "index.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="lewis-的知识库" tabindex="-1">Lewis 的知识库 <a class="header-anchor" href="#lewis-的知识库" aria-label="Permalink to &quot;Lewis 的知识库&quot;">​</a></h1><p>记录技术研究，整理项目文档，沉淀学习笔记。</p><p>这里按主题和章节组织内容。每篇文档都可以持续补充，让零散的记录逐渐成为可以查阅、复用的知识。</p><h2 id="文档集" tabindex="-1">文档集 <a class="header-anchor" href="#文档集" aria-label="Permalink to &quot;文档集&quot;">​</a></h2><h3 id="tinyllm-·-从零学习语言模型" tabindex="-1"><a href="./tinyllm/">TinyLLM · 从零学习语言模型</a> <a class="header-anchor" href="#tinyllm-·-从零学习语言模型" aria-label="Permalink to &quot;[TinyLLM · 从零学习语言模型](./tinyllm/index.md)&quot;">​</a></h3><p>先用不到 100 行代码跑通一个会写唐诗的小模型，再顺着数据流从分词、词嵌入、注意力一路搭出模型，接着用残差、初始化和归一化让深层网络训得动，最后是训练、推理、后训练与应用。课程分八部分、规划 37 章，目前第 1～17、19、25、26 章已有完整教案、配图和配套 notebook；每章开头的架构总图会标出本章负责的零件。只有半小时的话，从<a href="./tinyllm/quickstart.html">30 分钟快速体验</a>开始。</p><p><a href="./tinyllm/">进入 TinyLLM 教程 →</a></p><h3 id="mini-redis-·-从源码学习-rust-与-redis-架构" tabindex="-1"><a href="./mini-redis/">mini-redis · 从源码学习 Rust 与 Redis 架构</a> <a class="header-anchor" href="#mini-redis-·-从源码学习-rust-与-redis-架构" aria-label="Permalink to &quot;[mini-redis · 从源码学习 Rust 与 Redis 架构](./mini-redis/index.md)&quot;">​</a></h3><p>沿着一条 SET/GET 请求，学习 Rust 所有权、Tokio 异步任务、共享存储、过期清理、发布订阅与优雅停机。包含整体架构导读、13 章教程、28 篇逐文件源码分析、Rust 源码阅读说明、6 个可运行实验、源码学习包及原始验证记录。第 13 章记录 TTL 测试挂起的定位与修复过程。</p><p><a href="./mini-redis/">进入 mini-redis 教程 →</a></p><h3 id="深入理解-burn-深度学习框架" tabindex="-1"><a href="./burn/">深入理解 Burn 深度学习框架</a> <a class="header-anchor" href="#深入理解-burn-深度学习框架" aria-label="Permalink to &quot;[深入理解 Burn 深度学习框架](./burn/index.md)&quot;">​</a></h3><p>从环境、模型数学、张量与 Rust 出发，通过 learn-cuda 学习 GPU 的线程、内存与分块，再认识 Rust CUDA 和 CubeCL，随后进入 Burn 的模型、后端、自动微分、训练、执行性能、部署与扩展。全书分七部分、18 章，统一学习目标、实践方式与章间导航；最后用 PyTorch 对照、源码追踪和实验索引检查理解。CPU 学习包以 Burn 0.22.1 为基线，实际验证范围在实验章逐项说明。</p><p>另有配备公式、图解、手算和自测的<a href="./burn/math-foundations.html">数学预备篇</a>，可按需与正文对照阅读。</p><p><a href="./burn/">进入 Burn 教程 →</a></p><h2 id="从这里开始" tabindex="-1">从这里开始 <a class="header-anchor" href="#从这里开始" aria-label="Permalink to &quot;从这里开始&quot;">​</a></h2><p>更多文档将逐步整理。你可以通过左侧目录浏览文档，通过右侧目录定位当前章节，也可以使用顶部搜索查找内容。</p><ul><li><strong>技术研究</strong>：记录概念、原理、方案比较与实验结论。</li><li><strong>项目文档</strong>：整理架构设计、使用说明和实践经验。</li><li><strong>学习笔记</strong>：按学习路径组织知识点、示例和问题。</li></ul><h2 id="阅读与查找" tabindex="-1">阅读与查找 <a class="header-anchor" href="#阅读与查找" aria-label="Permalink to &quot;阅读与查找&quot;">​</a></h2><p>点击左侧目录切换文档；阅读长文时，使用右侧的「本页目录」跳转到具体章节。在手机上，点击「文档目录」展开导航。</p><p>点击顶部「搜索文档」，或按下 <code>⌘ K</code>（Windows / Linux 为 <code>Ctrl K</code>），输入关键词即可查找已收录的内容。</p><h2 id="开始整理文档" tabindex="-1">开始整理文档 <a class="header-anchor" href="#开始整理文档" aria-label="Permalink to &quot;开始整理文档&quot;">​</a></h2><p>准备写第一篇文档时，可以从 <a href="./guide/writing.html">新增与发布文档</a> 开始。需要标题、代码块、表格等写作格式时，参考 <a href="./guide/markdown.html">Markdown 写作示例</a>。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("index.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const index = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  index as default
};
