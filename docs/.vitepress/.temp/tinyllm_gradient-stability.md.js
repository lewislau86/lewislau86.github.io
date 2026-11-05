import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 20 章：梯度稳定与累积","description":"梯度裁剪、FP16 Loss Scaling、梯度累积与梯度监测。","frontmatter":{"title":"第 20 章：梯度稳定与累积","description":"梯度裁剪、FP16 Loss Scaling、梯度累积与梯度监测。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/gradient-stability.md","filePath":"tinyllm/gradient-stability.md"}');
const _sfc_main = { name: "tinyllm/gradient-stability.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-20-章-梯度稳定与累积" tabindex="-1">第 20 章：梯度稳定与累积 <a class="header-anchor" href="#第-20-章-梯度稳定与累积" aria-label="Permalink to &quot;第 20 章：梯度稳定与累积&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./precision.html">上一章</a> · <a href="./training-loop.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。预计覆盖：Gradient Clipping、FP16 Loss Scaling（<code>GradScaler</code>）、梯度累积与梯度数值监测；解释它们在训练循环中的调用顺序。</p></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "gradient-stability" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>默认记录全局梯度范数，并在 <code>optimizer.step()</code> 前按全局范数裁剪；显存不足时用梯度累积达到目标有效 batch。BF16/FP32 不默认使用 <code>GradScaler</code>；FP16 路径先 <code>unscale_</code> 再裁剪，防止把放大后的梯度当真实范数。裁剪阈值应随损失归一化、模型和训练曲线调整。<a href="https://docs.pytorch.org/docs/stable/notes/amp_examples.html#gradient-clipping" target="_blank" rel="noreferrer">PyTorch AMP 梯度裁剪示例</a></p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/gradient-stability.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const gradientStability = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  gradientStability as default
};
