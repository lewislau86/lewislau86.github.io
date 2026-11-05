import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"页面已移动","description":"","frontmatter":{"title":"页面已移动","search":false,"sidebar":false,"outline":false,"head":[["meta",{"http-equiv":"refresh","content":"0; url=/tinyllm/#roadmap"}]]},"headers":[],"relativePath":"tinyllm/advanced-topics.md","filePath":"tinyllm/advanced-topics.md"}');
const _sfc_main = { name: "tinyllm/advanced-topics.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="页面已移动" tabindex="-1">页面已移动 <a class="header-anchor" href="#页面已移动" aria-label="Permalink to &quot;页面已移动&quot;">​</a></h1><p>TinyLLM 已调整章节结构。原“扩展专题”一章已拆到各章：分布式训练见<a href="./large-model-stability.html">第 23 章</a>，FlashAttention 与算子融合见<a href="./attention-kernels.html">第 27 章</a>，量化见<a href="./quantization.html">第 28 章</a>，对齐见<a href="./rlhf.html">第 35 章</a>与<a href="./preference-alignment.html">第 36 章</a>。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/advanced-topics.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const advancedTopics = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  advancedTopics as default
};
