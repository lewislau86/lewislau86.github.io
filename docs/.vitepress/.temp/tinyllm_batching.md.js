import { resolveComponent, useSSRContext } from "vue";
import { ssrRenderAttrs, ssrRenderComponent } from "vue/server-renderer";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"第 30 章：批处理与调度","description":"很多请求同时来时，怎样把它们排进同一个推理循环：静态、动态与连续批处理，padding 的浪费，chunked prefill 与 decode 拼批，以及用等待时间和 goodput 衡量调度好不好。","frontmatter":{"title":"第 30 章：批处理与调度","description":"很多请求同时来时，怎样把它们排进同一个推理循环：静态、动态与连续批处理，padding 的浪费，chunked prefill 与 decode 拼批，以及用等待时间和 goodput 衡量调度好不好。","pageClass":"tinyllm-course"},"headers":[],"relativePath":"tinyllm/batching.md","filePath":"tinyllm/batching.md"}');
const _sfc_main = { name: "tinyllm/batching.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  const _component_TinyLLMMap = resolveComponent("TinyLLMMap");
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="第-30-章-批处理与调度" tabindex="-1">第 30 章：批处理与调度 <a class="header-anchor" href="#第-30-章-批处理与调度" aria-label="Permalink to &quot;第 30 章：批处理与调度&quot;">​</a></h1><p><a href="./">课程总览</a> · <a href="./speculative-decoding.html">上一章</a> · <a href="./kv-memory.html">下一章</a></p><div class="info custom-block"><p class="custom-block-title">本章状态：规划中</p><p>正文与 notebook 尚未完成。到目前为止每个请求都是单独处理的，本章处理第一个真正的服务问题：多个请求同时到达。预计覆盖：</p><ul><li><strong>为什么要批。</strong> decode 每一步都要把全部权重从显存读一遍，读一次给一个请求用和给 16 个请求用，读的量一样。批量把这份开销摊薄。</li><li><strong>三种批法。</strong> 静态批处理要等够固定数量、且整批一起结束；动态批处理改成按时间窗口收；连续批处理按 token 步调度，哪个请求生成了停止符就立刻换上下一个。</li><li><strong>等长之外的问题。</strong> 变长序列靠 padding 拼成矩形，短序列的填充位置照样占算力；记录一批里多少位置是白算的。</li><li><strong>chunked prefill。</strong> 一个长提示词的 prefill 会占住整个前向，让所有正在解码的请求停一下；把它切块和 decode 拼在同一批里，能在 prefill 没做完时也让其他请求继续出字。</li><li><strong>用什么衡量。</strong> 首字延迟（TTFT）、每 token 延迟（TPOT）、吞吐，以及只有满足时延目标才算数的 goodput；<a href="./inference-efficiency.html">第 26 章</a>的指标在这里第一次被用来比较调度策略。</li></ul></div>`);
  _push(ssrRenderComponent(_component_TinyLLMMap, { active: "batching" }, null, _parent));
  _push(`<h2 id="本章主线选择-待实验验证" tabindex="-1">本章主线选择（待实验验证） <a class="header-anchor" href="#本章主线选择-待实验验证" aria-label="Permalink to &quot;本章主线选择（待实验验证）&quot;">​</a></h2><p>主线写一个最小的推理循环：请求带到达时间和目标输出长度，由固定的随机数生成器预先排好一批请求流（和<a href="./tinyllm-model.html">第 12 章</a>的 batch 计划同一个思路），然后依次换成静态、动态、连续三种调度，在同一份请求流上比较每个请求的等待时间与总步数。指标以<strong>步数和白算的位置数</strong>为主，墙钟时间放在第二位并标清环境。</p><p>chunked prefill 单独做一组：同一个长提示词，一次 prefill 与切成 2、4 块并且和 decode 拼批，比较每一步的 prefill token 数与正在解码的请求能否继续出字。分块不改变数学结果，这一点用 KV cache 的等价性直接验证（<a href="./inference-efficiency.html">第 26 章</a>已经用过同样的做法）。</p><p>批处理本身不解决显存：把更多请求同时放进来，KV cache 会先撑不住。下一章讲显存里的 KV 怎样分配和复用。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("tinyllm/batching.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const batching = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  batching as default
};
