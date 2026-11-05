import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 34 章：参数高效微调（LoRA）","description":"冻结原模型，只训练低秩增量：LoRA 节省了什么、没有节省什么。","frontmatter":{"title":"第 34 章：参数高效微调（LoRA）","description":"冻结原模型，只训练低秩增量：LoRA 节省了什么、没有节省什么。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/lora-finetuning.md","filePath":"tinyllm/lora-finetuning.md"}');
const _sfc_main = { name: "tinyllm/lora-finetuning.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-34-章-参数高效微调-lora" tabindex="-1">第 34 章：参数高效微调（LoRA） <a class="header-anchor" href="#第-34-章-参数高效微调-lora" aria-label="Permalink to &quot;第 34 章：参数高效微调（LoRA）&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./instruction-finetuning.html">上一章</a> · <a href="./rlhf.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：低秩分解、LoRA 插在哪些线性层、秩与缩放系数、与全参数微调的显存和效果对比、把增量合并回原权重后推理。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "lora-finetuning" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>TinyLLM 小模型先用<strong>全参数微调</strong>建立质量和显存基线；只有微调显存或优化器状态成为约束时，才试 LoRA。LoRA 主要减少可训练参数和对应的优化器状态，并不减少基础权重的推理存储；合并增量后推理速度与原模型相同。MoE 属于模型结构，见<a href="./mixture-of-experts.html">第 24 章</a>。<a href="https://arxiv.org/abs/2106.09685" target="_blank" rel="noreferrer">LoRA 论文</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/lora-finetuning.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const loraFinetuning = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  loraFinetuning as default
};
