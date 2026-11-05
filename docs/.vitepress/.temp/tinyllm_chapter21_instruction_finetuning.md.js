import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"页面已移动","description":"","frontmatter":{"title":"页面已移动","search":false,"sidebar":false,"outline":false,"head":[["meta",{"http-equiv":"refresh","content":"0; url=/tinyllm/instruction-finetuning.html"}]]},"headers":[],"relativePath":"tinyllm/chapter21_instruction_finetuning.md","filePath":"tinyllm/chapter21_instruction_finetuning.md"}');
const _sfc_main = { name: "tinyllm/chapter21_instruction_finetuning.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="页面已移动" tabindex="-1">页面已移动 <a class="header-anchor" href="#页面已移动" aria-label="Permalink to &quot;页面已移动&quot;">​</a></h1><p>TinyLLM 已调整章节顺序。请继续阅读<a href="./instruction-finetuning.html">第 33 章：指令微调</a>。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/chapter21_instruction_finetuning.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const chapter21_instruction_finetuning = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  chapter21_instruction_finetuning as default
};
