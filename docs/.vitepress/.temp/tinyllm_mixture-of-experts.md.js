import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 24 章：稀疏专家（MoE）","description":"把前馈层换成多个专家和一个路由器：同样的计算量装下更多参数，以及怎样让专家分工均衡。","frontmatter":{"title":"第 24 章：稀疏专家（MoE）","description":"把前馈层换成多个专家和一个路由器：同样的计算量装下更多参数，以及怎样让专家分工均衡。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/mixture-of-experts.md","filePath":"tinyllm/mixture-of-experts.md"}');
const _sfc_main = { name: "tinyllm/mixture-of-experts.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-24-章-稀疏专家-moe" tabindex="-1">第 24 章：稀疏专家（MoE） <a class="header-anchor" href="#第-24-章-稀疏专家-moe" aria-label="Permalink to &quot;第 24 章：稀疏专家（MoE）&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./large-model-stability.html">上一章</a> · <a href="./generation.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：路由器与 top-k 专家；与“激活参数相同”和“总参数相同”的稠密模型对比；路由崩塌与负载均衡（辅助损失、无辅助损失的偏置调整）；观察专家的分工；稀疏升级（把训练好的稠密模型改成 MoE 继续训练）。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "mixture-of-experts" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>TinyLLM 主线保持<strong>稠密</strong>。本章把每个 Block 的 SwiGLU 换成路由器加多个小专家，其余代码不变，用相同数据和训练步数从头训练，与主线对比；再用稀疏升级，从已经训练好的稠密模型出发继续训练。MoE 是模型做大以后的选择：参数规模或推理成本成为瓶颈时再切换，具体结论以本章实验为准。<a href="https://arxiv.org/abs/2101.03961" target="_blank" rel="noreferrer">Switch Transformer</a> · <a href="https://arxiv.org/abs/2412.19437" target="_blank" rel="noreferrer">DeepSeek-V3 技术报告</a> · <a href="https://arxiv.org/abs/2212.05055" target="_blank" rel="noreferrer">Sparse Upcycling</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/mixture-of-experts.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const mixtureOfExperts = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  mixtureOfExperts as default
};
