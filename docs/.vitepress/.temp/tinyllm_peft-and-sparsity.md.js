import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"页面已移动","description":"","frontmatter":{"title":"页面已移动","search":false,"sidebar":false,"outline":false,"head":[["meta",{"http-equiv":"refresh","content":"0; url=/tinyllm/lora-finetuning.html"}]]},"headers":[],"relativePath":"tinyllm/peft-and-sparsity.md","filePath":"tinyllm/peft-and-sparsity.md"}');
const _sfc_main = { name: "tinyllm/peft-and-sparsity.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="页面已移动" tabindex="-1">页面已移动 <a class="header-anchor" href="#页面已移动" aria-label="Permalink to &quot;页面已移动&quot;">​</a></h1><p>TinyLLM 已调整章节结构。原“参数高效与稀疏结构”一章已拆分：LoRA 见<a href="./lora-finetuning.html">第 34 章：参数高效微调（LoRA）</a>，MoE 见<a href="./mixture-of-experts.html">第 24 章：稀疏专家（MoE）</a>。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/peft-and-sparsity.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const peftAndSparsity = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  peftAndSparsity as default
};
