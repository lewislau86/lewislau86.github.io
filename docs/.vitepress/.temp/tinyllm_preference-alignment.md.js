import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 36 章：DPO 与 GRPO","description":"把 RLHF 变简单：DPO 不用奖励模型直接从偏好数据学；GRPO 不用价值模型，用可自动判分的任务训练推理能力。","frontmatter":{"title":"第 36 章：DPO 与 GRPO","description":"把 RLHF 变简单：DPO 不用奖励模型直接从偏好数据学；GRPO 不用价值模型，用可自动判分的任务训练推理能力。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/preference-alignment.md","filePath":"tinyllm/preference-alignment.md"}');
const _sfc_main = { name: "tinyllm/preference-alignment.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-36-章-dpo-与-grpo" tabindex="-1">第 36 章：DPO 与 GRPO <a class="header-anchor" href="#第-36-章-dpo-与-grpo" aria-label="Permalink to &quot;第 36 章：DPO 与 GRPO&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./rlhf.html">上一章</a> · <a href="./agent-memory.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：从 RLHF 的目标推出 DPO：为什么可以跳过奖励模型和 PPO，直接用成对偏好训练；GRPO：同一个问题采样一组回答、组内比较打分，省掉价值模型；可验证奖励（算术题答案对不对、代码能不能通过测试）与推理模型；三种方法在同一任务上的效果、显存和稳定性对比。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "preference-alignment" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>在 SFT 模型上先用 <strong>DPO</strong>：数据只需要成对的偏好，不用单独训练奖励模型，流程和 SFT 接近，和<a href="./rlhf.html">第 35 章</a>的 RLHF 在同一份数据上对比。有能自动判对错的任务时，再用 GRPO 训练并观察回答长度和正确率的变化。对齐后要同时检查目标任务和原有能力，防止为了迎合偏好而退化。<a href="https://arxiv.org/abs/2305.18290" target="_blank" rel="noreferrer">DPO</a> · <a href="https://arxiv.org/abs/2402.03300" target="_blank" rel="noreferrer">DeepSeekMath（GRPO）</a> · <a href="https://arxiv.org/abs/2501.12948" target="_blank" rel="noreferrer">DeepSeek-R1</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/preference-alignment.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const preferenceAlignment = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  preferenceAlignment as default
};
