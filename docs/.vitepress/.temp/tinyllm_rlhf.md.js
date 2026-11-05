import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 35 章：RLHF：奖励模型与 PPO","description":"SFT 之后怎样让回答更符合人的偏好：偏好数据、奖励模型、PPO 与 KL 约束，这是 ChatGPT 背后的经典流程。","frontmatter":{"title":"第 35 章：RLHF：奖励模型与 PPO","description":"SFT 之后怎样让回答更符合人的偏好：偏好数据、奖励模型、PPO 与 KL 约束，这是 ChatGPT 背后的经典流程。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/rlhf.md","filePath":"tinyllm/rlhf.md"}');
const _sfc_main = { name: "tinyllm/rlhf.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-35-章-rlhf-奖励模型与-ppo" tabindex="-1">第 35 章：RLHF：奖励模型与 PPO <a class="header-anchor" href="#第-35-章-rlhf-奖励模型与-ppo" aria-label="Permalink to &quot;第 35 章：RLHF：奖励模型与 PPO&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./lora-finetuning.html">上一章</a> · <a href="./preference-alignment.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：RLHF 的三步流程（SFT → 训练奖励模型 → 用强化学习优化策略）；偏好数据怎样收集（同一个问题的两个回答，人来选更好的那个）；奖励模型怎样从“二选一”学出打分（Bradley–Terry 损失）；PPO 的策略、参考、奖励、价值四个模型各做什么；KL 惩罚为什么必不可少；奖励被“钻空子”（reward hacking）的例子。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "rlhf" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>在<a href="./instruction-finetuning.html">第 33 章</a>的 SFT 模型上，用一个可控的小任务把 <strong>RLHF 三步完整实现一遍</strong>：先训练奖励模型，再用 PPO 加 KL 惩罚优化，并记录奖励、KL 和生成样例。RLHF 是理解后面所有对齐方法的基础；但它要同时维护四个模型，训练也容易不稳定，TinyLLM 实际使用的对齐方法见<a href="./preference-alignment.html">第 36 章</a>。<a href="https://arxiv.org/abs/2203.02155" target="_blank" rel="noreferrer">InstructGPT</a> · <a href="https://arxiv.org/abs/1707.06347" target="_blank" rel="noreferrer">PPO</a> · <a href="https://arxiv.org/abs/2009.01325" target="_blank" rel="noreferrer">Learning to Summarize from Human Feedback</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/rlhf.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const rlhf = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  rlhf as default
};
