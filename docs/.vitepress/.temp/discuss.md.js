import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"读者讨论","description":"交流教程问题、补充资料和勘误。","frontmatter":{"title":"读者讨论","description":"交流教程问题、补充资料和勘误。"},"headers":[],"relativePath":"discuss.md","filePath":"discuss.md"}');
const _sfc_main = { name: "discuss.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="读者讨论" tabindex="-1">读者讨论 <a class="header-anchor" href="#读者讨论" aria-label="Permalink to &quot;读者讨论&quot;">​</a></h1><p>欢迎交流 TinyLLM、mini-redis 和 Burn 教程中的问题，也欢迎补充资料和指出错误。可在本页下方匿名留言；留言经审核后公开显示。</p><p>讨论某篇文章时，也可以在文章底部留言。先前通过 giscus 发布的内容仍可在 <a href="https://github.com/lewislau86/lewislau86.github.io/discussions" target="_blank" rel="noreferrer">GitHub Discussions</a> 查看。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("discuss.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const discuss = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  discuss as default
};
