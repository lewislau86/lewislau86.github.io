import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"关于","description":"","frontmatter":{},"headers":[],"relativePath":"about.md","filePath":"about.md"}');
const _sfc_main = { name: "about.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="关于" tabindex="-1">关于 <a class="header-anchor" href="#关于" aria-label="Permalink to &quot;关于&quot;">​</a></h1><p>这里是 Lewis 的个人知识库，用于持续整理技术研究、项目文档与学习笔记。</p><h2 id="整理方式" tabindex="-1">整理方式 <a class="header-anchor" href="#整理方式" aria-label="Permalink to &quot;整理方式&quot;">​</a></h2><p>内容按主题组织，并在实践中持续修订。尽量记录问题的背景、解决过程与验证结果，让文档既能帮助当下，也便于以后回顾。</p><h2 id="github" tabindex="-1">GitHub <a class="header-anchor" href="#github" aria-label="Permalink to &quot;GitHub&quot;">​</a></h2><p>文档源文件保存在 <a href="https://github.com/lewislau86/lewislau86.github.io" target="_blank" rel="noreferrer">GitHub 仓库</a>。如发现错误或需要补充，可以通过仓库提出建议。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("about.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const about = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  about as default
};
