import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 21 章：训练循环与检查点","description":"DataLoader、前向反向、优化器与调度器的调用顺序，随机种子与检查点。","frontmatter":{"title":"第 21 章：训练循环与检查点","description":"DataLoader、前向反向、优化器与调度器的调用顺序，随机种子与检查点。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/training-loop.md","filePath":"tinyllm/training-loop.md"}');
const _sfc_main = { name: "tinyllm/training-loop.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-21-章-训练循环与检查点" tabindex="-1">第 21 章：训练循环与检查点 <a class="header-anchor" href="#第-21-章-训练循环与检查点" aria-label="Permalink to &quot;第 21 章：训练循环与检查点&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./gradient-stability.html">上一章</a> · <a href="./training-evaluation.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：DataLoader、forward/backward、optimizer/scheduler step、随机种子、保存与恢复。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "training-loop" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>主线显式记录随机种子、tokenizer 与模型配置；每次更新按 <code>zero_grad → forward → backward → clip → optimizer.step → scheduler.step</code> 执行，并保存模型、优化器、调度器和随机数状态。梯度累积时，多个 micro-batch 共同完成一次更新，学习率调度器只在真正更新后推进。恢复训练要用同一数据位置与配置，否则“接着训”可能改变数据顺序。<a href="https://pytorch.org/tutorials/recipes/recipes/saving_and_loading_a_general_checkpoint.html" target="_blank" rel="noreferrer">PyTorch 检查点教程</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/training-loop.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const trainingLoop = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  trainingLoop as default
};
