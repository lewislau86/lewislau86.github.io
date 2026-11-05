import { ssrRenderAttrs } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"页面已移动","description":"","frontmatter":{"title":"页面已移动","search":false,"sidebar":false,"outline":false,"head":[["meta",{"http-equiv":"refresh","content":"0; url=/mini-redis/architecture.html"}]]},"headers":[],"relativePath":"mini-redis/00-architecture.md","filePath":"mini-redis/00-architecture.md"}');
const _sfc_main = { name: "mini-redis/00-architecture.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="页面已移动" tabindex="-1">页面已移动 <a class="header-anchor" href="#页面已移动" aria-label="Permalink to &quot;页面已移动&quot;">​</a></h1><p>请继续阅读<a href="./architecture.html">第 0 章：整体架构：代码职责、连接通信与后续优化</a>。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("mini-redis/00-architecture.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const _00Architecture = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  _00Architecture as default
};
