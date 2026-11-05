import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 33 章：指令微调","description":"在预训练模型上做监督微调：对话模板、只对答案计算 loss。","frontmatter":{"title":"第 33 章：指令微调","description":"在预训练模型上做监督微调：对话模板、只对答案计算 loss。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/instruction-finetuning.md","filePath":"tinyllm/instruction-finetuning.md"}');
const _sfc_main = { name: "tinyllm/instruction-finetuning.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-33-章-指令微调" tabindex="-1">第 33 章：指令微调 <a class="header-anchor" href="#第-33-章-指令微调" aria-label="Permalink to &quot;第 33 章：指令微调&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./inference-optimization.html">上一章</a> · <a href="./lora-finetuning.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：预训练与监督微调、对话模板、只对答案计算 loss、基础评估。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "instruction-finetuning" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>在预训练权重上做 <strong>SFT</strong>，固定对话模板和终止 token，并仅对助手答案位置计算 loss。这样监督目标对应模型需要生成的内容；模板或 mask 不一致会让训练目标和推理提示词错位。数据量不足或显存受限时再比较 <a href="./lora-finetuning.html">LoRA</a> 微调。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/instruction-finetuning.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const instructionFinetuning = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  instructionFinetuning as default
};
