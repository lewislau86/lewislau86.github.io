import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 22 章：训练诊断与评估","description":"先过拟合一个小 batch，再看验证损失、困惑度与生成样例。","frontmatter":{"title":"第 22 章：训练诊断与评估","description":"先过拟合一个小 batch，再看验证损失、困惑度与生成样例。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/training-evaluation.md","filePath":"tinyllm/training-evaluation.md"}');
const _sfc_main = { name: "tinyllm/training-evaluation.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-22-章-训练诊断与评估" tabindex="-1">第 22 章：训练诊断与评估 <a class="header-anchor" href="#第-22-章-训练诊断与评估" aria-label="Permalink to &quot;第 22 章：训练诊断与评估&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./training-loop.html">上一章</a> · <a href="./large-model-stability.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：先过拟合一个小 batch，再观察 loss、梯度、验证集困惑度和生成样例。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "training-evaluation" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>先做<strong>单个小 batch 过拟合</strong>来检查前向、反向和参数更新，再在独立验证集报告交叉熵、困惑度以及固定提示词的生成样例。困惑度只在相同 tokenizer 和数据口径下比较；一条训练 loss 曲线既不能证明泛化，也不能单独证明生成质量。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/training-evaluation.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const trainingEvaluation = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  trainingEvaluation as default
};
