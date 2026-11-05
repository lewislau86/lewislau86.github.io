import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 31 章：KV 显存管理：分页与前缀缓存","description":"把 KV cache 从一整块连续张量换成一块块固定大小的页：分页怎样消除碎片和超配，前缀缓存怎样让多个请求共用同一段提示词的缓存，以及命中率和淘汰策略怎样实测。","frontmatter":{"title":"第 31 章：KV 显存管理：分页与前缀缓存","description":"把 KV cache 从一整块连续张量换成一块块固定大小的页：分页怎样消除碎片和超配，前缀缓存怎样让多个请求共用同一段提示词的缓存，以及命中率和淘汰策略怎样实测。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/kv-memory.md","filePath":"tinyllm/kv-memory.md"}');
const _sfc_main = { name: "tinyllm/kv-memory.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-31-章-kv-显存管理-分页与前缀缓存" tabindex="-1">第 31 章：KV 显存管理：分页与前缀缓存 <a class="header-anchor" href="#第-31-章-kv-显存管理-分页与前缀缓存" aria-label="Permalink to &quot;第 31 章：KV 显存管理：分页与前缀缓存&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./batching.html">上一章</a> · <a href="./inference-optimization.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。<a href="./inference-efficiency.html">第 26 章</a>算过 KV cache 要占多少字节，<a href="./batching.html">第 30 章</a>让很多请求同时进来；两件事撞在一起，显存里的 KV 怎么放就成了瓶颈。预计覆盖：</p><ul><li><strong>连续分配为什么浪费。</strong> 每个请求按最大长度预留一整块，实际只用到一部分；算一算预分配和实际使用差多少，这就是分页要解决的问题。</li><li><strong>分页。</strong> 缓存切成固定大小的页，一张块表把逻辑位置映射到物理页；序列增长时只追加新的页，不同请求的页可以放在不连续的位置上，注意力按块表去读。</li><li><strong>前缀共享。</strong> 两个请求开头一样，就让它们的块表前几项指向同一批页；写时再复制。多轮对话与固定 system prompt 是最常见的两种命中场景，统计命中率。</li><li><strong>淘汰。</strong> 显存有限，没人再用的页要回收；按最近使用还是按引用计数，淘汰错了会重算，淘汰对了才省。</li><li><strong>offloading 的边界。</strong> 把冷页搬到内存甚至磁盘，收益取决于“搬回来的代价”和“重算的代价”谁更小，需要和全在显存里的基线比。</li></ul></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "kv-memory" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>主线先在 CPU 上实现一张<strong>块表</strong>：逻辑位置 → 物理页，页大小取 4 或 8 个 token，注意力按块表把 K、V 拼出来。第一件事是验证正确性：分页后的注意力输出与连续存储逐元素一致（沿用<a href="./inference-efficiency.html">第 26 章</a>的对照写法）。第二件事是记账：同一份请求流下，比较“按最大长度预分配”和“按页追加”各占多少槽位、真正存了多少 token，报告两者的比值。第三件事是前缀共享：用多轮对话式的请求流，统计有多少页被复用、省下多少次 prefill。</p><p>分页是<strong>分配方式</strong>的改变，不改变数学结果；这一点要先用代码证明，再谈收益。指标以“分配槽位 / 实际使用”“页复用次数”这类计数为主，因为它们在 CPU 上就能精确测出；显存峰值和吞吐放在标注了环境的 GPU 实验里。淘汰策略和 offloading 只做小规模模拟，并明确说明是模拟。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/kv-memory.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const kvMemory = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  kvMemory as default
};
