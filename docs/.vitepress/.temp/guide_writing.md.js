import { ssrRenderAttrs, ssrRenderStyle } from "vue/server-renderer";
import { useSSRContext } from "vue";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const __pageData = JSON.parse('{"title":"新增与发布文档","description":"","frontmatter":{},"headers":[],"relativePath":"guide/writing.md","filePath":"guide/writing.md"}');
const _sfc_main = { name: "guide/writing.md" };
function _sfc_ssrRender(_ctx, _push, _parent, _attrs, $props, $setup, $data, $options) {
  _push(`<div${ssrRenderAttrs(_attrs)}><h1 id="新增与发布文档" tabindex="-1">新增与发布文档 <a class="header-anchor" href="#新增与发布文档" aria-label="Permalink to &quot;新增与发布文档&quot;">​</a></h1><p>每篇文档都是一个 Markdown 文件，保存在仓库的 <code>docs/</code> 目录中。</p><h2 id="新建文档" tabindex="-1">新建文档 <a class="header-anchor" href="#新建文档" aria-label="Permalink to &quot;新建文档&quot;">​</a></h2><p>例如，要记录一篇架构设计，可以创建 <code>docs/projects/architecture.md</code>：</p><div class="language-md vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">md</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#005CC5", "--shiki-light-font-weight": "bold", "--shiki-dark": "#79B8FF", "--shiki-dark-font-weight": "bold" })}"># 架构设计</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">简要说明这个项目要解决的问题。</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#005CC5", "--shiki-light-font-weight": "bold", "--shiki-dark": "#79B8FF", "--shiki-dark-font-weight": "bold" })}">## 背景</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">记录业务场景与约束。</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#005CC5", "--shiki-light-font-weight": "bold", "--shiki-dark": "#79B8FF", "--shiki-dark-font-weight": "bold" })}">## 方案</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">说明模块职责、数据流和主要取舍。</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#005CC5", "--shiki-light-font-weight": "bold", "--shiki-dark": "#79B8FF", "--shiki-dark-font-weight": "bold" })}">## 验证</span></span>
<span class="line"></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">记录已经验证的结果，以及尚未验证的部分。</span></span></code></pre></div><p>一级标题作为文章标题，二级和三级标题会出现在右侧页内目录中。</p><div class="tip custom-block"><p class="custom-block-title">写系列教程？</p><p>编写 TinyLLM、Burn、mini-redis 这类多章节课程时，请先阅读<a href="./course-conventions.html">课程写作规范</a>：文件命名、侧栏、章节模板和配图都有统一约定。</p></div><h2 id="加入左侧目录" tabindex="-1">加入左侧目录 <a class="header-anchor" href="#加入左侧目录" aria-label="Permalink to &quot;加入左侧目录&quot;">​</a></h2><p>打开 <code>docs/.vitepress/config.mts</code>，在 <code>themeConfig.sidebar</code> 数组中增加一个分组：</p><div class="language-ts vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">ts</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">{</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">  text</span><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">: </span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}">&#39;项目文档&#39;</span><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">,</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">  items</span><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">: [</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">    { text: </span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}">&#39;架构设计&#39;</span><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">, link: </span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}">&#39;/projects/architecture&#39;</span><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}"> }</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">  ]</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#24292E", "--shiki-dark": "#E1E4E8" })}">}</span></span></code></pre></div><p>目录中的链接相对于 <code>docs/</code>，不需要写 <code>.md</code> 后缀。</p><h2 id="本地预览" tabindex="-1">本地预览 <a class="header-anchor" href="#本地预览" aria-label="Permalink to &quot;本地预览&quot;">​</a></h2><p>在仓库根目录执行：</p><div class="language-sh vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">sh</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">npm</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> ci</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">npm</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> run</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> docs:dev</span></span></code></pre></div><p>打开终端显示的本地地址。修改 Markdown 文件后，预览页面会自动更新。</p><p>发布前可以检查构建结果：</p><div class="language-sh vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">sh</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">npm</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> run</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> docs:build</span></span>
<span class="line"><span style="${ssrRenderStyle({ "--shiki-light": "#6F42C1", "--shiki-dark": "#B392F0" })}">npm</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> run</span><span style="${ssrRenderStyle({ "--shiki-light": "#032F62", "--shiki-dark": "#9ECBFF" })}"> docs:preview</span></span></code></pre></div><h2 id="发布到网站" tabindex="-1">发布到网站 <a class="header-anchor" href="#发布到网站" aria-label="Permalink to &quot;发布到网站&quot;">​</a></h2><p>将修改提交并推送到 <code>master</code> 分支，GitHub Actions 会自动构建并部署网站。可以在仓库的 <strong>Actions</strong> 页面查看部署结果。</p><p>部署成功后，在 <a href="https://lewislau86.github.io/" target="_blank" rel="noreferrer">知识库首页</a> 查看更新。</p><p>也可以点击每页底部的「在 GitHub 上编辑此页」，直接在浏览器里修改并提交文档。</p></div>`);
}
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("guide/writing.md");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const writing = /* @__PURE__ */ _export_sfc(_sfc_main, [["ssrRender", _sfc_ssrRender]]);
export {
  __pageData,
  writing as default
};
