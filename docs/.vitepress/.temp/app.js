import { ssrRenderAttrs, ssrRenderSlot, ssrInterpolate, ssrRenderAttr, ssrRenderList, ssrRenderComponent, ssrRenderVNode, ssrRenderClass, ssrRenderStyle, renderToString } from "vue/server-renderer";
import { defineComponent, mergeProps, useSSRContext, shallowRef, inject, computed, ref, watch, onUnmounted, reactive, markRaw, readonly, nextTick, h, unref, onMounted, watchEffect, watchPostEffect, onUpdated, resolveComponent, createVNode, resolveDynamicComponent, withCtx, renderSlot, createTextVNode, toDisplayString, openBlock, createBlock, createCommentVNode, Fragment, renderList, defineAsyncComponent, provide, toHandlers, withKeys, onBeforeUnmount, useSlots, createSSRApp } from "vue";
import { usePreferredDark, useDark, useMediaQuery, useWindowSize, onKeyStroke, useWindowScroll, useScrollLock } from "@vueuse/core";
import { _ as _export_sfc } from "./plugin-vue_export-helper.1tPrXgE0.js";
const _sfc_main$1h = /* @__PURE__ */ defineComponent({
  __name: "VPBadge",
  __ssrInlineRender: true,
  props: {
    text: {},
    type: { default: "tip" }
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<span${ssrRenderAttrs(mergeProps({
        class: ["VPBadge", __props.type]
      }, _attrs))}>`);
      ssrRenderSlot(_ctx.$slots, "default", {}, () => {
        _push(`${ssrInterpolate(__props.text)}`);
      }, _push, _parent);
      _push(`</span>`);
    };
  }
});
const _sfc_setup$1h = _sfc_main$1h.setup;
_sfc_main$1h.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPBadge.vue");
  return _sfc_setup$1h ? _sfc_setup$1h(props, ctx) : void 0;
};
function deserializeFunctions(r) {
  return Array.isArray(r) ? r.map(deserializeFunctions) : typeof r == "object" && r !== null ? Object.keys(r).reduce((t, n) => (t[n] = deserializeFunctions(r[n]), t), {}) : typeof r == "string" && r.startsWith("_vp-fn_") ? new Function(`return ${r.slice(7)}`)() : r;
}
const siteData = deserializeFunctions(JSON.parse('{"lang":"zh-CN","dir":"ltr","title":"Lewis 的知识库","description":"按主题整理技术研究、项目文档与学习笔记。","base":"/","head":[],"router":{"prefetchLinks":true},"appearance":true,"themeConfig":{"logo":"/favicon.svg","nav":[{"text":"文档","link":"/"},{"text":"TinyLLM","link":"/tinyllm/"},{"text":"mini-redis","link":"/mini-redis/"},{"text":"Burn","link":"/burn/"},{"text":"讨论","link":"/discuss"},{"text":"关于","link":"/about"}],"sidebar":{"/burn/":[{"text":"深入理解 Burn","items":[{"text":"返回知识库","link":"/"},{"text":"课程总览","link":"/burn/"},{"text":"数学预备篇 · 公式与图解","link":"/burn/math-foundations"},{"text":"资料、版本与术语","link":"/burn/references"}]},{"text":"第一部分 · 环境与基础","collapsed":false,"items":[{"text":"第 1 章 · 环境与工具链","link":"/burn/environment"},{"text":"第 2 章 · 从模型到框架","link":"/burn/model-and-framework"},{"text":"第 3 章 · 张量、形状与内存","link":"/burn/tensors-and-memory"},{"text":"第 4 章 · 阅读计算代码所需的 Rust","link":"/burn/rust-basics"}]},{"text":"第二部分 · GPU 与 Rust 计算","collapsed":false,"items":[{"text":"第 5 章 · GPU 编程：从向量加法到矩阵乘法","link":"/burn/gpu-programming"},{"text":"第 6 章 · Rust GPU 编程与 CubeCL","link":"/burn/rust-gpu"}]},{"text":"第三部分 · Burn 模型与后端","collapsed":false,"items":[{"text":"第 7 章 · 把第一次 Burn 推理跑起来","link":"/burn/first-burn-inference"},{"text":"第 8 章 · 模型、参数与 Module","link":"/burn/models-and-modules"},{"text":"第 9 章 · Backend 与执行路径","link":"/burn/backends-and-dispatch"}]},{"text":"第四部分 · 自动微分与训练","collapsed":false,"items":[{"text":"第 10 章 · 自动微分与梯度","link":"/burn/autodiff"},{"text":"第 11 章 · 优化器、训练与推理","link":"/burn/training-to-inference"}]},{"text":"第五部分 · 执行与性能","collapsed":false,"items":[{"text":"第 12 章 · 一次计算怎样执行","link":"/burn/execution"},{"text":"第 13 章 · 融合、内存与性能","link":"/burn/fusion-and-performance"}]},{"text":"第六部分 · 部署与扩展","collapsed":false,"items":[{"text":"第 14 章 · 权重导入与部署","link":"/burn/import-and-deploy"},{"text":"第 15 章 · 后端扩展与自定义算子","link":"/burn/custom-operators"}]},{"text":"第七部分 · 对照、源码与实验","collapsed":false,"items":[{"text":"第 16 章 · 用 PyTorch 对照学习 Burn","link":"/burn/pytorch-comparison"},{"text":"第 17 章 · 源码阅读地图","link":"/burn/source-reading"},{"text":"第 18 章 · 实验索引与后续路线","link":"/burn/learning-labs"}]}],"/tinyllm/":[{"text":"TinyLLM 教程","items":[{"text":"返回知识库","link":"/"},{"text":"课程总览","link":"/tinyllm/"}]},{"text":"快速体验","collapsed":false,"items":[{"text":"实验环境：安装与代码下载","link":"/tinyllm/setup"},{"text":"30 分钟快速体验：把零件逐个打开","link":"/tinyllm/quickstart"}]},{"text":"第一部分 · 先跑起来","collapsed":false,"items":[{"text":"第 1 章 · 先跑通一个最小 TinyLLM","link":"/tinyllm/first-run"}]},{"text":"第二部分 · 背景知识","collapsed":false,"items":[{"text":"第 2 章 · 张量与自动求导","link":"/tinyllm/tensors-and-autograd"},{"text":"第 3 章 · 架构演进：从 Transformer 到 GPT 再到今天","link":"/tinyllm/architecture-evolution"}]},{"text":"第三部分 · 沿数据流搭模型","collapsed":false,"items":[{"text":"第 4 章 · 文本与词元化","link":"/tinyllm/tokenization"},{"text":"第 5 章 · 词嵌入与输出层","link":"/tinyllm/embeddings-and-output"},{"text":"第 6 章 · 自注意力","link":"/tinyllm/self-attention"},{"text":"第 7 章 · 位置表示","link":"/tinyllm/position-encoding"},{"text":"第 8 章 · 激活函数与门控前馈层","link":"/tinyllm/activations-and-ffn"},{"text":"第 9 章 · Transformer Block","link":"/tinyllm/transformer-block"}]},{"text":"第四部分 · 让深层网络训得动","collapsed":false,"items":[{"text":"第 10 章 · 初始化与残差路径","link":"/tinyllm/initialization-and-residuals"},{"text":"第 11 章 · 归一化","link":"/tinyllm/normalization"},{"text":"第 12 章 · 完整 TinyLLM","link":"/tinyllm/tinyllm-model"},{"text":"第 13 章 · TinyLLM 在 GPU 上完整实现","link":"/tinyllm/gpu-training"}]},{"text":"第五部分 · 数据与训练","collapsed":false,"items":[{"text":"第 14 章 · 语料与数据管线","link":"/tinyllm/data-pipeline"},{"text":"第 15 章 · 语言模型目标函数","link":"/tinyllm/language-model-loss"},{"text":"第 16 章 · 优化器","link":"/tinyllm/optimizers"},{"text":"第 17 章 · 学习率策略","link":"/tinyllm/learning-rate"},{"text":"第 18 章 · 正则化与泛化","link":"/tinyllm/regularization"},{"text":"第 19 章 · 数值精度与混合精度","link":"/tinyllm/precision"}]},{"text":"第六部分 · 推理","collapsed":false,"items":[{"text":"第 25 章 · 自回归生成","link":"/tinyllm/generation"},{"text":"第 26 章 · 推理效率：prefill、decode 与 KV cache","link":"/tinyllm/inference-efficiency"}]},{"text":"规划中（尚未成文）","collapsed":true,"items":[{"text":"第 20 章 · 梯度稳定与累积","link":"/tinyllm/gradient-stability"},{"text":"第 21 章 · 训练循环与检查点","link":"/tinyllm/training-loop"},{"text":"第 22 章 · 训练诊断与评估","link":"/tinyllm/training-evaluation"},{"text":"第 23 章 · 大规模训练稳定性","link":"/tinyllm/large-model-stability"},{"text":"第 24 章 · 稀疏专家（MoE）","link":"/tinyllm/mixture-of-experts"},{"text":"第 27 章 · 注意力内核与算子融合","link":"/tinyllm/attention-kernels"},{"text":"第 28 章 · 量化","link":"/tinyllm/quantization"},{"text":"第 29 章 · 投机解码","link":"/tinyllm/speculative-decoding"},{"text":"第 30 章 · 批处理与调度","link":"/tinyllm/batching"},{"text":"第 31 章 · KV 显存管理：分页与前缀缓存","link":"/tinyllm/kv-memory"},{"text":"第 32 章 · 推理优化：逐项对照与推理服务","link":"/tinyllm/inference-optimization"},{"text":"第 33 章 · 指令微调","link":"/tinyllm/instruction-finetuning"},{"text":"第 34 章 · 参数高效微调（LoRA）","link":"/tinyllm/lora-finetuning"},{"text":"第 35 章 · RLHF：奖励模型与 PPO","link":"/tinyllm/rlhf"},{"text":"第 36 章 · DPO 与 GRPO","link":"/tinyllm/preference-alignment"},{"text":"第 37 章 · Agent 记忆与检索","link":"/tinyllm/agent-memory"}]}],"/mini-redis/source/":[{"text":"mini-redis 逐文件分析","items":[{"text":"返回教程总览","link":"/mini-redis/"},{"text":"源码阅读索引","link":"/mini-redis/source/"},{"text":"Rust 源码阅读说明","link":"/mini-redis/rust-reading-guide"}]},{"text":"入口与模块边界","collapsed":false,"items":[{"text":"src/lib.rs","link":"/mini-redis/source/src/lib"},{"text":"src/bin/server.rs","link":"/mini-redis/source/src/bin/server"},{"text":"src/bin/cli.rs","link":"/mini-redis/source/src/bin/cli"},{"text":"src/clients/mod.rs","link":"/mini-redis/source/src/clients/mod"}]},{"text":"连接、协议与服务任务","collapsed":false,"items":[{"text":"src/server.rs","link":"/mini-redis/source/src/server"},{"text":"src/connection.rs","link":"/mini-redis/source/src/connection"},{"text":"src/frame.rs","link":"/mini-redis/source/src/frame"},{"text":"src/parse.rs","link":"/mini-redis/source/src/parse"},{"text":"src/shutdown.rs","link":"/mini-redis/source/src/shutdown"}]},{"text":"命令与共享存储","collapsed":false,"items":[{"text":"src/cmd/mod.rs","link":"/mini-redis/source/src/cmd/mod"},{"text":"src/cmd/set.rs","link":"/mini-redis/source/src/cmd/set"},{"text":"src/cmd/get.rs","link":"/mini-redis/source/src/cmd/get"},{"text":"src/db.rs","link":"/mini-redis/source/src/db"},{"text":"src/cmd/ping.rs","link":"/mini-redis/source/src/cmd/ping"},{"text":"src/cmd/publish.rs","link":"/mini-redis/source/src/cmd/publish"},{"text":"src/cmd/subscribe.rs","link":"/mini-redis/source/src/cmd/subscribe"},{"text":"src/cmd/unknown.rs","link":"/mini-redis/source/src/cmd/unknown"}]},{"text":"客户端形态","collapsed":false,"items":[{"text":"src/clients/client.rs","link":"/mini-redis/source/src/clients/client"},{"text":"src/clients/buffered_client.rs","link":"/mini-redis/source/src/clients/buffered_client"},{"text":"src/clients/blocking_client.rs","link":"/mini-redis/source/src/clients/blocking_client"}]},{"text":"应用示例","collapsed":false,"items":[{"text":"examples/hello_world.rs","link":"/mini-redis/source/examples/hello_world"},{"text":"examples/pub.rs","link":"/mini-redis/source/examples/pub"},{"text":"examples/sub.rs","link":"/mini-redis/source/examples/sub"},{"text":"examples/chat.rs","link":"/mini-redis/source/examples/chat"}]},{"text":"测试如何提供证据","collapsed":false,"items":[{"text":"tests/client.rs","link":"/mini-redis/source/tests/client"},{"text":"tests/server.rs","link":"/mini-redis/source/tests/server"},{"text":"tests/buffered_client.rs","link":"/mini-redis/source/tests/buffered_client"},{"text":"tests/frame_validation.rs","link":"/mini-redis/source/tests/frame_validation"}]}],"/mini-redis/":[{"text":"mini-redis 源码分析","items":[{"text":"返回知识库","link":"/"},{"text":"课程总览与下载","link":"/mini-redis/"},{"text":"按源码文件阅读","link":"/mini-redis/source/"},{"text":"Rust 源码阅读说明","link":"/mini-redis/rust-reading-guide"}]},{"text":"第一部分 · 整体架构","collapsed":false,"items":[{"text":"第 0 章 · 整体架构：代码职责、连接通信与后续优化","link":"/mini-redis/architecture"}]},{"text":"第二部分 · 入门与请求链路","collapsed":false,"items":[{"text":"第 1 章 · 跑通第一条请求","link":"/mini-redis/first-run"},{"text":"第 2 章 · 用所有权管理一份数据","link":"/mini-redis/rust-foundations"},{"text":"第 3 章 · 沿着 SET/GET 走一遍","link":"/mini-redis/request-path"},{"text":"第 4 章 · TCP 字节如何变成帧","link":"/mini-redis/resp-and-connection"}]},{"text":"第三部分 · 并发、存储与生命周期","collapsed":false,"items":[{"text":"第 5 章 · 为什么服务器能同时服务多人","link":"/mini-redis/tokio-server"},{"text":"第 6 章 · 数据如何安全地共享","link":"/mini-redis/shared-storage"},{"text":"第 7 章 · 到期的数据由谁删除","link":"/mini-redis/expiration"},{"text":"第 8 章 · 发布订阅为什么改变连接状态","link":"/mini-redis/pubsub"},{"text":"第 9 章 · 客户端为什么有三种形态","link":"/mini-redis/clients"},{"text":"第 10 章 · 如何停机与验证行为","link":"/mini-redis/shutdown-and-tests"}]},{"text":"第四部分 · 架构与实践","collapsed":false,"items":[{"text":"第 11 章 · 从教学服务器走向 Redis","link":"/mini-redis/real-redis"},{"text":"第 12 章 · 动手练习与知识索引","link":"/mini-redis/exercises-and-index"},{"text":"第 13 章 · 一条 TTL 测试为什么会一直等待","link":"/mini-redis/ttl-test-debugging"}]},{"text":"配套资料","collapsed":false,"items":[{"text":"配套实验","link":"/mini-redis/labs/"},{"text":"原始验证记录","link":"/mini-redis/validation"}]}],"/":[{"text":"知识库","items":[{"text":"文档首页","link":"/"},{"text":"TinyLLM 教程","link":"/tinyllm/"},{"text":"mini-redis 源码分析","link":"/mini-redis/"},{"text":"深入理解 Burn","link":"/burn/"},{"text":"关于","link":"/about"}]},{"text":"使用指南","collapsed":false,"items":[{"text":"新增与发布文档","link":"/guide/writing"},{"text":"课程写作规范","link":"/guide/course-conventions"},{"text":"Markdown 写作示例","link":"/guide/markdown"}]}]},"notFound":{"title":"文档未找到","quote":"这篇文档可能已移动或尚未创建，请返回首页查找。","linkLabel":"返回文档首页","linkText":"返回文档首页"},"outline":{"level":[2,3],"label":"本页目录"},"docFooter":{"prev":"上一篇","next":"下一篇"},"sidebarMenuLabel":"文档目录","returnToTopLabel":"返回顶部","darkModeSwitchLabel":"外观","lightModeSwitchTitle":"切换为浅色模式","darkModeSwitchTitle":"切换为深色模式","skipToContentLabel":"跳转到正文","editLink":{"pattern":"https://github.com/lewislau86/lewislau86.github.io/edit/master/docs/:path","text":"在 GitHub 上编辑此页"},"socialLinks":[{"icon":"github","link":"https://github.com/lewislau86/lewislau86.github.io"}],"search":{"provider":"local","options":{"miniSearch":{"options":{"tokenize":"_vp-fn_(text) => {\\n              const tokens = [];\\n              if (typeof text !== \\"string\\" || text.length === 0) return tokens;\\n              const parts = text.toLowerCase().match(/[\\\\p{Script=Han}]+|\\\\d+(?:\\\\.\\\\d+)+|[a-z0-9_]+/gu) ?? [];\\n              for (const part of parts) {\\n                if (!new RegExp(\\"^\\\\\\\\p{Script=Han}\\", \\"u\\").test(part)) {\\n                  tokens.push(part);\\n                  continue;\\n                }\\n                const chars = Array.from(part);\\n                if (chars.length === 1) {\\n                  tokens.push(chars[0]);\\n                  continue;\\n                }\\n                for (let i = 0; i < chars.length - 1; i++) {\\n                  tokens.push(chars[i] + chars[i + 1]);\\n                }\\n              }\\n              return tokens;\\n            }"}},"locales":{"root":{"translations":{"button":{"buttonText":"搜索文档","buttonAriaLabel":"搜索文档"},"modal":{"displayDetails":"显示详细内容","resetButtonTitle":"清除搜索","backButtonTitle":"关闭搜索","noResultsText":"没有找到相关内容","footer":{"selectText":"选择","navigateText":"切换","closeText":"关闭"}}}}}}}},"locales":{},"scrollOffset":134,"cleanUrls":false}'));
const __vite_import_meta_env__ = {};
const EXTERNAL_URL_RE = /^(?:[a-z]+:|\/\/)/i;
const APPEARANCE_KEY = "vitepress-theme-appearance";
const HASH_RE = /#.*$/;
const HASH_OR_QUERY_RE = /[?#].*$/;
const INDEX_OR_EXT_RE = /(?:(^|\/)index)?\.(?:md|html)$/;
const inBrowser = typeof document !== "undefined";
const notFoundPageData = {
  relativePath: "404.md",
  filePath: "",
  title: "404",
  description: "Not Found",
  headers: [],
  frontmatter: { sidebar: false, layout: "page" },
  lastUpdated: 0,
  isNotFound: true
};
function isActive(currentPath, matchPath, asRegex = false) {
  if (matchPath === void 0) {
    return false;
  }
  currentPath = normalize(`/${currentPath}`);
  if (asRegex) {
    return new RegExp(matchPath).test(currentPath);
  }
  if (normalize(matchPath) !== currentPath) {
    return false;
  }
  const hashMatch = matchPath.match(HASH_RE);
  if (hashMatch) {
    return (inBrowser ? location.hash : "") === hashMatch[0];
  }
  return true;
}
function normalize(path) {
  return decodeURI(path).replace(HASH_OR_QUERY_RE, "").replace(INDEX_OR_EXT_RE, "$1");
}
function isExternal(path) {
  return EXTERNAL_URL_RE.test(path);
}
function getLocaleForPath(siteData2, relativePath) {
  return Object.keys((siteData2 == null ? void 0 : siteData2.locales) || {}).find((key) => key !== "root" && !isExternal(key) && isActive(relativePath, `/${key}/`, true)) || "root";
}
function resolveSiteDataByRoute(siteData2, relativePath) {
  var _a, _b, _c, _d, _e, _f, _g;
  const localeIndex = getLocaleForPath(siteData2, relativePath);
  return Object.assign({}, siteData2, {
    localeIndex,
    lang: ((_a = siteData2.locales[localeIndex]) == null ? void 0 : _a.lang) ?? siteData2.lang,
    dir: ((_b = siteData2.locales[localeIndex]) == null ? void 0 : _b.dir) ?? siteData2.dir,
    title: ((_c = siteData2.locales[localeIndex]) == null ? void 0 : _c.title) ?? siteData2.title,
    titleTemplate: ((_d = siteData2.locales[localeIndex]) == null ? void 0 : _d.titleTemplate) ?? siteData2.titleTemplate,
    description: ((_e = siteData2.locales[localeIndex]) == null ? void 0 : _e.description) ?? siteData2.description,
    head: mergeHead(siteData2.head, ((_f = siteData2.locales[localeIndex]) == null ? void 0 : _f.head) ?? []),
    themeConfig: {
      ...siteData2.themeConfig,
      ...(_g = siteData2.locales[localeIndex]) == null ? void 0 : _g.themeConfig
    }
  });
}
function createTitle(siteData2, pageData) {
  const title = pageData.title || siteData2.title;
  const template = pageData.titleTemplate ?? siteData2.titleTemplate;
  if (typeof template === "string" && template.includes(":title")) {
    return template.replace(/:title/g, title);
  }
  const templateString = createTitleTemplate(siteData2.title, template);
  if (title === templateString.slice(3)) {
    return title;
  }
  return `${title}${templateString}`;
}
function createTitleTemplate(siteTitle, template) {
  if (template === false) {
    return "";
  }
  if (template === true || template === void 0) {
    return ` | ${siteTitle}`;
  }
  if (siteTitle === template) {
    return "";
  }
  return ` | ${template}`;
}
function hasTag(head, tag) {
  const [tagType, tagAttrs] = tag;
  if (tagType !== "meta")
    return false;
  const keyAttr = Object.entries(tagAttrs)[0];
  if (keyAttr == null)
    return false;
  return head.some(([type, attrs]) => type === tagType && attrs[keyAttr[0]] === keyAttr[1]);
}
function mergeHead(prev, curr) {
  return [...prev.filter((tagAttrs) => !hasTag(curr, tagAttrs)), ...curr];
}
const INVALID_CHAR_REGEX = /[\u0000-\u001F"#$&*+,:;<=>?[\]^`{|}\u007F]/g;
const DRIVE_LETTER_REGEX = /^[a-z]:/i;
function sanitizeFileName(name) {
  const match = DRIVE_LETTER_REGEX.exec(name);
  const driveLetter = match ? match[0] : "";
  return driveLetter + name.slice(driveLetter.length).replace(INVALID_CHAR_REGEX, "_").replace(/(^|\/)_+(?=[^/]*$)/, "$1");
}
const KNOWN_EXTENSIONS = /* @__PURE__ */ new Set();
function treatAsHtml(filename) {
  var _a;
  if (KNOWN_EXTENSIONS.size === 0) {
    const extraExts = typeof process === "object" && ((_a = process.env) == null ? void 0 : _a.VITE_EXTRA_EXTENSIONS) || (__vite_import_meta_env__ == null ? void 0 : __vite_import_meta_env__.VITE_EXTRA_EXTENSIONS) || "";
    ("3g2,3gp,aac,ai,apng,au,avif,bin,bmp,cer,class,conf,crl,css,csv,dll,doc,eps,epub,exe,gif,gz,ics,ief,jar,jpe,jpeg,jpg,js,json,jsonld,m4a,man,mid,midi,mjs,mov,mp2,mp3,mp4,mpe,mpeg,mpg,mpp,oga,ogg,ogv,ogx,opus,otf,p10,p7c,p7m,p7s,pdf,png,ps,qt,roff,rtf,rtx,ser,svg,t,tif,tiff,tr,ts,tsv,ttf,txt,vtt,wav,weba,webm,webp,woff,woff2,xhtml,xml,yaml,yml,zip" + (extraExts && typeof extraExts === "string" ? "," + extraExts : "")).split(",").forEach((ext2) => KNOWN_EXTENSIONS.add(ext2));
  }
  const ext = filename.split(".").pop();
  return ext == null || !KNOWN_EXTENSIONS.has(ext.toLowerCase());
}
function escapeRegExp(str) {
  return str.replace(/[|\\{}()[\]^$+*?.]/g, "\\$&").replace(/-/g, "\\x2d");
}
const dataSymbol = Symbol();
const siteDataRef = shallowRef(siteData);
function initData(route) {
  const site = computed(() => resolveSiteDataByRoute(siteDataRef.value, route.data.relativePath));
  const appearance = site.value.appearance;
  const isDark = appearance === "force-dark" ? ref(true) : appearance === "force-auto" ? usePreferredDark() : appearance ? useDark({
    storageKey: APPEARANCE_KEY,
    initialValue: () => appearance === "dark" ? "dark" : "auto",
    ...typeof appearance === "object" ? appearance : {}
  }) : ref(false);
  const hashRef = ref(inBrowser ? location.hash : "");
  if (inBrowser) {
    window.addEventListener("hashchange", () => {
      hashRef.value = location.hash;
    });
  }
  watch(() => route.data, () => {
    hashRef.value = inBrowser ? location.hash : "";
  });
  return {
    site,
    theme: computed(() => site.value.themeConfig),
    page: computed(() => route.data),
    frontmatter: computed(() => route.data.frontmatter),
    params: computed(() => route.data.params),
    lang: computed(() => site.value.lang),
    dir: computed(() => route.data.frontmatter.dir || site.value.dir),
    localeIndex: computed(() => site.value.localeIndex || "root"),
    title: computed(() => createTitle(site.value, route.data)),
    description: computed(() => route.data.description || site.value.description),
    isDark,
    hash: computed(() => hashRef.value)
  };
}
function useData$1() {
  const data = inject(dataSymbol);
  if (!data) {
    throw new Error("vitepress data not properly injected in app");
  }
  return data;
}
function joinPath(base2, path) {
  return `${base2}${path}`.replace(/\/+/g, "/");
}
function withBase(path) {
  return EXTERNAL_URL_RE.test(path) || !path.startsWith("/") ? path : joinPath(siteDataRef.value.base, path);
}
function pathToFile(path) {
  let pagePath = path.replace(/\.html$/, "");
  pagePath = decodeURIComponent(pagePath);
  pagePath = pagePath.replace(/\/$/, "/index");
  {
    if (inBrowser) {
      const base2 = "/";
      pagePath = sanitizeFileName(pagePath.slice(base2.length).replace(/\//g, "_") || "index") + ".md";
      let pageHash = __VP_HASH_MAP__[pagePath.toLowerCase()];
      if (!pageHash) {
        pagePath = pagePath.endsWith("_index.md") ? pagePath.slice(0, -9) + ".md" : pagePath.slice(0, -3) + "_index.md";
        pageHash = __VP_HASH_MAP__[pagePath.toLowerCase()];
      }
      if (!pageHash)
        return null;
      pagePath = `${base2}${"assets"}/${pagePath}.${pageHash}.js`;
    } else {
      pagePath = `./${sanitizeFileName(pagePath.slice(1).replace(/\//g, "_"))}.md.js`;
    }
  }
  return pagePath;
}
let contentUpdatedCallbacks = [];
function onContentUpdated(fn) {
  contentUpdatedCallbacks.push(fn);
  onUnmounted(() => {
    contentUpdatedCallbacks = contentUpdatedCallbacks.filter((f) => f !== fn);
  });
}
function getScrollOffset() {
  let scrollOffset = siteDataRef.value.scrollOffset;
  let offset = 0;
  let padding = 24;
  if (typeof scrollOffset === "object" && "padding" in scrollOffset) {
    padding = scrollOffset.padding;
    scrollOffset = scrollOffset.selector;
  }
  if (typeof scrollOffset === "number") {
    offset = scrollOffset;
  } else if (typeof scrollOffset === "string") {
    offset = tryOffsetSelector(scrollOffset, padding);
  } else if (Array.isArray(scrollOffset)) {
    for (const selector of scrollOffset) {
      const res = tryOffsetSelector(selector, padding);
      if (res) {
        offset = res;
        break;
      }
    }
  }
  return offset;
}
function tryOffsetSelector(selector, padding) {
  const el = document.querySelector(selector);
  if (!el)
    return 0;
  const bot = el.getBoundingClientRect().bottom;
  if (bot < 0)
    return 0;
  return bot + padding;
}
const RouterSymbol = Symbol();
const fakeHost = "http://a.com";
const getDefaultRoute = () => ({
  path: "/",
  component: null,
  data: notFoundPageData
});
function createRouter(loadPageModule, fallbackComponent) {
  const route = reactive(getDefaultRoute());
  const router = {
    route,
    go
  };
  async function go(href = inBrowser ? location.href : "/") {
    var _a, _b;
    href = normalizeHref(href);
    if (await ((_a = router.onBeforeRouteChange) == null ? void 0 : _a.call(router, href)) === false)
      return;
    if (inBrowser && href !== normalizeHref(location.href)) {
      history.replaceState({ scrollPosition: window.scrollY }, "");
      history.pushState({}, "", href);
    }
    await loadPage(href);
    await ((_b = router.onAfterRouteChange ?? router.onAfterRouteChanged) == null ? void 0 : _b(href));
  }
  let latestPendingPath = null;
  async function loadPage(href, scrollPosition = 0, isRetry = false) {
    var _a, _b;
    if (await ((_a = router.onBeforePageLoad) == null ? void 0 : _a.call(router, href)) === false)
      return;
    const targetLoc = new URL(href, fakeHost);
    const pendingPath = latestPendingPath = targetLoc.pathname;
    try {
      let page = await loadPageModule(pendingPath);
      if (!page) {
        throw new Error(`Page not found: ${pendingPath}`);
      }
      if (latestPendingPath === pendingPath) {
        latestPendingPath = null;
        const { default: comp, __pageData } = page;
        if (!comp) {
          throw new Error(`Invalid route component: ${comp}`);
        }
        await ((_b = router.onAfterPageLoad) == null ? void 0 : _b.call(router, href));
        route.path = inBrowser ? pendingPath : withBase(pendingPath);
        route.component = markRaw(comp);
        route.data = true ? markRaw(__pageData) : readonly(__pageData);
        if (inBrowser) {
          nextTick(() => {
            let actualPathname = siteDataRef.value.base + __pageData.relativePath.replace(/(?:(^|\/)index)?\.md$/, "$1");
            if (!siteDataRef.value.cleanUrls && !actualPathname.endsWith("/")) {
              actualPathname += ".html";
            }
            if (actualPathname !== targetLoc.pathname) {
              targetLoc.pathname = actualPathname;
              href = actualPathname + targetLoc.search + targetLoc.hash;
              history.replaceState({}, "", href);
            }
            if (targetLoc.hash && !scrollPosition) {
              let target2 = null;
              try {
                target2 = document.getElementById(decodeURIComponent(targetLoc.hash).slice(1));
              } catch (e) {
                console.warn(e);
              }
              if (target2) {
                scrollTo(target2, targetLoc.hash);
                return;
              }
            }
            window.scrollTo(0, scrollPosition);
          });
        }
      }
    } catch (err) {
      if (!/fetch|Page not found/.test(err.message) && !/^\/404(\.html|\/)?$/.test(href)) {
        console.error(err);
      }
      if (!isRetry) {
        try {
          const res = await fetch(siteDataRef.value.base + "hashmap.json");
          window.__VP_HASH_MAP__ = await res.json();
          await loadPage(href, scrollPosition, true);
          return;
        } catch (e) {
        }
      }
      if (latestPendingPath === pendingPath) {
        latestPendingPath = null;
        route.path = inBrowser ? pendingPath : withBase(pendingPath);
        route.component = fallbackComponent ? markRaw(fallbackComponent) : null;
        const relativePath = inBrowser ? pendingPath.replace(/(^|\/)$/, "$1index").replace(/(\.html)?$/, ".md").replace(/^\//, "") : "404.md";
        route.data = { ...notFoundPageData, relativePath };
      }
    }
  }
  if (inBrowser) {
    if (history.state === null) {
      history.replaceState({}, "");
    }
    window.addEventListener("click", (e) => {
      if (e.defaultPrevented || !(e.target instanceof Element) || e.target.closest("button") || // temporary fix for docsearch action buttons
      e.button !== 0 || e.ctrlKey || e.shiftKey || e.altKey || e.metaKey)
        return;
      const link2 = e.target.closest("a");
      if (!link2 || link2.closest(".vp-raw") || link2.hasAttribute("download") || link2.hasAttribute("target"))
        return;
      const linkHref = link2.getAttribute("href") ?? (link2 instanceof SVGAElement ? link2.getAttribute("xlink:href") : null);
      if (linkHref == null)
        return;
      const { href, origin, pathname, hash, search } = new URL(linkHref, link2.baseURI);
      const currentUrl = new URL(location.href);
      if (origin === currentUrl.origin && treatAsHtml(pathname)) {
        e.preventDefault();
        if (pathname === currentUrl.pathname && search === currentUrl.search) {
          if (hash !== currentUrl.hash) {
            history.pushState({}, "", href);
            window.dispatchEvent(new HashChangeEvent("hashchange", {
              oldURL: currentUrl.href,
              newURL: href
            }));
          }
          if (hash) {
            scrollTo(link2, hash, link2.classList.contains("header-anchor"));
          } else {
            window.scrollTo(0, 0);
          }
        } else {
          go(href);
        }
      }
    }, { capture: true });
    window.addEventListener("popstate", async (e) => {
      var _a;
      if (e.state === null)
        return;
      const href = normalizeHref(location.href);
      await loadPage(href, e.state && e.state.scrollPosition || 0);
      await ((_a = router.onAfterRouteChange ?? router.onAfterRouteChanged) == null ? void 0 : _a(href));
    });
    window.addEventListener("hashchange", (e) => {
      e.preventDefault();
    });
  }
  return router;
}
function useRouter() {
  const router = inject(RouterSymbol);
  if (!router) {
    throw new Error("useRouter() is called without provider.");
  }
  return router;
}
function useRoute() {
  return useRouter().route;
}
function scrollTo(el, hash, smooth = false) {
  let target2 = null;
  try {
    target2 = el.classList.contains("header-anchor") ? el : document.getElementById(decodeURIComponent(hash).slice(1));
  } catch (e) {
    console.warn(e);
  }
  if (target2) {
    let scrollToTarget = function() {
      if (!smooth || Math.abs(targetTop - window.scrollY) > window.innerHeight)
        window.scrollTo(0, targetTop);
      else
        window.scrollTo({ left: 0, top: targetTop, behavior: "smooth" });
    };
    const targetPadding = parseInt(window.getComputedStyle(target2).paddingTop, 10);
    const targetTop = window.scrollY + target2.getBoundingClientRect().top - getScrollOffset() + targetPadding;
    requestAnimationFrame(scrollToTarget);
  }
}
function normalizeHref(href) {
  const url = new URL(href, fakeHost);
  url.pathname = url.pathname.replace(/(^|\/)index(\.html)?$/, "$1");
  if (siteDataRef.value.cleanUrls)
    url.pathname = url.pathname.replace(/\.html$/, "");
  else if (!url.pathname.endsWith("/") && !url.pathname.endsWith(".html"))
    url.pathname += ".html";
  return url.pathname + url.search + url.hash;
}
const runCbs = () => contentUpdatedCallbacks.forEach((fn) => fn());
const Content = defineComponent({
  name: "VitePressContent",
  props: {
    as: { type: [Object, String], default: "div" }
  },
  setup(props) {
    const route = useRoute();
    const { frontmatter, site } = useData$1();
    watch(frontmatter, runCbs, { deep: true, flush: "post" });
    return () => h(props.as, site.value.contentProps ?? { style: { position: "relative" } }, [
      route.component ? h(route.component, {
        onVnodeMounted: runCbs,
        onVnodeUpdated: runCbs,
        onVnodeUnmounted: runCbs
      }) : "404 Page Not Found"
    ]);
  }
});
const _sfc_main$1g = /* @__PURE__ */ defineComponent({
  __name: "VPBackdrop",
  __ssrInlineRender: true,
  props: {
    show: { type: Boolean }
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      if (__props.show) {
        _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPBackdrop" }, _attrs))} data-v-c79a1216></div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$1g = _sfc_main$1g.setup;
_sfc_main$1g.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPBackdrop.vue");
  return _sfc_setup$1g ? _sfc_setup$1g(props, ctx) : void 0;
};
const VPBackdrop = /* @__PURE__ */ _export_sfc(_sfc_main$1g, [["__scopeId", "data-v-c79a1216"]]);
const useData = useData$1;
function throttleAndDebounce(fn, delay) {
  let timeoutId;
  let called = false;
  return () => {
    if (timeoutId)
      clearTimeout(timeoutId);
    if (!called) {
      fn();
      (called = true) && setTimeout(() => called = false, delay);
    } else
      timeoutId = setTimeout(fn, delay);
  };
}
function ensureStartingSlash(path) {
  return path.startsWith("/") ? path : `/${path}`;
}
function normalizeLink$1(url) {
  const { pathname, search, hash, protocol } = new URL(url, "http://a.com");
  if (isExternal(url) || url.startsWith("#") || !protocol.startsWith("http") || !treatAsHtml(pathname))
    return url;
  const { site } = useData();
  const normalizedPath = pathname.endsWith("/") || pathname.endsWith(".html") ? url : url.replace(/(?:(^\.+)\/)?.*$/, `$1${pathname.replace(/(\.md)?$/, site.value.cleanUrls ? "" : ".html")}${search}${hash}`);
  return withBase(normalizedPath);
}
function useLangs({ correspondingLink = false } = {}) {
  const { site, localeIndex, page, theme: theme2, hash } = useData();
  const currentLang = computed(() => {
    var _a, _b;
    return {
      label: (_a = site.value.locales[localeIndex.value]) == null ? void 0 : _a.label,
      link: ((_b = site.value.locales[localeIndex.value]) == null ? void 0 : _b.link) || (localeIndex.value === "root" ? "/" : `/${localeIndex.value}/`)
    };
  });
  const localeLinks = computed(() => Object.entries(site.value.locales).flatMap(([key, value]) => currentLang.value.label === value.label ? [] : {
    text: value.label,
    link: normalizeLink(value.link || (key === "root" ? "/" : `/${key}/`), theme2.value.i18nRouting !== false && correspondingLink, page.value.relativePath.slice(currentLang.value.link.length - 1), !site.value.cleanUrls) + hash.value
  }));
  return { localeLinks, currentLang };
}
function normalizeLink(link2, addPath, path, addExt) {
  return addPath ? link2.replace(/\/$/, "") + ensureStartingSlash(path.replace(/(^|\/)index\.md$/, "$1").replace(/\.md$/, addExt ? ".html" : "")) : link2;
}
const _sfc_main$1f = /* @__PURE__ */ defineComponent({
  __name: "NotFound",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    const { currentLang } = useLangs();
    return (_ctx, _push, _parent, _attrs) => {
      var _a, _b, _c, _d, _e;
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "NotFound" }, _attrs))} data-v-d6be1790><p class="code" data-v-d6be1790>${ssrInterpolate(((_a = unref(theme2).notFound) == null ? void 0 : _a.code) ?? "404")}</p><h1 class="title" data-v-d6be1790>${ssrInterpolate(((_b = unref(theme2).notFound) == null ? void 0 : _b.title) ?? "PAGE NOT FOUND")}</h1><div class="divider" data-v-d6be1790></div><blockquote class="quote" data-v-d6be1790>${ssrInterpolate(((_c = unref(theme2).notFound) == null ? void 0 : _c.quote) ?? "But if you don't change your direction, and if you keep looking, you may end up where you are heading.")}</blockquote><div class="action" data-v-d6be1790><a class="link"${ssrRenderAttr("href", unref(withBase)(unref(currentLang).link))}${ssrRenderAttr("aria-label", ((_d = unref(theme2).notFound) == null ? void 0 : _d.linkLabel) ?? "go to home")} data-v-d6be1790>${ssrInterpolate(((_e = unref(theme2).notFound) == null ? void 0 : _e.linkText) ?? "Take me home")}</a></div></div>`);
    };
  }
});
const _sfc_setup$1f = _sfc_main$1f.setup;
_sfc_main$1f.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/NotFound.vue");
  return _sfc_setup$1f ? _sfc_setup$1f(props, ctx) : void 0;
};
const NotFound = /* @__PURE__ */ _export_sfc(_sfc_main$1f, [["__scopeId", "data-v-d6be1790"]]);
function getSidebar(_sidebar, path) {
  if (Array.isArray(_sidebar))
    return addBase(_sidebar);
  if (_sidebar == null)
    return [];
  path = ensureStartingSlash(path);
  const dir = Object.keys(_sidebar).sort((a, b) => {
    return b.split("/").length - a.split("/").length;
  }).find((dir2) => {
    return path.startsWith(ensureStartingSlash(dir2));
  });
  const sidebar = dir ? _sidebar[dir] : [];
  return Array.isArray(sidebar) ? addBase(sidebar) : addBase(sidebar.items, sidebar.base);
}
function getSidebarGroups(sidebar) {
  const groups = [];
  let lastGroupIndex = 0;
  for (const index in sidebar) {
    const item = sidebar[index];
    if (item.items) {
      lastGroupIndex = groups.push(item);
      continue;
    }
    if (!groups[lastGroupIndex]) {
      groups.push({ items: [] });
    }
    groups[lastGroupIndex].items.push(item);
  }
  return groups;
}
function getFlatSideBarLinks(sidebar) {
  const links = [];
  function recursivelyExtractLinks(items) {
    for (const item of items) {
      if (item.text && item.link) {
        links.push({
          text: item.text,
          link: item.link,
          docFooterText: item.docFooterText
        });
      }
      if (item.items) {
        recursivelyExtractLinks(item.items);
      }
    }
  }
  recursivelyExtractLinks(sidebar);
  return links;
}
function hasActiveLink(path, items) {
  if (Array.isArray(items)) {
    return items.some((item) => hasActiveLink(path, item));
  }
  return isActive(path, items.link) ? true : items.items ? hasActiveLink(path, items.items) : false;
}
function addBase(items, _base) {
  return [...items].map((_item) => {
    const item = { ..._item };
    const base2 = item.base || _base;
    if (base2 && item.link)
      item.link = base2 + item.link;
    if (item.items)
      item.items = addBase(item.items, base2);
    return item;
  });
}
function useSidebar() {
  const { frontmatter, page, theme: theme2 } = useData();
  const is960 = useMediaQuery("(min-width: 960px)");
  const isOpen = ref(false);
  const _sidebar = computed(() => {
    const sidebarConfig = theme2.value.sidebar;
    const relativePath = page.value.relativePath;
    return sidebarConfig ? getSidebar(sidebarConfig, relativePath) : [];
  });
  const sidebar = ref(_sidebar.value);
  watch(_sidebar, (next, prev) => {
    if (JSON.stringify(next) !== JSON.stringify(prev))
      sidebar.value = _sidebar.value;
  });
  const hasSidebar = computed(() => {
    return frontmatter.value.sidebar !== false && sidebar.value.length > 0 && frontmatter.value.layout !== "home";
  });
  const leftAside = computed(() => {
    if (hasAside)
      return frontmatter.value.aside == null ? theme2.value.aside === "left" : frontmatter.value.aside === "left";
    return false;
  });
  const hasAside = computed(() => {
    if (frontmatter.value.layout === "home")
      return false;
    if (frontmatter.value.aside != null)
      return !!frontmatter.value.aside;
    return theme2.value.aside !== false;
  });
  const isSidebarEnabled = computed(() => hasSidebar.value && is960.value);
  const sidebarGroups = computed(() => {
    return hasSidebar.value ? getSidebarGroups(sidebar.value) : [];
  });
  function open() {
    isOpen.value = true;
  }
  function close() {
    isOpen.value = false;
  }
  function toggle() {
    isOpen.value ? close() : open();
  }
  return {
    isOpen,
    sidebar,
    sidebarGroups,
    hasSidebar,
    hasAside,
    leftAside,
    isSidebarEnabled,
    open,
    close,
    toggle
  };
}
function useCloseSidebarOnEscape(isOpen, close) {
  let triggerElement;
  watchEffect(() => {
    triggerElement = isOpen.value ? document.activeElement : void 0;
  });
  onMounted(() => {
    window.addEventListener("keyup", onEscape);
  });
  onUnmounted(() => {
    window.removeEventListener("keyup", onEscape);
  });
  function onEscape(e) {
    if (e.key === "Escape" && isOpen.value) {
      close();
      triggerElement == null ? void 0 : triggerElement.focus();
    }
  }
}
function useSidebarControl(item) {
  const { page, hash } = useData();
  const collapsed = ref(false);
  const collapsible = computed(() => {
    return item.value.collapsed != null;
  });
  const isLink = computed(() => {
    return !!item.value.link;
  });
  const isActiveLink = ref(false);
  const updateIsActiveLink = () => {
    isActiveLink.value = isActive(page.value.relativePath, item.value.link);
  };
  watch([page, item, hash], updateIsActiveLink);
  onMounted(updateIsActiveLink);
  const hasActiveLink$1 = computed(() => {
    if (isActiveLink.value) {
      return true;
    }
    return item.value.items ? hasActiveLink(page.value.relativePath, item.value.items) : false;
  });
  const hasChildren = computed(() => {
    return !!(item.value.items && item.value.items.length);
  });
  watchEffect(() => {
    collapsed.value = !!(collapsible.value && item.value.collapsed);
  });
  watchPostEffect(() => {
    (isActiveLink.value || hasActiveLink$1.value) && (collapsed.value = false);
  });
  function toggle() {
    if (collapsible.value) {
      collapsed.value = !collapsed.value;
    }
  }
  return {
    collapsed,
    collapsible,
    isLink,
    isActiveLink,
    hasActiveLink: hasActiveLink$1,
    hasChildren,
    toggle
  };
}
function useAside() {
  const { hasSidebar } = useSidebar();
  const is960 = useMediaQuery("(min-width: 960px)");
  const is1280 = useMediaQuery("(min-width: 1280px)");
  const isAsideEnabled = computed(() => {
    if (!is1280.value && !is960.value) {
      return false;
    }
    return hasSidebar.value ? is1280.value : is960.value;
  });
  return {
    isAsideEnabled
  };
}
const ignoreRE = /\b(?:VPBadge|header-anchor|footnote-ref|ignore-header)\b/;
const resolvedHeaders = [];
function resolveTitle(theme2) {
  return typeof theme2.outline === "object" && !Array.isArray(theme2.outline) && theme2.outline.label || theme2.outlineTitle || "On this page";
}
function getHeaders(range) {
  const headers = [
    ...document.querySelectorAll(".VPDoc :where(h1,h2,h3,h4,h5,h6)")
  ].filter((el) => el.id && el.hasChildNodes()).map((el) => {
    const level = Number(el.tagName[1]);
    return {
      element: el,
      title: serializeHeader(el),
      link: "#" + el.id,
      level
    };
  });
  return resolveHeaders(headers, range);
}
function serializeHeader(h2) {
  let ret = "";
  for (const node of h2.childNodes) {
    if (node.nodeType === 1) {
      if (ignoreRE.test(node.className))
        continue;
      ret += node.textContent;
    } else if (node.nodeType === 3) {
      ret += node.textContent;
    }
  }
  return ret.trim();
}
function resolveHeaders(headers, range) {
  if (range === false) {
    return [];
  }
  const levelsRange = (typeof range === "object" && !Array.isArray(range) ? range.level : range) || 2;
  const [high, low] = typeof levelsRange === "number" ? [levelsRange, levelsRange] : levelsRange === "deep" ? [2, 6] : levelsRange;
  return buildTree(headers, high, low);
}
function useActiveAnchor(container, marker) {
  const { isAsideEnabled } = useAside();
  const onScroll = throttleAndDebounce(setActiveLink, 100);
  let prevActiveLink = null;
  onMounted(() => {
    requestAnimationFrame(setActiveLink);
    window.addEventListener("scroll", onScroll);
  });
  onUpdated(() => {
    activateLink(location.hash);
  });
  onUnmounted(() => {
    window.removeEventListener("scroll", onScroll);
  });
  function setActiveLink() {
    if (!isAsideEnabled.value) {
      return;
    }
    const scrollY = window.scrollY;
    const innerHeight = window.innerHeight;
    const offsetHeight = document.body.offsetHeight;
    const isBottom = Math.abs(scrollY + innerHeight - offsetHeight) < 1;
    const headers = resolvedHeaders.map(({ element, link: link2 }) => ({
      link: link2,
      top: getAbsoluteTop(element)
    })).filter(({ top }) => !Number.isNaN(top)).sort((a, b) => a.top - b.top);
    if (!headers.length) {
      activateLink(null);
      return;
    }
    if (scrollY < 1) {
      activateLink(null);
      return;
    }
    if (isBottom) {
      activateLink(headers[headers.length - 1].link);
      return;
    }
    let activeLink = null;
    for (const { link: link2, top } of headers) {
      if (top > scrollY + getScrollOffset() + 4) {
        break;
      }
      activeLink = link2;
    }
    activateLink(activeLink);
  }
  function activateLink(hash) {
    if (prevActiveLink) {
      prevActiveLink.classList.remove("active");
    }
    if (hash == null) {
      prevActiveLink = null;
    } else {
      prevActiveLink = container.value.querySelector(`a[href="${decodeURIComponent(hash)}"]`);
    }
    const activeLink = prevActiveLink;
    if (activeLink) {
      activeLink.classList.add("active");
      marker.value.style.top = activeLink.offsetTop + 39 + "px";
      marker.value.style.opacity = "1";
    } else {
      marker.value.style.top = "33px";
      marker.value.style.opacity = "0";
    }
  }
}
function getAbsoluteTop(element) {
  let offsetTop = 0;
  while (element !== document.body) {
    if (element === null) {
      return NaN;
    }
    offsetTop += element.offsetTop;
    element = element.offsetParent;
  }
  return offsetTop;
}
function buildTree(data, min, max) {
  resolvedHeaders.length = 0;
  const result = [];
  const stack = [];
  data.forEach((item) => {
    const node = { ...item, children: [] };
    let parent = stack[stack.length - 1];
    while (parent && parent.level >= node.level) {
      stack.pop();
      parent = stack[stack.length - 1];
    }
    if (node.element.classList.contains("ignore-header") || parent && "shouldIgnore" in parent) {
      stack.push({ level: node.level, shouldIgnore: true });
      return;
    }
    if (node.level > max || node.level < min)
      return;
    resolvedHeaders.push({ element: node.element, link: node.link });
    if (parent)
      parent.children.push(node);
    else
      result.push(node);
    stack.push(node);
  });
  return result;
}
const _sfc_main$1e = /* @__PURE__ */ defineComponent({
  __name: "VPDocOutlineItem",
  __ssrInlineRender: true,
  props: {
    headers: {},
    root: { type: Boolean }
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      const _component_VPDocOutlineItem = resolveComponent("VPDocOutlineItem", true);
      _push(`<ul${ssrRenderAttrs(mergeProps({
        class: ["VPDocOutlineItem", __props.root ? "root" : "nested"]
      }, _attrs))} data-v-b933a997><!--[-->`);
      ssrRenderList(__props.headers, ({ children, link: link2, title }) => {
        _push(`<li data-v-b933a997><a class="outline-link"${ssrRenderAttr("href", link2)}${ssrRenderAttr("title", title)} data-v-b933a997>${ssrInterpolate(title)}</a>`);
        if (children == null ? void 0 : children.length) {
          _push(ssrRenderComponent(_component_VPDocOutlineItem, { headers: children }, null, _parent));
        } else {
          _push(`<!---->`);
        }
        _push(`</li>`);
      });
      _push(`<!--]--></ul>`);
    };
  }
});
const _sfc_setup$1e = _sfc_main$1e.setup;
_sfc_main$1e.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocOutlineItem.vue");
  return _sfc_setup$1e ? _sfc_setup$1e(props, ctx) : void 0;
};
const VPDocOutlineItem = /* @__PURE__ */ _export_sfc(_sfc_main$1e, [["__scopeId", "data-v-b933a997"]]);
const _sfc_main$1d = /* @__PURE__ */ defineComponent({
  __name: "VPDocAsideOutline",
  __ssrInlineRender: true,
  setup(__props) {
    const { frontmatter, theme: theme2 } = useData();
    const headers = shallowRef([]);
    onContentUpdated(() => {
      headers.value = getHeaders(frontmatter.value.outline ?? theme2.value.outline);
    });
    const container = ref();
    const marker = ref();
    useActiveAnchor(container, marker);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<nav${ssrRenderAttrs(mergeProps({
        "aria-labelledby": "doc-outline-aria-label",
        class: ["VPDocAsideOutline", { "has-outline": headers.value.length > 0 }],
        ref_key: "container",
        ref: container
      }, _attrs))} data-v-a5bbad30><div class="content" data-v-a5bbad30><div class="outline-marker" data-v-a5bbad30></div><div aria-level="2" class="outline-title" id="doc-outline-aria-label" role="heading" data-v-a5bbad30>${ssrInterpolate(unref(resolveTitle)(unref(theme2)))}</div>`);
      _push(ssrRenderComponent(VPDocOutlineItem, {
        headers: headers.value,
        root: true
      }, null, _parent));
      _push(`</div></nav>`);
    };
  }
});
const _sfc_setup$1d = _sfc_main$1d.setup;
_sfc_main$1d.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocAsideOutline.vue");
  return _sfc_setup$1d ? _sfc_setup$1d(props, ctx) : void 0;
};
const VPDocAsideOutline = /* @__PURE__ */ _export_sfc(_sfc_main$1d, [["__scopeId", "data-v-a5bbad30"]]);
const _sfc_main$1c = /* @__PURE__ */ defineComponent({
  __name: "VPDocAsideCarbonAds",
  __ssrInlineRender: true,
  props: {
    carbonAds: {}
  },
  setup(__props) {
    const VPCarbonAds = () => null;
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPDocAsideCarbonAds" }, _attrs))}>`);
      _push(ssrRenderComponent(unref(VPCarbonAds), { "carbon-ads": __props.carbonAds }, null, _parent));
      _push(`</div>`);
    };
  }
});
const _sfc_setup$1c = _sfc_main$1c.setup;
_sfc_main$1c.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocAsideCarbonAds.vue");
  return _sfc_setup$1c ? _sfc_setup$1c(props, ctx) : void 0;
};
const _sfc_main$1b = /* @__PURE__ */ defineComponent({
  __name: "VPDocAside",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPDocAside" }, _attrs))} data-v-3f215769>`);
      ssrRenderSlot(_ctx.$slots, "aside-top", {}, null, _push, _parent);
      ssrRenderSlot(_ctx.$slots, "aside-outline-before", {}, null, _push, _parent);
      _push(ssrRenderComponent(VPDocAsideOutline, null, null, _parent));
      ssrRenderSlot(_ctx.$slots, "aside-outline-after", {}, null, _push, _parent);
      _push(`<div class="spacer" data-v-3f215769></div>`);
      ssrRenderSlot(_ctx.$slots, "aside-ads-before", {}, null, _push, _parent);
      if (unref(theme2).carbonAds) {
        _push(ssrRenderComponent(_sfc_main$1c, {
          "carbon-ads": unref(theme2).carbonAds
        }, null, _parent));
      } else {
        _push(`<!---->`);
      }
      ssrRenderSlot(_ctx.$slots, "aside-ads-after", {}, null, _push, _parent);
      ssrRenderSlot(_ctx.$slots, "aside-bottom", {}, null, _push, _parent);
      _push(`</div>`);
    };
  }
});
const _sfc_setup$1b = _sfc_main$1b.setup;
_sfc_main$1b.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocAside.vue");
  return _sfc_setup$1b ? _sfc_setup$1b(props, ctx) : void 0;
};
const VPDocAside = /* @__PURE__ */ _export_sfc(_sfc_main$1b, [["__scopeId", "data-v-3f215769"]]);
function useEditLink() {
  const { theme: theme2, page } = useData();
  return computed(() => {
    const { text = "Edit this page", pattern = "" } = theme2.value.editLink || {};
    let url;
    if (typeof pattern === "function") {
      url = pattern(page.value);
    } else {
      url = pattern.replace(/:path/g, page.value.filePath);
    }
    return { url, text };
  });
}
function usePrevNext() {
  const { page, theme: theme2, frontmatter } = useData();
  return computed(() => {
    var _a, _b, _c, _d, _e, _f, _g, _h;
    const sidebar = getSidebar(theme2.value.sidebar, page.value.relativePath);
    const links = getFlatSideBarLinks(sidebar);
    const candidates = uniqBy(links, (link2) => link2.link.replace(/[?#].*$/, ""));
    const index = candidates.findIndex((link2) => {
      return isActive(page.value.relativePath, link2.link);
    });
    const hidePrev = ((_a = theme2.value.docFooter) == null ? void 0 : _a.prev) === false && !frontmatter.value.prev || frontmatter.value.prev === false;
    const hideNext = ((_b = theme2.value.docFooter) == null ? void 0 : _b.next) === false && !frontmatter.value.next || frontmatter.value.next === false;
    return {
      prev: hidePrev ? void 0 : {
        text: (typeof frontmatter.value.prev === "string" ? frontmatter.value.prev : typeof frontmatter.value.prev === "object" ? frontmatter.value.prev.text : void 0) ?? ((_c = candidates[index - 1]) == null ? void 0 : _c.docFooterText) ?? ((_d = candidates[index - 1]) == null ? void 0 : _d.text),
        link: (typeof frontmatter.value.prev === "object" ? frontmatter.value.prev.link : void 0) ?? ((_e = candidates[index - 1]) == null ? void 0 : _e.link)
      },
      next: hideNext ? void 0 : {
        text: (typeof frontmatter.value.next === "string" ? frontmatter.value.next : typeof frontmatter.value.next === "object" ? frontmatter.value.next.text : void 0) ?? ((_f = candidates[index + 1]) == null ? void 0 : _f.docFooterText) ?? ((_g = candidates[index + 1]) == null ? void 0 : _g.text),
        link: (typeof frontmatter.value.next === "object" ? frontmatter.value.next.link : void 0) ?? ((_h = candidates[index + 1]) == null ? void 0 : _h.link)
      }
    };
  });
}
function uniqBy(array, keyFn) {
  const seen = /* @__PURE__ */ new Set();
  return array.filter((item) => {
    const k2 = keyFn(item);
    return seen.has(k2) ? false : seen.add(k2);
  });
}
const _sfc_main$1a = /* @__PURE__ */ defineComponent({
  __name: "VPLink",
  __ssrInlineRender: true,
  props: {
    tag: {},
    href: {},
    noIcon: { type: Boolean },
    target: {},
    rel: {}
  },
  setup(__props) {
    const props = __props;
    const tag = computed(() => props.tag ?? (props.href ? "a" : "span"));
    const isExternal2 = computed(
      () => props.href && EXTERNAL_URL_RE.test(props.href) || props.target === "_blank"
    );
    return (_ctx, _push, _parent, _attrs) => {
      ssrRenderVNode(_push, createVNode(resolveDynamicComponent(tag.value), mergeProps({
        class: ["VPLink", {
          link: __props.href,
          "vp-external-link-icon": isExternal2.value,
          "no-icon": __props.noIcon
        }],
        href: __props.href ? unref(normalizeLink$1)(__props.href) : void 0,
        target: __props.target ?? (isExternal2.value ? "_blank" : void 0),
        rel: __props.rel ?? (isExternal2.value ? "noreferrer" : void 0)
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "default", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "default")
            ];
          }
        }),
        _: 3
      }), _parent);
    };
  }
});
const _sfc_setup$1a = _sfc_main$1a.setup;
_sfc_main$1a.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPLink.vue");
  return _sfc_setup$1a ? _sfc_setup$1a(props, ctx) : void 0;
};
const _sfc_main$19 = /* @__PURE__ */ defineComponent({
  __name: "VPDocFooterLastUpdated",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2, page, lang } = useData();
    const date = computed(
      () => new Date(page.value.lastUpdated)
    );
    const isoDatetime = computed(() => date.value.toISOString());
    const datetime = ref("");
    onMounted(() => {
      watchEffect(() => {
        var _a, _b, _c;
        datetime.value = new Intl.DateTimeFormat(
          ((_b = (_a = theme2.value.lastUpdated) == null ? void 0 : _a.formatOptions) == null ? void 0 : _b.forceLocale) ? lang.value : void 0,
          ((_c = theme2.value.lastUpdated) == null ? void 0 : _c.formatOptions) ?? {
            dateStyle: "short",
            timeStyle: "short"
          }
        ).format(date.value);
      });
    });
    return (_ctx, _push, _parent, _attrs) => {
      var _a;
      _push(`<p${ssrRenderAttrs(mergeProps({ class: "VPLastUpdated" }, _attrs))} data-v-e98dd255>${ssrInterpolate(((_a = unref(theme2).lastUpdated) == null ? void 0 : _a.text) || unref(theme2).lastUpdatedText || "Last updated")}: <time${ssrRenderAttr("datetime", isoDatetime.value)} data-v-e98dd255>${ssrInterpolate(datetime.value)}</time></p>`);
    };
  }
});
const _sfc_setup$19 = _sfc_main$19.setup;
_sfc_main$19.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocFooterLastUpdated.vue");
  return _sfc_setup$19 ? _sfc_setup$19(props, ctx) : void 0;
};
const VPDocFooterLastUpdated = /* @__PURE__ */ _export_sfc(_sfc_main$19, [["__scopeId", "data-v-e98dd255"]]);
const _sfc_main$18 = /* @__PURE__ */ defineComponent({
  __name: "VPDocFooter",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2, page, frontmatter } = useData();
    const editLink = useEditLink();
    const control = usePrevNext();
    const hasEditLink = computed(
      () => theme2.value.editLink && frontmatter.value.editLink !== false
    );
    const hasLastUpdated = computed(() => page.value.lastUpdated);
    const showFooter = computed(
      () => hasEditLink.value || hasLastUpdated.value || control.value.prev || control.value.next
    );
    return (_ctx, _push, _parent, _attrs) => {
      var _a, _b, _c, _d;
      if (showFooter.value) {
        _push(`<footer${ssrRenderAttrs(mergeProps({ class: "VPDocFooter" }, _attrs))} data-v-e257564d>`);
        ssrRenderSlot(_ctx.$slots, "doc-footer-before", {}, null, _push, _parent);
        if (hasEditLink.value || hasLastUpdated.value) {
          _push(`<div class="edit-info" data-v-e257564d>`);
          if (hasEditLink.value) {
            _push(`<div class="edit-link" data-v-e257564d>`);
            _push(ssrRenderComponent(_sfc_main$1a, {
              class: "edit-link-button",
              href: unref(editLink).url,
              "no-icon": true
            }, {
              default: withCtx((_, _push2, _parent2, _scopeId) => {
                if (_push2) {
                  _push2(`<span class="vpi-square-pen edit-link-icon" data-v-e257564d${_scopeId}></span> ${ssrInterpolate(unref(editLink).text)}`);
                } else {
                  return [
                    createVNode("span", { class: "vpi-square-pen edit-link-icon" }),
                    createTextVNode(" " + toDisplayString(unref(editLink).text), 1)
                  ];
                }
              }),
              _: 1
            }, _parent));
            _push(`</div>`);
          } else {
            _push(`<!---->`);
          }
          if (hasLastUpdated.value) {
            _push(`<div class="last-updated" data-v-e257564d>`);
            _push(ssrRenderComponent(VPDocFooterLastUpdated, null, null, _parent));
            _push(`</div>`);
          } else {
            _push(`<!---->`);
          }
          _push(`</div>`);
        } else {
          _push(`<!---->`);
        }
        if (((_a = unref(control).prev) == null ? void 0 : _a.link) || ((_b = unref(control).next) == null ? void 0 : _b.link)) {
          _push(`<nav class="prev-next" aria-labelledby="doc-footer-aria-label" data-v-e257564d><span class="visually-hidden" id="doc-footer-aria-label" data-v-e257564d>Pager</span><div class="pager" data-v-e257564d>`);
          if ((_c = unref(control).prev) == null ? void 0 : _c.link) {
            _push(ssrRenderComponent(_sfc_main$1a, {
              class: "pager-link prev",
              href: unref(control).prev.link
            }, {
              default: withCtx((_, _push2, _parent2, _scopeId) => {
                var _a2, _b2;
                if (_push2) {
                  _push2(`<span class="desc" data-v-e257564d${_scopeId}>${(((_a2 = unref(theme2).docFooter) == null ? void 0 : _a2.prev) || "Previous page") ?? ""}</span><span class="title" data-v-e257564d${_scopeId}>${unref(control).prev.text ?? ""}</span>`);
                } else {
                  return [
                    createVNode("span", {
                      class: "desc",
                      innerHTML: ((_b2 = unref(theme2).docFooter) == null ? void 0 : _b2.prev) || "Previous page"
                    }, null, 8, ["innerHTML"]),
                    createVNode("span", {
                      class: "title",
                      innerHTML: unref(control).prev.text
                    }, null, 8, ["innerHTML"])
                  ];
                }
              }),
              _: 1
            }, _parent));
          } else {
            _push(`<!---->`);
          }
          _push(`</div><div class="pager" data-v-e257564d>`);
          if ((_d = unref(control).next) == null ? void 0 : _d.link) {
            _push(ssrRenderComponent(_sfc_main$1a, {
              class: "pager-link next",
              href: unref(control).next.link
            }, {
              default: withCtx((_, _push2, _parent2, _scopeId) => {
                var _a2, _b2;
                if (_push2) {
                  _push2(`<span class="desc" data-v-e257564d${_scopeId}>${(((_a2 = unref(theme2).docFooter) == null ? void 0 : _a2.next) || "Next page") ?? ""}</span><span class="title" data-v-e257564d${_scopeId}>${unref(control).next.text ?? ""}</span>`);
                } else {
                  return [
                    createVNode("span", {
                      class: "desc",
                      innerHTML: ((_b2 = unref(theme2).docFooter) == null ? void 0 : _b2.next) || "Next page"
                    }, null, 8, ["innerHTML"]),
                    createVNode("span", {
                      class: "title",
                      innerHTML: unref(control).next.text
                    }, null, 8, ["innerHTML"])
                  ];
                }
              }),
              _: 1
            }, _parent));
          } else {
            _push(`<!---->`);
          }
          _push(`</div></nav>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</footer>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$18 = _sfc_main$18.setup;
_sfc_main$18.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocFooter.vue");
  return _sfc_setup$18 ? _sfc_setup$18(props, ctx) : void 0;
};
const VPDocFooter = /* @__PURE__ */ _export_sfc(_sfc_main$18, [["__scopeId", "data-v-e257564d"]]);
const _sfc_main$17 = /* @__PURE__ */ defineComponent({
  __name: "VPDoc",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    const route = useRoute();
    const { hasSidebar, hasAside, leftAside } = useSidebar();
    const pageName = computed(
      () => route.path.replace(/[./]+/g, "_").replace(/_html$/, "")
    );
    return (_ctx, _push, _parent, _attrs) => {
      const _component_Content = resolveComponent("Content");
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPDoc", { "has-sidebar": unref(hasSidebar), "has-aside": unref(hasAside) }]
      }, _attrs))} data-v-39a288b8>`);
      ssrRenderSlot(_ctx.$slots, "doc-top", {}, null, _push, _parent);
      _push(`<div class="container" data-v-39a288b8>`);
      if (unref(hasAside)) {
        _push(`<div class="${ssrRenderClass([{ "left-aside": unref(leftAside) }, "aside"])}" data-v-39a288b8><div class="aside-curtain" data-v-39a288b8></div><div class="aside-container" data-v-39a288b8><div class="aside-content" data-v-39a288b8>`);
        _push(ssrRenderComponent(VPDocAside, null, {
          "aside-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-top", {}, void 0, true)
              ];
            }
          }),
          "aside-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-bottom", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-before", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-after", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-before", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(`</div></div></div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<div class="content" data-v-39a288b8><div class="content-container" data-v-39a288b8>`);
      ssrRenderSlot(_ctx.$slots, "doc-before", {}, null, _push, _parent);
      _push(`<main class="main" data-v-39a288b8>`);
      _push(ssrRenderComponent(_component_Content, {
        class: ["vp-doc", [
          pageName.value,
          unref(theme2).externalLinkIcon && "external-link-icon-enabled"
        ]]
      }, null, _parent));
      _push(`</main>`);
      _push(ssrRenderComponent(VPDocFooter, null, {
        "doc-footer-before": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "doc-footer-before", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "doc-footer-before", {}, void 0, true)
            ];
          }
        }),
        _: 3
      }, _parent));
      ssrRenderSlot(_ctx.$slots, "doc-after", {}, null, _push, _parent);
      _push(`</div></div></div>`);
      ssrRenderSlot(_ctx.$slots, "doc-bottom", {}, null, _push, _parent);
      _push(`</div>`);
    };
  }
});
const _sfc_setup$17 = _sfc_main$17.setup;
_sfc_main$17.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDoc.vue");
  return _sfc_setup$17 ? _sfc_setup$17(props, ctx) : void 0;
};
const VPDoc = /* @__PURE__ */ _export_sfc(_sfc_main$17, [["__scopeId", "data-v-39a288b8"]]);
const _sfc_main$16 = /* @__PURE__ */ defineComponent({
  __name: "VPButton",
  __ssrInlineRender: true,
  props: {
    tag: {},
    size: { default: "medium" },
    theme: { default: "brand" },
    text: {},
    href: {},
    target: {},
    rel: {}
  },
  setup(__props) {
    const props = __props;
    const isExternal2 = computed(
      () => props.href && EXTERNAL_URL_RE.test(props.href)
    );
    const component = computed(() => {
      return props.tag || (props.href ? "a" : "button");
    });
    return (_ctx, _push, _parent, _attrs) => {
      ssrRenderVNode(_push, createVNode(resolveDynamicComponent(component.value), mergeProps({
        class: ["VPButton", [__props.size, __props.theme]],
        href: __props.href ? unref(normalizeLink$1)(__props.href) : void 0,
        target: props.target ?? (isExternal2.value ? "_blank" : void 0),
        rel: props.rel ?? (isExternal2.value ? "noreferrer" : void 0)
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`${ssrInterpolate(__props.text)}`);
          } else {
            return [
              createTextVNode(toDisplayString(__props.text), 1)
            ];
          }
        }),
        _: 1
      }), _parent);
    };
  }
});
const _sfc_setup$16 = _sfc_main$16.setup;
_sfc_main$16.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPButton.vue");
  return _sfc_setup$16 ? _sfc_setup$16(props, ctx) : void 0;
};
const VPButton = /* @__PURE__ */ _export_sfc(_sfc_main$16, [["__scopeId", "data-v-fa7799d5"]]);
const _sfc_main$15 = /* @__PURE__ */ defineComponent({
  ...{ inheritAttrs: false },
  __name: "VPImage",
  __ssrInlineRender: true,
  props: {
    image: {},
    alt: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      const _component_VPImage = resolveComponent("VPImage", true);
      if (__props.image) {
        _push(`<!--[-->`);
        if (typeof __props.image === "string" || "src" in __props.image) {
          _push(`<img${ssrRenderAttrs(mergeProps({ class: "VPImage" }, typeof __props.image === "string" ? _ctx.$attrs : { ...__props.image, ..._ctx.$attrs }, {
            src: unref(withBase)(typeof __props.image === "string" ? __props.image : __props.image.src),
            alt: __props.alt ?? (typeof __props.image === "string" ? "" : __props.image.alt || "")
          }))} data-v-8426fc1a>`);
        } else {
          _push(`<!--[-->`);
          _push(ssrRenderComponent(_component_VPImage, mergeProps({
            class: "dark",
            image: __props.image.dark,
            alt: __props.image.alt
          }, _ctx.$attrs), null, _parent));
          _push(ssrRenderComponent(_component_VPImage, mergeProps({
            class: "light",
            image: __props.image.light,
            alt: __props.image.alt
          }, _ctx.$attrs), null, _parent));
          _push(`<!--]-->`);
        }
        _push(`<!--]-->`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$15 = _sfc_main$15.setup;
_sfc_main$15.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPImage.vue");
  return _sfc_setup$15 ? _sfc_setup$15(props, ctx) : void 0;
};
const VPImage = /* @__PURE__ */ _export_sfc(_sfc_main$15, [["__scopeId", "data-v-8426fc1a"]]);
const _sfc_main$14 = /* @__PURE__ */ defineComponent({
  __name: "VPHero",
  __ssrInlineRender: true,
  props: {
    name: {},
    text: {},
    tagline: {},
    image: {},
    actions: {}
  },
  setup(__props) {
    const heroImageSlotExists = inject("hero-image-slot-exists");
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPHero", { "has-image": __props.image || unref(heroImageSlotExists) }]
      }, _attrs))} data-v-4f9c455b><div class="container" data-v-4f9c455b><div class="main" data-v-4f9c455b>`);
      ssrRenderSlot(_ctx.$slots, "home-hero-info-before", {}, null, _push, _parent);
      ssrRenderSlot(_ctx.$slots, "home-hero-info", {}, () => {
        _push(`<h1 class="heading" data-v-4f9c455b>`);
        if (__props.name) {
          _push(`<span class="name clip" data-v-4f9c455b>${__props.name ?? ""}</span>`);
        } else {
          _push(`<!---->`);
        }
        if (__props.text) {
          _push(`<span class="text" data-v-4f9c455b>${__props.text ?? ""}</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</h1>`);
        if (__props.tagline) {
          _push(`<p class="tagline" data-v-4f9c455b>${__props.tagline ?? ""}</p>`);
        } else {
          _push(`<!---->`);
        }
      }, _push, _parent);
      ssrRenderSlot(_ctx.$slots, "home-hero-info-after", {}, null, _push, _parent);
      if (__props.actions) {
        _push(`<div class="actions" data-v-4f9c455b><!--[-->`);
        ssrRenderList(__props.actions, (action) => {
          _push(`<div class="action" data-v-4f9c455b>`);
          _push(ssrRenderComponent(VPButton, {
            tag: "a",
            size: "medium",
            theme: action.theme,
            text: action.text,
            href: action.link,
            target: action.target,
            rel: action.rel
          }, null, _parent));
          _push(`</div>`);
        });
        _push(`<!--]--></div>`);
      } else {
        _push(`<!---->`);
      }
      ssrRenderSlot(_ctx.$slots, "home-hero-actions-after", {}, null, _push, _parent);
      _push(`</div>`);
      if (__props.image || unref(heroImageSlotExists)) {
        _push(`<div class="image" data-v-4f9c455b><div class="image-container" data-v-4f9c455b><div class="image-bg" data-v-4f9c455b></div>`);
        ssrRenderSlot(_ctx.$slots, "home-hero-image", {}, () => {
          if (__props.image) {
            _push(ssrRenderComponent(VPImage, {
              class: "image-src",
              image: __props.image
            }, null, _parent));
          } else {
            _push(`<!---->`);
          }
        }, _push, _parent);
        _push(`</div></div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div></div>`);
    };
  }
});
const _sfc_setup$14 = _sfc_main$14.setup;
_sfc_main$14.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHero.vue");
  return _sfc_setup$14 ? _sfc_setup$14(props, ctx) : void 0;
};
const VPHero = /* @__PURE__ */ _export_sfc(_sfc_main$14, [["__scopeId", "data-v-4f9c455b"]]);
const _sfc_main$13 = /* @__PURE__ */ defineComponent({
  __name: "VPHomeHero",
  __ssrInlineRender: true,
  setup(__props) {
    const { frontmatter: fm } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(fm).hero) {
        _push(ssrRenderComponent(VPHero, mergeProps({
          class: "VPHomeHero",
          name: unref(fm).hero.name,
          text: unref(fm).hero.text,
          tagline: unref(fm).hero.tagline,
          image: unref(fm).hero.image,
          actions: unref(fm).hero.actions
        }, _attrs), {
          "home-hero-info-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-before")
              ];
            }
          }),
          "home-hero-info": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info")
              ];
            }
          }),
          "home-hero-info-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-after")
              ];
            }
          }),
          "home-hero-actions-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-actions-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-actions-after")
              ];
            }
          }),
          "home-hero-image": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-image", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-image")
              ];
            }
          }),
          _: 3
        }, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$13 = _sfc_main$13.setup;
_sfc_main$13.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHomeHero.vue");
  return _sfc_setup$13 ? _sfc_setup$13(props, ctx) : void 0;
};
const _sfc_main$12 = /* @__PURE__ */ defineComponent({
  __name: "VPFeature",
  __ssrInlineRender: true,
  props: {
    icon: {},
    title: {},
    details: {},
    link: {},
    linkText: {},
    rel: {},
    target: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(_sfc_main$1a, mergeProps({
        class: "VPFeature",
        href: __props.link,
        rel: __props.rel,
        target: __props.target,
        "no-icon": true,
        tag: __props.link ? "a" : "div"
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<article class="box" data-v-a3976bdc${_scopeId}>`);
            if (typeof __props.icon === "object" && __props.icon.wrap) {
              _push2(`<div class="icon" data-v-a3976bdc${_scopeId}>`);
              _push2(ssrRenderComponent(VPImage, {
                image: __props.icon,
                alt: __props.icon.alt,
                height: __props.icon.height || 48,
                width: __props.icon.width || 48
              }, null, _parent2, _scopeId));
              _push2(`</div>`);
            } else if (typeof __props.icon === "object") {
              _push2(ssrRenderComponent(VPImage, {
                image: __props.icon,
                alt: __props.icon.alt,
                height: __props.icon.height || 48,
                width: __props.icon.width || 48
              }, null, _parent2, _scopeId));
            } else if (__props.icon) {
              _push2(`<div class="icon" data-v-a3976bdc${_scopeId}>${__props.icon ?? ""}</div>`);
            } else {
              _push2(`<!---->`);
            }
            _push2(`<h2 class="title" data-v-a3976bdc${_scopeId}>${__props.title ?? ""}</h2>`);
            if (__props.details) {
              _push2(`<p class="details" data-v-a3976bdc${_scopeId}>${__props.details ?? ""}</p>`);
            } else {
              _push2(`<!---->`);
            }
            if (__props.linkText) {
              _push2(`<div class="link-text" data-v-a3976bdc${_scopeId}><p class="link-text-value" data-v-a3976bdc${_scopeId}>${ssrInterpolate(__props.linkText)} <span class="vpi-arrow-right link-text-icon" data-v-a3976bdc${_scopeId}></span></p></div>`);
            } else {
              _push2(`<!---->`);
            }
            _push2(`</article>`);
          } else {
            return [
              createVNode("article", { class: "box" }, [
                typeof __props.icon === "object" && __props.icon.wrap ? (openBlock(), createBlock("div", {
                  key: 0,
                  class: "icon"
                }, [
                  createVNode(VPImage, {
                    image: __props.icon,
                    alt: __props.icon.alt,
                    height: __props.icon.height || 48,
                    width: __props.icon.width || 48
                  }, null, 8, ["image", "alt", "height", "width"])
                ])) : typeof __props.icon === "object" ? (openBlock(), createBlock(VPImage, {
                  key: 1,
                  image: __props.icon,
                  alt: __props.icon.alt,
                  height: __props.icon.height || 48,
                  width: __props.icon.width || 48
                }, null, 8, ["image", "alt", "height", "width"])) : __props.icon ? (openBlock(), createBlock("div", {
                  key: 2,
                  class: "icon",
                  innerHTML: __props.icon
                }, null, 8, ["innerHTML"])) : createCommentVNode("", true),
                createVNode("h2", {
                  class: "title",
                  innerHTML: __props.title
                }, null, 8, ["innerHTML"]),
                __props.details ? (openBlock(), createBlock("p", {
                  key: 3,
                  class: "details",
                  innerHTML: __props.details
                }, null, 8, ["innerHTML"])) : createCommentVNode("", true),
                __props.linkText ? (openBlock(), createBlock("div", {
                  key: 4,
                  class: "link-text"
                }, [
                  createVNode("p", { class: "link-text-value" }, [
                    createTextVNode(toDisplayString(__props.linkText) + " ", 1),
                    createVNode("span", { class: "vpi-arrow-right link-text-icon" })
                  ])
                ])) : createCommentVNode("", true)
              ])
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$12 = _sfc_main$12.setup;
_sfc_main$12.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPFeature.vue");
  return _sfc_setup$12 ? _sfc_setup$12(props, ctx) : void 0;
};
const VPFeature = /* @__PURE__ */ _export_sfc(_sfc_main$12, [["__scopeId", "data-v-a3976bdc"]]);
const _sfc_main$11 = /* @__PURE__ */ defineComponent({
  __name: "VPFeatures",
  __ssrInlineRender: true,
  props: {
    features: {}
  },
  setup(__props) {
    const props = __props;
    const grid = computed(() => {
      const length = props.features.length;
      if (!length) {
        return;
      } else if (length === 2) {
        return "grid-2";
      } else if (length === 3) {
        return "grid-3";
      } else if (length % 3 === 0) {
        return "grid-6";
      } else if (length > 3) {
        return "grid-4";
      }
    });
    return (_ctx, _push, _parent, _attrs) => {
      if (__props.features) {
        _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPFeatures" }, _attrs))} data-v-a6181336><div class="container" data-v-a6181336><div class="items" data-v-a6181336><!--[-->`);
        ssrRenderList(__props.features, (feature) => {
          _push(`<div class="${ssrRenderClass([[grid.value], "item"])}" data-v-a6181336>`);
          _push(ssrRenderComponent(VPFeature, {
            icon: feature.icon,
            title: feature.title,
            details: feature.details,
            link: feature.link,
            "link-text": feature.linkText,
            rel: feature.rel,
            target: feature.target
          }, null, _parent));
          _push(`</div>`);
        });
        _push(`<!--]--></div></div></div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$11 = _sfc_main$11.setup;
_sfc_main$11.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPFeatures.vue");
  return _sfc_setup$11 ? _sfc_setup$11(props, ctx) : void 0;
};
const VPFeatures = /* @__PURE__ */ _export_sfc(_sfc_main$11, [["__scopeId", "data-v-a6181336"]]);
const _sfc_main$10 = /* @__PURE__ */ defineComponent({
  __name: "VPHomeFeatures",
  __ssrInlineRender: true,
  setup(__props) {
    const { frontmatter: fm } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(fm).features) {
        _push(ssrRenderComponent(VPFeatures, mergeProps({
          class: "VPHomeFeatures",
          features: unref(fm).features
        }, _attrs), null, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$10 = _sfc_main$10.setup;
_sfc_main$10.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHomeFeatures.vue");
  return _sfc_setup$10 ? _sfc_setup$10(props, ctx) : void 0;
};
const _sfc_main$$ = /* @__PURE__ */ defineComponent({
  __name: "VPHomeContent",
  __ssrInlineRender: true,
  setup(__props) {
    const { width: vw } = useWindowSize({
      initialWidth: 0,
      includeScrollbar: false
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: "vp-doc container",
        style: unref(vw) ? { "--vp-offset": `calc(50% - ${unref(vw) / 2}px)` } : {}
      }, _attrs))} data-v-8e2d4988>`);
      ssrRenderSlot(_ctx.$slots, "default", {}, null, _push, _parent);
      _push(`</div>`);
    };
  }
});
const _sfc_setup$$ = _sfc_main$$.setup;
_sfc_main$$.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHomeContent.vue");
  return _sfc_setup$$ ? _sfc_setup$$(props, ctx) : void 0;
};
const VPHomeContent = /* @__PURE__ */ _export_sfc(_sfc_main$$, [["__scopeId", "data-v-8e2d4988"]]);
const _sfc_main$_ = /* @__PURE__ */ defineComponent({
  __name: "VPHome",
  __ssrInlineRender: true,
  setup(__props) {
    const { frontmatter, theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      const _component_Content = resolveComponent("Content");
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPHome", {
          "external-link-icon-enabled": unref(theme2).externalLinkIcon
        }]
      }, _attrs))} data-v-8b561e3d>`);
      ssrRenderSlot(_ctx.$slots, "home-hero-before", {}, null, _push, _parent);
      _push(ssrRenderComponent(_sfc_main$13, null, {
        "home-hero-info-before": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "home-hero-info-before", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "home-hero-info-before", {}, void 0, true)
            ];
          }
        }),
        "home-hero-info": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "home-hero-info", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "home-hero-info", {}, void 0, true)
            ];
          }
        }),
        "home-hero-info-after": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "home-hero-info-after", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "home-hero-info-after", {}, void 0, true)
            ];
          }
        }),
        "home-hero-actions-after": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "home-hero-actions-after", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "home-hero-actions-after", {}, void 0, true)
            ];
          }
        }),
        "home-hero-image": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "home-hero-image", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "home-hero-image", {}, void 0, true)
            ];
          }
        }),
        _: 3
      }, _parent));
      ssrRenderSlot(_ctx.$slots, "home-hero-after", {}, null, _push, _parent);
      ssrRenderSlot(_ctx.$slots, "home-features-before", {}, null, _push, _parent);
      _push(ssrRenderComponent(_sfc_main$10, null, null, _parent));
      ssrRenderSlot(_ctx.$slots, "home-features-after", {}, null, _push, _parent);
      if (unref(frontmatter).markdownStyles !== false) {
        _push(ssrRenderComponent(VPHomeContent, null, {
          default: withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              _push2(ssrRenderComponent(_component_Content, null, null, _parent2, _scopeId));
            } else {
              return [
                createVNode(_component_Content)
              ];
            }
          }),
          _: 1
        }, _parent));
      } else {
        _push(ssrRenderComponent(_component_Content, null, null, _parent));
      }
      _push(`</div>`);
    };
  }
});
const _sfc_setup$_ = _sfc_main$_.setup;
_sfc_main$_.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHome.vue");
  return _sfc_setup$_ ? _sfc_setup$_(props, ctx) : void 0;
};
const VPHome = /* @__PURE__ */ _export_sfc(_sfc_main$_, [["__scopeId", "data-v-8b561e3d"]]);
const _sfc_main$Z = {};
function _sfc_ssrRender$1(_ctx, _push, _parent, _attrs) {
  const _component_Content = resolveComponent("Content");
  _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPPage" }, _attrs))}>`);
  ssrRenderSlot(_ctx.$slots, "page-top", {}, null, _push, _parent);
  _push(ssrRenderComponent(_component_Content, null, null, _parent));
  ssrRenderSlot(_ctx.$slots, "page-bottom", {}, null, _push, _parent);
  _push(`</div>`);
}
const _sfc_setup$Z = _sfc_main$Z.setup;
_sfc_main$Z.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPPage.vue");
  return _sfc_setup$Z ? _sfc_setup$Z(props, ctx) : void 0;
};
const VPPage = /* @__PURE__ */ _export_sfc(_sfc_main$Z, [["ssrRender", _sfc_ssrRender$1]]);
const _sfc_main$Y = /* @__PURE__ */ defineComponent({
  __name: "VPContent",
  __ssrInlineRender: true,
  setup(__props) {
    const { page, frontmatter } = useData();
    const { hasSidebar } = useSidebar();
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPContent", {
          "has-sidebar": unref(hasSidebar),
          "is-home": unref(frontmatter).layout === "home"
        }],
        id: "VPContent"
      }, _attrs))} data-v-1428d186>`);
      if (unref(page).isNotFound) {
        ssrRenderSlot(_ctx.$slots, "not-found", {}, () => {
          _push(ssrRenderComponent(NotFound, null, null, _parent));
        }, _push, _parent);
      } else if (unref(frontmatter).layout === "page") {
        _push(ssrRenderComponent(VPPage, null, {
          "page-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "page-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "page-top", {}, void 0, true)
              ];
            }
          }),
          "page-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "page-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "page-bottom", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
      } else if (unref(frontmatter).layout === "home") {
        _push(ssrRenderComponent(VPHome, null, {
          "home-hero-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-before", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-before", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-after", {}, void 0, true)
              ];
            }
          }),
          "home-hero-actions-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-actions-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-actions-after", {}, void 0, true)
              ];
            }
          }),
          "home-hero-image": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-image", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-image", {}, void 0, true)
              ];
            }
          }),
          "home-hero-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-after", {}, void 0, true)
              ];
            }
          }),
          "home-features-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-features-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-features-before", {}, void 0, true)
              ];
            }
          }),
          "home-features-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-features-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-features-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
      } else if (unref(frontmatter).layout && unref(frontmatter).layout !== "doc") {
        ssrRenderVNode(_push, createVNode(resolveDynamicComponent(unref(frontmatter).layout), null, null), _parent);
      } else {
        _push(ssrRenderComponent(VPDoc, null, {
          "doc-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-top", {}, void 0, true)
              ];
            }
          }),
          "doc-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-bottom", {}, void 0, true)
              ];
            }
          }),
          "doc-footer-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-footer-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-footer-before", {}, void 0, true)
              ];
            }
          }),
          "doc-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-before", {}, void 0, true)
              ];
            }
          }),
          "doc-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-after", {}, void 0, true)
              ];
            }
          }),
          "aside-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-top", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-before", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-after", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-before", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-after", {}, void 0, true)
              ];
            }
          }),
          "aside-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-bottom", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
      }
      _push(`</div>`);
    };
  }
});
const _sfc_setup$Y = _sfc_main$Y.setup;
_sfc_main$Y.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPContent.vue");
  return _sfc_setup$Y ? _sfc_setup$Y(props, ctx) : void 0;
};
const VPContent = /* @__PURE__ */ _export_sfc(_sfc_main$Y, [["__scopeId", "data-v-1428d186"]]);
const _sfc_main$X = /* @__PURE__ */ defineComponent({
  __name: "VPFooter",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2, frontmatter } = useData();
    const { hasSidebar } = useSidebar();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(theme2).footer && unref(frontmatter).footer !== false) {
        _push(`<footer${ssrRenderAttrs(mergeProps({
          class: ["VPFooter", { "has-sidebar": unref(hasSidebar) }]
        }, _attrs))} data-v-e315a0ad><div class="container" data-v-e315a0ad>`);
        if (unref(theme2).footer.message) {
          _push(`<p class="message" data-v-e315a0ad>${unref(theme2).footer.message ?? ""}</p>`);
        } else {
          _push(`<!---->`);
        }
        if (unref(theme2).footer.copyright) {
          _push(`<p class="copyright" data-v-e315a0ad>${unref(theme2).footer.copyright ?? ""}</p>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</div></footer>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$X = _sfc_main$X.setup;
_sfc_main$X.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPFooter.vue");
  return _sfc_setup$X ? _sfc_setup$X(props, ctx) : void 0;
};
const VPFooter = /* @__PURE__ */ _export_sfc(_sfc_main$X, [["__scopeId", "data-v-e315a0ad"]]);
function useLocalNav() {
  const { theme: theme2, frontmatter } = useData();
  const headers = shallowRef([]);
  const hasLocalNav = computed(() => {
    return headers.value.length > 0;
  });
  onContentUpdated(() => {
    headers.value = getHeaders(frontmatter.value.outline ?? theme2.value.outline);
  });
  return {
    headers,
    hasLocalNav
  };
}
const _sfc_main$W = /* @__PURE__ */ defineComponent({
  __name: "VPLocalNavOutlineDropdown",
  __ssrInlineRender: true,
  props: {
    headers: {},
    navHeight: {}
  },
  setup(__props) {
    const { theme: theme2 } = useData();
    const open = ref(false);
    const vh = ref(0);
    const main = ref();
    ref();
    function closeOnClickOutside(e) {
      var _a;
      if (!((_a = main.value) == null ? void 0 : _a.contains(e.target))) {
        open.value = false;
      }
    }
    watch(open, (value) => {
      if (value) {
        document.addEventListener("click", closeOnClickOutside);
        return;
      }
      document.removeEventListener("click", closeOnClickOutside);
    });
    onKeyStroke("Escape", () => {
      open.value = false;
    });
    onContentUpdated(() => {
      open.value = false;
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: "VPLocalNavOutlineDropdown",
        style: { "--vp-vh": vh.value + "px" },
        ref_key: "main",
        ref: main
      }, _attrs))} data-v-8a42e2b4>`);
      if (__props.headers.length > 0) {
        _push(`<button class="${ssrRenderClass({ open: open.value })}" data-v-8a42e2b4><span class="menu-text" data-v-8a42e2b4>${ssrInterpolate(unref(resolveTitle)(unref(theme2)))}</span><span class="vpi-chevron-right icon" data-v-8a42e2b4></span></button>`);
      } else {
        _push(`<button data-v-8a42e2b4>${ssrInterpolate(unref(theme2).returnToTopLabel || "Return to top")}</button>`);
      }
      if (open.value) {
        _push(`<div class="items" data-v-8a42e2b4><div class="header" data-v-8a42e2b4><a class="top-link" href="#" data-v-8a42e2b4>${ssrInterpolate(unref(theme2).returnToTopLabel || "Return to top")}</a></div><div class="outline" data-v-8a42e2b4>`);
        _push(ssrRenderComponent(VPDocOutlineItem, { headers: __props.headers }, null, _parent));
        _push(`</div></div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div>`);
    };
  }
});
const _sfc_setup$W = _sfc_main$W.setup;
_sfc_main$W.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPLocalNavOutlineDropdown.vue");
  return _sfc_setup$W ? _sfc_setup$W(props, ctx) : void 0;
};
const VPLocalNavOutlineDropdown = /* @__PURE__ */ _export_sfc(_sfc_main$W, [["__scopeId", "data-v-8a42e2b4"]]);
const _sfc_main$V = /* @__PURE__ */ defineComponent({
  __name: "VPLocalNav",
  __ssrInlineRender: true,
  props: {
    open: { type: Boolean }
  },
  emits: ["open-menu"],
  setup(__props) {
    const { theme: theme2, frontmatter } = useData();
    const { hasSidebar } = useSidebar();
    const { headers } = useLocalNav();
    const { y } = useWindowScroll();
    const navHeight = ref(0);
    onMounted(() => {
      navHeight.value = parseInt(
        getComputedStyle(document.documentElement).getPropertyValue(
          "--vp-nav-height"
        )
      );
    });
    onContentUpdated(() => {
      headers.value = getHeaders(frontmatter.value.outline ?? theme2.value.outline);
    });
    const empty = computed(() => {
      return headers.value.length === 0;
    });
    const emptyAndNoSidebar = computed(() => {
      return empty.value && !hasSidebar.value;
    });
    const classes = computed(() => {
      return {
        VPLocalNav: true,
        "has-sidebar": hasSidebar.value,
        empty: empty.value,
        fixed: emptyAndNoSidebar.value
      };
    });
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(frontmatter).layout !== "home" && (!emptyAndNoSidebar.value || unref(y) >= navHeight.value)) {
        _push(`<div${ssrRenderAttrs(mergeProps({ class: classes.value }, _attrs))} data-v-a6f0e41e><div class="container" data-v-a6f0e41e>`);
        if (unref(hasSidebar)) {
          _push(`<button class="menu"${ssrRenderAttr("aria-expanded", __props.open)} aria-controls="VPSidebarNav" data-v-a6f0e41e><span class="vpi-align-left menu-icon" data-v-a6f0e41e></span><span class="menu-text" data-v-a6f0e41e>${ssrInterpolate(unref(theme2).sidebarMenuLabel || "Menu")}</span></button>`);
        } else {
          _push(`<!---->`);
        }
        _push(ssrRenderComponent(VPLocalNavOutlineDropdown, {
          headers: unref(headers),
          navHeight: navHeight.value
        }, null, _parent));
        _push(`</div></div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$V = _sfc_main$V.setup;
_sfc_main$V.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPLocalNav.vue");
  return _sfc_setup$V ? _sfc_setup$V(props, ctx) : void 0;
};
const VPLocalNav = /* @__PURE__ */ _export_sfc(_sfc_main$V, [["__scopeId", "data-v-a6f0e41e"]]);
function useNav() {
  const isScreenOpen = ref(false);
  function openScreen() {
    isScreenOpen.value = true;
    window.addEventListener("resize", closeScreenOnTabletWindow);
  }
  function closeScreen() {
    isScreenOpen.value = false;
    window.removeEventListener("resize", closeScreenOnTabletWindow);
  }
  function toggleScreen() {
    isScreenOpen.value ? closeScreen() : openScreen();
  }
  function closeScreenOnTabletWindow() {
    window.outerWidth >= 768 && closeScreen();
  }
  const route = useRoute();
  watch(() => route.path, closeScreen);
  return {
    isScreenOpen,
    openScreen,
    closeScreen,
    toggleScreen
  };
}
const _sfc_main$U = {};
function _sfc_ssrRender(_ctx, _push, _parent, _attrs) {
  _push(`<button${ssrRenderAttrs(mergeProps({
    class: "VPSwitch",
    type: "button",
    role: "switch"
  }, _attrs))} data-v-1d5665e3><span class="check" data-v-1d5665e3>`);
  if (_ctx.$slots.default) {
    _push(`<span class="icon" data-v-1d5665e3>`);
    ssrRenderSlot(_ctx.$slots, "default", {}, null, _push, _parent);
    _push(`</span>`);
  } else {
    _push(`<!---->`);
  }
  _push(`</span></button>`);
}
const _sfc_setup$U = _sfc_main$U.setup;
_sfc_main$U.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSwitch.vue");
  return _sfc_setup$U ? _sfc_setup$U(props, ctx) : void 0;
};
const VPSwitch = /* @__PURE__ */ _export_sfc(_sfc_main$U, [["ssrRender", _sfc_ssrRender], ["__scopeId", "data-v-1d5665e3"]]);
const _sfc_main$T = /* @__PURE__ */ defineComponent({
  __name: "VPSwitchAppearance",
  __ssrInlineRender: true,
  setup(__props) {
    const { isDark, theme: theme2 } = useData();
    const toggleAppearance = inject("toggle-appearance", () => {
      isDark.value = !isDark.value;
    });
    const switchTitle = ref("");
    watchPostEffect(() => {
      switchTitle.value = isDark.value ? theme2.value.lightModeSwitchTitle || "Switch to light theme" : theme2.value.darkModeSwitchTitle || "Switch to dark theme";
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(VPSwitch, mergeProps({
        title: switchTitle.value,
        class: "VPSwitchAppearance",
        "aria-checked": unref(isDark),
        onClick: unref(toggleAppearance)
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<span class="vpi-sun sun" data-v-5337faa4${_scopeId}></span><span class="vpi-moon moon" data-v-5337faa4${_scopeId}></span>`);
          } else {
            return [
              createVNode("span", { class: "vpi-sun sun" }),
              createVNode("span", { class: "vpi-moon moon" })
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$T = _sfc_main$T.setup;
_sfc_main$T.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSwitchAppearance.vue");
  return _sfc_setup$T ? _sfc_setup$T(props, ctx) : void 0;
};
const VPSwitchAppearance = /* @__PURE__ */ _export_sfc(_sfc_main$T, [["__scopeId", "data-v-5337faa4"]]);
const _sfc_main$S = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarAppearance",
  __ssrInlineRender: true,
  setup(__props) {
    const { site } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(site).appearance && unref(site).appearance !== "force-dark" && unref(site).appearance !== "force-auto") {
        _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPNavBarAppearance" }, _attrs))} data-v-6c893767>`);
        _push(ssrRenderComponent(VPSwitchAppearance, null, null, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$S = _sfc_main$S.setup;
_sfc_main$S.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarAppearance.vue");
  return _sfc_setup$S ? _sfc_setup$S(props, ctx) : void 0;
};
const VPNavBarAppearance = /* @__PURE__ */ _export_sfc(_sfc_main$S, [["__scopeId", "data-v-6c893767"]]);
const focusedElement = ref();
let active = false;
let listeners = 0;
function useFlyout(options) {
  const focus = ref(false);
  if (inBrowser) {
    !active && activateFocusTracking();
    listeners++;
    const unwatch = watch(focusedElement, (el) => {
      var _a, _b, _c;
      if (el === options.el.value || ((_a = options.el.value) == null ? void 0 : _a.contains(el))) {
        focus.value = true;
        (_b = options.onFocus) == null ? void 0 : _b.call(options);
      } else {
        focus.value = false;
        (_c = options.onBlur) == null ? void 0 : _c.call(options);
      }
    });
    onUnmounted(() => {
      unwatch();
      listeners--;
      if (!listeners) {
        deactivateFocusTracking();
      }
    });
  }
  return readonly(focus);
}
function activateFocusTracking() {
  document.addEventListener("focusin", handleFocusIn);
  active = true;
  focusedElement.value = document.activeElement;
}
function deactivateFocusTracking() {
  document.removeEventListener("focusin", handleFocusIn);
}
function handleFocusIn() {
  focusedElement.value = document.activeElement;
}
const _sfc_main$R = /* @__PURE__ */ defineComponent({
  __name: "VPMenuLink",
  __ssrInlineRender: true,
  props: {
    item: {}
  },
  setup(__props) {
    const { page } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPMenuLink" }, _attrs))} data-v-35975db6>`);
      _push(ssrRenderComponent(_sfc_main$1a, {
        class: {
          active: unref(isActive)(
            unref(page).relativePath,
            __props.item.activeMatch || __props.item.link,
            !!__props.item.activeMatch
          )
        },
        href: __props.item.link,
        target: __props.item.target,
        rel: __props.item.rel,
        "no-icon": __props.item.noIcon
      }, {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<span data-v-35975db6${_scopeId}>${__props.item.text ?? ""}</span>`);
          } else {
            return [
              createVNode("span", {
                innerHTML: __props.item.text
              }, null, 8, ["innerHTML"])
            ];
          }
        }),
        _: 1
      }, _parent));
      _push(`</div>`);
    };
  }
});
const _sfc_setup$R = _sfc_main$R.setup;
_sfc_main$R.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPMenuLink.vue");
  return _sfc_setup$R ? _sfc_setup$R(props, ctx) : void 0;
};
const VPMenuLink = /* @__PURE__ */ _export_sfc(_sfc_main$R, [["__scopeId", "data-v-35975db6"]]);
const _sfc_main$Q = /* @__PURE__ */ defineComponent({
  __name: "VPMenuGroup",
  __ssrInlineRender: true,
  props: {
    text: {},
    items: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPMenuGroup" }, _attrs))} data-v-69e747b5>`);
      if (__props.text) {
        _push(`<p class="title" data-v-69e747b5>${ssrInterpolate(__props.text)}</p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<!--[-->`);
      ssrRenderList(__props.items, (item) => {
        _push(`<!--[-->`);
        if ("link" in item) {
          _push(ssrRenderComponent(VPMenuLink, { item }, null, _parent));
        } else {
          _push(`<!---->`);
        }
        _push(`<!--]-->`);
      });
      _push(`<!--]--></div>`);
    };
  }
});
const _sfc_setup$Q = _sfc_main$Q.setup;
_sfc_main$Q.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPMenuGroup.vue");
  return _sfc_setup$Q ? _sfc_setup$Q(props, ctx) : void 0;
};
const VPMenuGroup = /* @__PURE__ */ _export_sfc(_sfc_main$Q, [["__scopeId", "data-v-69e747b5"]]);
const _sfc_main$P = /* @__PURE__ */ defineComponent({
  __name: "VPMenu",
  __ssrInlineRender: true,
  props: {
    items: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPMenu" }, _attrs))} data-v-b98bc113>`);
      if (__props.items) {
        _push(`<div class="items" data-v-b98bc113><!--[-->`);
        ssrRenderList(__props.items, (item) => {
          _push(`<!--[-->`);
          if ("link" in item) {
            _push(ssrRenderComponent(VPMenuLink, { item }, null, _parent));
          } else if ("component" in item) {
            ssrRenderVNode(_push, createVNode(resolveDynamicComponent(item.component), mergeProps({ ref_for: true }, item.props), null), _parent);
          } else {
            _push(ssrRenderComponent(VPMenuGroup, {
              text: item.text,
              items: item.items
            }, null, _parent));
          }
          _push(`<!--]-->`);
        });
        _push(`<!--]--></div>`);
      } else {
        _push(`<!---->`);
      }
      ssrRenderSlot(_ctx.$slots, "default", {}, null, _push, _parent);
      _push(`</div>`);
    };
  }
});
const _sfc_setup$P = _sfc_main$P.setup;
_sfc_main$P.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPMenu.vue");
  return _sfc_setup$P ? _sfc_setup$P(props, ctx) : void 0;
};
const VPMenu = /* @__PURE__ */ _export_sfc(_sfc_main$P, [["__scopeId", "data-v-b98bc113"]]);
const _sfc_main$O = /* @__PURE__ */ defineComponent({
  __name: "VPFlyout",
  __ssrInlineRender: true,
  props: {
    icon: {},
    button: {},
    label: {},
    items: {}
  },
  setup(__props) {
    const open = ref(false);
    const el = ref();
    useFlyout({ el, onBlur });
    function onBlur() {
      open.value = false;
    }
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: "VPFlyout",
        ref_key: "el",
        ref: el
      }, _attrs))} data-v-cf11d7a2><button type="button" class="button" aria-haspopup="true"${ssrRenderAttr("aria-expanded", open.value)}${ssrRenderAttr("aria-label", __props.label)} data-v-cf11d7a2>`);
      if (__props.button || __props.icon) {
        _push(`<span class="text" data-v-cf11d7a2>`);
        if (__props.icon) {
          _push(`<span class="${ssrRenderClass([__props.icon, "option-icon"])}" data-v-cf11d7a2></span>`);
        } else {
          _push(`<!---->`);
        }
        if (__props.button) {
          _push(`<span data-v-cf11d7a2>${__props.button ?? ""}</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<span class="vpi-chevron-down text-icon" data-v-cf11d7a2></span></span>`);
      } else {
        _push(`<span class="vpi-more-horizontal icon" data-v-cf11d7a2></span>`);
      }
      _push(`</button><div class="menu" data-v-cf11d7a2>`);
      _push(ssrRenderComponent(VPMenu, { items: __props.items }, {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "default", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "default", {}, void 0, true)
            ];
          }
        }),
        _: 3
      }, _parent));
      _push(`</div></div>`);
    };
  }
});
const _sfc_setup$O = _sfc_main$O.setup;
_sfc_main$O.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPFlyout.vue");
  return _sfc_setup$O ? _sfc_setup$O(props, ctx) : void 0;
};
const VPFlyout = /* @__PURE__ */ _export_sfc(_sfc_main$O, [["__scopeId", "data-v-cf11d7a2"]]);
const _sfc_main$N = /* @__PURE__ */ defineComponent({
  __name: "VPSocialLink",
  __ssrInlineRender: true,
  props: {
    icon: {},
    link: {},
    ariaLabel: {}
  },
  setup(__props) {
    var _a;
    const props = __props;
    const el = ref();
    onMounted(async () => {
      var _a2;
      await nextTick();
      const span = (_a2 = el.value) == null ? void 0 : _a2.children[0];
      if (span instanceof HTMLElement && span.className.startsWith("vpi-social-") && (getComputedStyle(span).maskImage || getComputedStyle(span).webkitMaskImage) === "none") {
        span.style.setProperty(
          "--icon",
          `url('https://api.iconify.design/simple-icons/${props.icon}.svg')`
        );
      }
    });
    const svg = computed(() => {
      if (typeof props.icon === "object") return props.icon.svg;
      return `<span class="vpi-social-${props.icon}"></span>`;
    });
    {
      typeof props.icon === "string" && ((_a = useSSRContext()) == null ? void 0 : _a.vpSocialIcons.add(props.icon));
    }
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<a${ssrRenderAttrs(mergeProps({
        ref_key: "el",
        ref: el,
        class: "VPSocialLink no-icon",
        href: __props.link,
        "aria-label": __props.ariaLabel ?? (typeof __props.icon === "string" ? __props.icon : ""),
        target: "_blank",
        rel: "noopener"
      }, _attrs))} data-v-bd121fe5>${svg.value ?? ""}</a>`);
    };
  }
});
const _sfc_setup$N = _sfc_main$N.setup;
_sfc_main$N.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSocialLink.vue");
  return _sfc_setup$N ? _sfc_setup$N(props, ctx) : void 0;
};
const VPSocialLink = /* @__PURE__ */ _export_sfc(_sfc_main$N, [["__scopeId", "data-v-bd121fe5"]]);
const _sfc_main$M = /* @__PURE__ */ defineComponent({
  __name: "VPSocialLinks",
  __ssrInlineRender: true,
  props: {
    links: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPSocialLinks" }, _attrs))} data-v-7bc22406><!--[-->`);
      ssrRenderList(__props.links, ({ link: link2, icon, ariaLabel }) => {
        _push(ssrRenderComponent(VPSocialLink, {
          key: link2,
          icon,
          link: link2,
          ariaLabel
        }, null, _parent));
      });
      _push(`<!--]--></div>`);
    };
  }
});
const _sfc_setup$M = _sfc_main$M.setup;
_sfc_main$M.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSocialLinks.vue");
  return _sfc_setup$M ? _sfc_setup$M(props, ctx) : void 0;
};
const VPSocialLinks = /* @__PURE__ */ _export_sfc(_sfc_main$M, [["__scopeId", "data-v-7bc22406"]]);
const _sfc_main$L = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarExtra",
  __ssrInlineRender: true,
  setup(__props) {
    const { site, theme: theme2 } = useData();
    const { localeLinks, currentLang } = useLangs({ correspondingLink: true });
    const hasExtraContent = computed(
      () => localeLinks.value.length && currentLang.value.label || site.value.appearance || theme2.value.socialLinks
    );
    return (_ctx, _push, _parent, _attrs) => {
      if (hasExtraContent.value) {
        _push(ssrRenderComponent(VPFlyout, mergeProps({
          class: "VPNavBarExtra",
          label: "extra navigation"
        }, _attrs), {
          default: withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              if (unref(localeLinks).length && unref(currentLang).label) {
                _push2(`<div class="group translations" data-v-bb2aa2f0${_scopeId}><p class="trans-title" data-v-bb2aa2f0${_scopeId}>${ssrInterpolate(unref(currentLang).label)}</p><!--[-->`);
                ssrRenderList(unref(localeLinks), (locale) => {
                  _push2(ssrRenderComponent(VPMenuLink, { item: locale }, null, _parent2, _scopeId));
                });
                _push2(`<!--]--></div>`);
              } else {
                _push2(`<!---->`);
              }
              if (unref(site).appearance && unref(site).appearance !== "force-dark" && unref(site).appearance !== "force-auto") {
                _push2(`<div class="group" data-v-bb2aa2f0${_scopeId}><div class="item appearance" data-v-bb2aa2f0${_scopeId}><p class="label" data-v-bb2aa2f0${_scopeId}>${ssrInterpolate(unref(theme2).darkModeSwitchLabel || "Appearance")}</p><div class="appearance-action" data-v-bb2aa2f0${_scopeId}>`);
                _push2(ssrRenderComponent(VPSwitchAppearance, null, null, _parent2, _scopeId));
                _push2(`</div></div></div>`);
              } else {
                _push2(`<!---->`);
              }
              if (unref(theme2).socialLinks) {
                _push2(`<div class="group" data-v-bb2aa2f0${_scopeId}><div class="item social-links" data-v-bb2aa2f0${_scopeId}>`);
                _push2(ssrRenderComponent(VPSocialLinks, {
                  class: "social-links-list",
                  links: unref(theme2).socialLinks
                }, null, _parent2, _scopeId));
                _push2(`</div></div>`);
              } else {
                _push2(`<!---->`);
              }
            } else {
              return [
                unref(localeLinks).length && unref(currentLang).label ? (openBlock(), createBlock("div", {
                  key: 0,
                  class: "group translations"
                }, [
                  createVNode("p", { class: "trans-title" }, toDisplayString(unref(currentLang).label), 1),
                  (openBlock(true), createBlock(Fragment, null, renderList(unref(localeLinks), (locale) => {
                    return openBlock(), createBlock(VPMenuLink, {
                      key: locale.link,
                      item: locale
                    }, null, 8, ["item"]);
                  }), 128))
                ])) : createCommentVNode("", true),
                unref(site).appearance && unref(site).appearance !== "force-dark" && unref(site).appearance !== "force-auto" ? (openBlock(), createBlock("div", {
                  key: 1,
                  class: "group"
                }, [
                  createVNode("div", { class: "item appearance" }, [
                    createVNode("p", { class: "label" }, toDisplayString(unref(theme2).darkModeSwitchLabel || "Appearance"), 1),
                    createVNode("div", { class: "appearance-action" }, [
                      createVNode(VPSwitchAppearance)
                    ])
                  ])
                ])) : createCommentVNode("", true),
                unref(theme2).socialLinks ? (openBlock(), createBlock("div", {
                  key: 2,
                  class: "group"
                }, [
                  createVNode("div", { class: "item social-links" }, [
                    createVNode(VPSocialLinks, {
                      class: "social-links-list",
                      links: unref(theme2).socialLinks
                    }, null, 8, ["links"])
                  ])
                ])) : createCommentVNode("", true)
              ];
            }
          }),
          _: 1
        }, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$L = _sfc_main$L.setup;
_sfc_main$L.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarExtra.vue");
  return _sfc_setup$L ? _sfc_setup$L(props, ctx) : void 0;
};
const VPNavBarExtra = /* @__PURE__ */ _export_sfc(_sfc_main$L, [["__scopeId", "data-v-bb2aa2f0"]]);
const _sfc_main$K = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarHamburger",
  __ssrInlineRender: true,
  props: {
    active: { type: Boolean }
  },
  emits: ["click"],
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<button${ssrRenderAttrs(mergeProps({
        type: "button",
        class: ["VPNavBarHamburger", { active: __props.active }],
        "aria-label": "mobile navigation",
        "aria-expanded": __props.active,
        "aria-controls": "VPNavScreen"
      }, _attrs))} data-v-e5dd9c1c><span class="container" data-v-e5dd9c1c><span class="top" data-v-e5dd9c1c></span><span class="middle" data-v-e5dd9c1c></span><span class="bottom" data-v-e5dd9c1c></span></span></button>`);
    };
  }
});
const _sfc_setup$K = _sfc_main$K.setup;
_sfc_main$K.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarHamburger.vue");
  return _sfc_setup$K ? _sfc_setup$K(props, ctx) : void 0;
};
const VPNavBarHamburger = /* @__PURE__ */ _export_sfc(_sfc_main$K, [["__scopeId", "data-v-e5dd9c1c"]]);
const _sfc_main$J = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarMenuLink",
  __ssrInlineRender: true,
  props: {
    item: {}
  },
  setup(__props) {
    const { page } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(_sfc_main$1a, mergeProps({
        class: {
          VPNavBarMenuLink: true,
          active: unref(isActive)(
            unref(page).relativePath,
            __props.item.activeMatch || __props.item.link,
            !!__props.item.activeMatch
          )
        },
        href: __props.item.link,
        target: __props.item.target,
        rel: __props.item.rel,
        "no-icon": __props.item.noIcon,
        tabindex: "0"
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<span data-v-e56f3d57${_scopeId}>${__props.item.text ?? ""}</span>`);
          } else {
            return [
              createVNode("span", {
                innerHTML: __props.item.text
              }, null, 8, ["innerHTML"])
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$J = _sfc_main$J.setup;
_sfc_main$J.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarMenuLink.vue");
  return _sfc_setup$J ? _sfc_setup$J(props, ctx) : void 0;
};
const VPNavBarMenuLink = /* @__PURE__ */ _export_sfc(_sfc_main$J, [["__scopeId", "data-v-e56f3d57"]]);
const _sfc_main$I = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarMenuGroup",
  __ssrInlineRender: true,
  props: {
    item: {}
  },
  setup(__props) {
    const props = __props;
    const { page } = useData();
    const isChildActive = (navItem) => {
      if ("component" in navItem) return false;
      if ("link" in navItem) {
        return isActive(
          page.value.relativePath,
          navItem.link,
          !!props.item.activeMatch
        );
      }
      return navItem.items.some(isChildActive);
    };
    const childrenActive = computed(() => isChildActive(props.item));
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(VPFlyout, mergeProps({
        class: {
          VPNavBarMenuGroup: true,
          active: unref(isActive)(unref(page).relativePath, __props.item.activeMatch, !!__props.item.activeMatch) || childrenActive.value
        },
        button: __props.item.text,
        items: __props.item.items
      }, _attrs), null, _parent));
    };
  }
});
const _sfc_setup$I = _sfc_main$I.setup;
_sfc_main$I.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarMenuGroup.vue");
  return _sfc_setup$I ? _sfc_setup$I(props, ctx) : void 0;
};
const _sfc_main$H = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarMenu",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(theme2).nav) {
        _push(`<nav${ssrRenderAttrs(mergeProps({
          "aria-labelledby": "main-nav-aria-label",
          class: "VPNavBarMenu"
        }, _attrs))} data-v-dc692963><span id="main-nav-aria-label" class="visually-hidden" data-v-dc692963> Main Navigation </span><!--[-->`);
        ssrRenderList(unref(theme2).nav, (item) => {
          _push(`<!--[-->`);
          if ("link" in item) {
            _push(ssrRenderComponent(VPNavBarMenuLink, { item }, null, _parent));
          } else if ("component" in item) {
            ssrRenderVNode(_push, createVNode(resolveDynamicComponent(item.component), mergeProps({ ref_for: true }, item.props), null), _parent);
          } else {
            _push(ssrRenderComponent(_sfc_main$I, { item }, null, _parent));
          }
          _push(`<!--]-->`);
        });
        _push(`<!--]--></nav>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$H = _sfc_main$H.setup;
_sfc_main$H.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarMenu.vue");
  return _sfc_setup$H ? _sfc_setup$H(props, ctx) : void 0;
};
const VPNavBarMenu = /* @__PURE__ */ _export_sfc(_sfc_main$H, [["__scopeId", "data-v-dc692963"]]);
function createSearchTranslate(defaultTranslations) {
  const { localeIndex, theme: theme2 } = useData();
  function translate(key) {
    var _a, _b, _c;
    const keyPath = key.split(".");
    const themeObject = (_a = theme2.value.search) == null ? void 0 : _a.options;
    const isObject = themeObject && typeof themeObject === "object";
    const locales = isObject && ((_c = (_b = themeObject.locales) == null ? void 0 : _b[localeIndex.value]) == null ? void 0 : _c.translations) || null;
    const translations = isObject && themeObject.translations || null;
    let localeResult = locales;
    let translationResult = translations;
    let defaultResult = defaultTranslations;
    const lastKey = keyPath.pop();
    for (const k2 of keyPath) {
      let fallbackResult = null;
      const foundInFallback = defaultResult == null ? void 0 : defaultResult[k2];
      if (foundInFallback) {
        fallbackResult = defaultResult = foundInFallback;
      }
      const foundInTranslation = translationResult == null ? void 0 : translationResult[k2];
      if (foundInTranslation) {
        fallbackResult = translationResult = foundInTranslation;
      }
      const foundInLocale = localeResult == null ? void 0 : localeResult[k2];
      if (foundInLocale) {
        fallbackResult = localeResult = foundInLocale;
      }
      if (!foundInFallback) {
        defaultResult = fallbackResult;
      }
      if (!foundInTranslation) {
        translationResult = fallbackResult;
      }
      if (!foundInLocale) {
        localeResult = fallbackResult;
      }
    }
    return (localeResult == null ? void 0 : localeResult[lastKey]) ?? (translationResult == null ? void 0 : translationResult[lastKey]) ?? (defaultResult == null ? void 0 : defaultResult[lastKey]) ?? "";
  }
  return translate;
}
const _sfc_main$G = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarSearchButton",
  __ssrInlineRender: true,
  setup(__props) {
    const defaultTranslations = {
      button: {
        buttonText: "Search",
        buttonAriaLabel: "Search"
      }
    };
    const translate = createSearchTranslate(defaultTranslations);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<button${ssrRenderAttrs(mergeProps({
        type: "button",
        class: "DocSearch DocSearch-Button",
        "aria-label": unref(translate)("button.buttonAriaLabel")
      }, _attrs))}><span class="DocSearch-Button-Container"><span class="vp-icon DocSearch-Search-Icon"></span><span class="DocSearch-Button-Placeholder">${ssrInterpolate(unref(translate)("button.buttonText"))}</span></span><span class="DocSearch-Button-Keys"><kbd class="DocSearch-Button-Key"></kbd><kbd class="DocSearch-Button-Key">K</kbd></span></button>`);
    };
  }
});
const _sfc_setup$G = _sfc_main$G.setup;
_sfc_main$G.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarSearchButton.vue");
  return _sfc_setup$G ? _sfc_setup$G(props, ctx) : void 0;
};
const _sfc_main$F = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarSearch",
  __ssrInlineRender: true,
  setup(__props) {
    const VPLocalSearchBox = defineAsyncComponent(() => import("./VPLocalSearchBox.XRAzFkE3.js"));
    const VPAlgoliaSearchBox = () => null;
    const { theme: theme2 } = useData();
    const loaded = ref(false);
    const actuallyLoaded = ref(false);
    onMounted(() => {
      {
        return;
      }
    });
    function load() {
      if (!loaded.value) {
        loaded.value = true;
        setTimeout(poll, 16);
      }
    }
    function poll() {
      const e = new Event("keydown");
      e.key = "k";
      e.metaKey = true;
      window.dispatchEvent(e);
      setTimeout(() => {
        if (!document.querySelector(".DocSearch-Modal")) {
          poll();
        }
      }, 16);
    }
    function isEditingContent(event) {
      const element = event.target;
      const tagName = element.tagName;
      return element.isContentEditable || tagName === "INPUT" || tagName === "SELECT" || tagName === "TEXTAREA";
    }
    const showSearch = ref(false);
    {
      onKeyStroke("k", (event) => {
        if (event.ctrlKey || event.metaKey) {
          event.preventDefault();
          showSearch.value = true;
        }
      });
      onKeyStroke("/", (event) => {
        if (!isEditingContent(event)) {
          event.preventDefault();
          showSearch.value = true;
        }
      });
    }
    const provider = "local";
    return (_ctx, _push, _parent, _attrs) => {
      var _a;
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPNavBarSearch" }, _attrs))}>`);
      if (unref(provider) === "local") {
        _push(`<!--[-->`);
        if (showSearch.value) {
          _push(ssrRenderComponent(unref(VPLocalSearchBox), {
            onClose: ($event) => showSearch.value = false
          }, null, _parent));
        } else {
          _push(`<!---->`);
        }
        _push(`<div id="local-search">`);
        _push(ssrRenderComponent(_sfc_main$G, {
          onClick: ($event) => showSearch.value = true
        }, null, _parent));
        _push(`</div><!--]-->`);
      } else if (unref(provider) === "algolia") {
        _push(`<!--[-->`);
        if (loaded.value) {
          _push(ssrRenderComponent(unref(VPAlgoliaSearchBox), {
            algolia: ((_a = unref(theme2).search) == null ? void 0 : _a.options) ?? unref(theme2).algolia,
            onVnodeBeforeMount: ($event) => actuallyLoaded.value = true
          }, null, _parent));
        } else {
          _push(`<!---->`);
        }
        if (!actuallyLoaded.value) {
          _push(`<div id="docsearch">`);
          _push(ssrRenderComponent(_sfc_main$G, { onClick: load }, null, _parent));
          _push(`</div>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<!--]-->`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div>`);
    };
  }
});
const _sfc_setup$F = _sfc_main$F.setup;
_sfc_main$F.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarSearch.vue");
  return _sfc_setup$F ? _sfc_setup$F(props, ctx) : void 0;
};
const _sfc_main$E = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarSocialLinks",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(theme2).socialLinks) {
        _push(ssrRenderComponent(VPSocialLinks, mergeProps({
          class: "VPNavBarSocialLinks",
          links: unref(theme2).socialLinks
        }, _attrs), null, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$E = _sfc_main$E.setup;
_sfc_main$E.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarSocialLinks.vue");
  return _sfc_setup$E ? _sfc_setup$E(props, ctx) : void 0;
};
const VPNavBarSocialLinks = /* @__PURE__ */ _export_sfc(_sfc_main$E, [["__scopeId", "data-v-0394ad82"]]);
const _sfc_main$D = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarTitle",
  __ssrInlineRender: true,
  setup(__props) {
    const { site, theme: theme2 } = useData();
    const { hasSidebar } = useSidebar();
    const { currentLang } = useLangs();
    const link2 = computed(
      () => {
        var _a;
        return typeof theme2.value.logoLink === "string" ? theme2.value.logoLink : (_a = theme2.value.logoLink) == null ? void 0 : _a.link;
      }
    );
    const rel = computed(
      () => {
        var _a;
        return typeof theme2.value.logoLink === "string" ? void 0 : (_a = theme2.value.logoLink) == null ? void 0 : _a.rel;
      }
    );
    const target2 = computed(
      () => {
        var _a;
        return typeof theme2.value.logoLink === "string" ? void 0 : (_a = theme2.value.logoLink) == null ? void 0 : _a.target;
      }
    );
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPNavBarTitle", { "has-sidebar": unref(hasSidebar) }]
      }, _attrs))} data-v-1168a8e4><a class="title"${ssrRenderAttr("href", link2.value ?? unref(normalizeLink$1)(unref(currentLang).link))}${ssrRenderAttr("rel", rel.value)}${ssrRenderAttr("target", target2.value)} data-v-1168a8e4>`);
      ssrRenderSlot(_ctx.$slots, "nav-bar-title-before", {}, null, _push, _parent);
      if (unref(theme2).logo) {
        _push(ssrRenderComponent(VPImage, {
          class: "logo",
          image: unref(theme2).logo
        }, null, _parent));
      } else {
        _push(`<!---->`);
      }
      if (unref(theme2).siteTitle) {
        _push(`<span data-v-1168a8e4>${unref(theme2).siteTitle ?? ""}</span>`);
      } else if (unref(theme2).siteTitle === void 0) {
        _push(`<span data-v-1168a8e4>${ssrInterpolate(unref(site).title)}</span>`);
      } else {
        _push(`<!---->`);
      }
      ssrRenderSlot(_ctx.$slots, "nav-bar-title-after", {}, null, _push, _parent);
      _push(`</a></div>`);
    };
  }
});
const _sfc_setup$D = _sfc_main$D.setup;
_sfc_main$D.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarTitle.vue");
  return _sfc_setup$D ? _sfc_setup$D(props, ctx) : void 0;
};
const VPNavBarTitle = /* @__PURE__ */ _export_sfc(_sfc_main$D, [["__scopeId", "data-v-1168a8e4"]]);
const _sfc_main$C = /* @__PURE__ */ defineComponent({
  __name: "VPNavBarTranslations",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    const { localeLinks, currentLang } = useLangs({ correspondingLink: true });
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(localeLinks).length && unref(currentLang).label) {
        _push(ssrRenderComponent(VPFlyout, mergeProps({
          class: "VPNavBarTranslations",
          icon: "vpi-languages",
          label: unref(theme2).langMenuLabel || "Change language"
        }, _attrs), {
          default: withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              _push2(`<div class="items" data-v-88af2de4${_scopeId}><p class="title" data-v-88af2de4${_scopeId}>${ssrInterpolate(unref(currentLang).label)}</p><!--[-->`);
              ssrRenderList(unref(localeLinks), (locale) => {
                _push2(ssrRenderComponent(VPMenuLink, { item: locale }, null, _parent2, _scopeId));
              });
              _push2(`<!--]--></div>`);
            } else {
              return [
                createVNode("div", { class: "items" }, [
                  createVNode("p", { class: "title" }, toDisplayString(unref(currentLang).label), 1),
                  (openBlock(true), createBlock(Fragment, null, renderList(unref(localeLinks), (locale) => {
                    return openBlock(), createBlock(VPMenuLink, {
                      key: locale.link,
                      item: locale
                    }, null, 8, ["item"]);
                  }), 128))
                ])
              ];
            }
          }),
          _: 1
        }, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$C = _sfc_main$C.setup;
_sfc_main$C.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBarTranslations.vue");
  return _sfc_setup$C ? _sfc_setup$C(props, ctx) : void 0;
};
const VPNavBarTranslations = /* @__PURE__ */ _export_sfc(_sfc_main$C, [["__scopeId", "data-v-88af2de4"]]);
const _sfc_main$B = /* @__PURE__ */ defineComponent({
  __name: "VPNavBar",
  __ssrInlineRender: true,
  props: {
    isScreenOpen: { type: Boolean }
  },
  emits: ["toggle-screen"],
  setup(__props) {
    const props = __props;
    const { y } = useWindowScroll();
    const { hasSidebar } = useSidebar();
    const { frontmatter } = useData();
    const classes = ref({});
    watchPostEffect(() => {
      classes.value = {
        "has-sidebar": hasSidebar.value,
        "home": frontmatter.value.layout === "home",
        "top": y.value === 0,
        "screen-open": props.isScreenOpen
      };
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPNavBar", classes.value]
      }, _attrs))} data-v-6aa21345><div class="wrapper" data-v-6aa21345><div class="container" data-v-6aa21345><div class="title" data-v-6aa21345>`);
      _push(ssrRenderComponent(VPNavBarTitle, null, {
        "nav-bar-title-before": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "nav-bar-title-before", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "nav-bar-title-before", {}, void 0, true)
            ];
          }
        }),
        "nav-bar-title-after": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            ssrRenderSlot(_ctx.$slots, "nav-bar-title-after", {}, null, _push2, _parent2, _scopeId);
          } else {
            return [
              renderSlot(_ctx.$slots, "nav-bar-title-after", {}, void 0, true)
            ];
          }
        }),
        _: 3
      }, _parent));
      _push(`</div><div class="content" data-v-6aa21345><div class="content-body" data-v-6aa21345>`);
      ssrRenderSlot(_ctx.$slots, "nav-bar-content-before", {}, null, _push, _parent);
      _push(ssrRenderComponent(_sfc_main$F, { class: "search" }, null, _parent));
      _push(ssrRenderComponent(VPNavBarMenu, { class: "menu" }, null, _parent));
      _push(ssrRenderComponent(VPNavBarTranslations, { class: "translations" }, null, _parent));
      _push(ssrRenderComponent(VPNavBarAppearance, { class: "appearance" }, null, _parent));
      _push(ssrRenderComponent(VPNavBarSocialLinks, { class: "social-links" }, null, _parent));
      _push(ssrRenderComponent(VPNavBarExtra, { class: "extra" }, null, _parent));
      ssrRenderSlot(_ctx.$slots, "nav-bar-content-after", {}, null, _push, _parent);
      _push(ssrRenderComponent(VPNavBarHamburger, {
        class: "hamburger",
        active: __props.isScreenOpen,
        onClick: ($event) => _ctx.$emit("toggle-screen")
      }, null, _parent));
      _push(`</div></div></div></div><div class="divider" data-v-6aa21345><div class="divider-line" data-v-6aa21345></div></div></div>`);
    };
  }
});
const _sfc_setup$B = _sfc_main$B.setup;
_sfc_main$B.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavBar.vue");
  return _sfc_setup$B ? _sfc_setup$B(props, ctx) : void 0;
};
const VPNavBar = /* @__PURE__ */ _export_sfc(_sfc_main$B, [["__scopeId", "data-v-6aa21345"]]);
const _sfc_main$A = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenAppearance",
  __ssrInlineRender: true,
  setup(__props) {
    const { site, theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(site).appearance && unref(site).appearance !== "force-dark" && unref(site).appearance !== "force-auto") {
        _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPNavScreenAppearance" }, _attrs))} data-v-b44890b2><p class="text" data-v-b44890b2>${ssrInterpolate(unref(theme2).darkModeSwitchLabel || "Appearance")}</p>`);
        _push(ssrRenderComponent(VPSwitchAppearance, null, null, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$A = _sfc_main$A.setup;
_sfc_main$A.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenAppearance.vue");
  return _sfc_setup$A ? _sfc_setup$A(props, ctx) : void 0;
};
const VPNavScreenAppearance = /* @__PURE__ */ _export_sfc(_sfc_main$A, [["__scopeId", "data-v-b44890b2"]]);
const _sfc_main$z = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenMenuLink",
  __ssrInlineRender: true,
  props: {
    item: {}
  },
  setup(__props) {
    const closeScreen = inject("close-screen");
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(_sfc_main$1a, mergeProps({
        class: "VPNavScreenMenuLink",
        href: __props.item.link,
        target: __props.item.target,
        rel: __props.item.rel,
        "no-icon": __props.item.noIcon,
        onClick: unref(closeScreen)
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<span data-v-df37e6dd${_scopeId}>${__props.item.text ?? ""}</span>`);
          } else {
            return [
              createVNode("span", {
                innerHTML: __props.item.text
              }, null, 8, ["innerHTML"])
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$z = _sfc_main$z.setup;
_sfc_main$z.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenMenuLink.vue");
  return _sfc_setup$z ? _sfc_setup$z(props, ctx) : void 0;
};
const VPNavScreenMenuLink = /* @__PURE__ */ _export_sfc(_sfc_main$z, [["__scopeId", "data-v-df37e6dd"]]);
const _sfc_main$y = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenMenuGroupLink",
  __ssrInlineRender: true,
  props: {
    item: {}
  },
  setup(__props) {
    const closeScreen = inject("close-screen");
    return (_ctx, _push, _parent, _attrs) => {
      _push(ssrRenderComponent(_sfc_main$1a, mergeProps({
        class: "VPNavScreenMenuGroupLink",
        href: __props.item.link,
        target: __props.item.target,
        rel: __props.item.rel,
        "no-icon": __props.item.noIcon,
        onClick: unref(closeScreen)
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(`<span data-v-3e9c20e4${_scopeId}>${__props.item.text ?? ""}</span>`);
          } else {
            return [
              createVNode("span", {
                innerHTML: __props.item.text
              }, null, 8, ["innerHTML"])
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$y = _sfc_main$y.setup;
_sfc_main$y.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenMenuGroupLink.vue");
  return _sfc_setup$y ? _sfc_setup$y(props, ctx) : void 0;
};
const VPNavScreenMenuGroupLink = /* @__PURE__ */ _export_sfc(_sfc_main$y, [["__scopeId", "data-v-3e9c20e4"]]);
const _sfc_main$x = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenMenuGroupSection",
  __ssrInlineRender: true,
  props: {
    text: {},
    items: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPNavScreenMenuGroupSection" }, _attrs))} data-v-8133b170>`);
      if (__props.text) {
        _push(`<p class="title" data-v-8133b170>${ssrInterpolate(__props.text)}</p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<!--[-->`);
      ssrRenderList(__props.items, (item) => {
        _push(ssrRenderComponent(VPNavScreenMenuGroupLink, {
          key: item.text,
          item
        }, null, _parent));
      });
      _push(`<!--]--></div>`);
    };
  }
});
const _sfc_setup$x = _sfc_main$x.setup;
_sfc_main$x.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenMenuGroupSection.vue");
  return _sfc_setup$x ? _sfc_setup$x(props, ctx) : void 0;
};
const VPNavScreenMenuGroupSection = /* @__PURE__ */ _export_sfc(_sfc_main$x, [["__scopeId", "data-v-8133b170"]]);
const _sfc_main$w = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenMenuGroup",
  __ssrInlineRender: true,
  props: {
    text: {},
    items: {}
  },
  setup(__props) {
    const props = __props;
    const isOpen = ref(false);
    const groupId = computed(
      () => `NavScreenGroup-${props.text.replace(" ", "-").toLowerCase()}`
    );
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPNavScreenMenuGroup", { open: isOpen.value }]
      }, _attrs))} data-v-b9ab8c58><button class="button"${ssrRenderAttr("aria-controls", groupId.value)}${ssrRenderAttr("aria-expanded", isOpen.value)} data-v-b9ab8c58><span class="button-text" data-v-b9ab8c58>${__props.text ?? ""}</span><span class="vpi-plus button-icon" data-v-b9ab8c58></span></button><div${ssrRenderAttr("id", groupId.value)} class="items" data-v-b9ab8c58><!--[-->`);
      ssrRenderList(__props.items, (item) => {
        _push(`<!--[-->`);
        if ("link" in item) {
          _push(`<div class="item" data-v-b9ab8c58>`);
          _push(ssrRenderComponent(VPNavScreenMenuGroupLink, { item }, null, _parent));
          _push(`</div>`);
        } else if ("component" in item) {
          _push(`<div class="item" data-v-b9ab8c58>`);
          ssrRenderVNode(_push, createVNode(resolveDynamicComponent(item.component), mergeProps({ ref_for: true }, item.props, { "screen-menu": "" }), null), _parent);
          _push(`</div>`);
        } else {
          _push(`<div class="group" data-v-b9ab8c58>`);
          _push(ssrRenderComponent(VPNavScreenMenuGroupSection, {
            text: item.text,
            items: item.items
          }, null, _parent));
          _push(`</div>`);
        }
        _push(`<!--]-->`);
      });
      _push(`<!--]--></div></div>`);
    };
  }
});
const _sfc_setup$w = _sfc_main$w.setup;
_sfc_main$w.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenMenuGroup.vue");
  return _sfc_setup$w ? _sfc_setup$w(props, ctx) : void 0;
};
const VPNavScreenMenuGroup = /* @__PURE__ */ _export_sfc(_sfc_main$w, [["__scopeId", "data-v-b9ab8c58"]]);
const _sfc_main$v = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenMenu",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(theme2).nav) {
        _push(`<nav${ssrRenderAttrs(mergeProps({ class: "VPNavScreenMenu" }, _attrs))}><!--[-->`);
        ssrRenderList(unref(theme2).nav, (item) => {
          _push(`<!--[-->`);
          if ("link" in item) {
            _push(ssrRenderComponent(VPNavScreenMenuLink, { item }, null, _parent));
          } else if ("component" in item) {
            ssrRenderVNode(_push, createVNode(resolveDynamicComponent(item.component), mergeProps({ ref_for: true }, item.props, { "screen-menu": "" }), null), _parent);
          } else {
            _push(ssrRenderComponent(VPNavScreenMenuGroup, {
              text: item.text || "",
              items: item.items
            }, null, _parent));
          }
          _push(`<!--]-->`);
        });
        _push(`<!--]--></nav>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$v = _sfc_main$v.setup;
_sfc_main$v.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenMenu.vue");
  return _sfc_setup$v ? _sfc_setup$v(props, ctx) : void 0;
};
const _sfc_main$u = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenSocialLinks",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(theme2).socialLinks) {
        _push(ssrRenderComponent(VPSocialLinks, mergeProps({
          class: "VPNavScreenSocialLinks",
          links: unref(theme2).socialLinks
        }, _attrs), null, _parent));
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$u = _sfc_main$u.setup;
_sfc_main$u.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenSocialLinks.vue");
  return _sfc_setup$u ? _sfc_setup$u(props, ctx) : void 0;
};
const _sfc_main$t = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreenTranslations",
  __ssrInlineRender: true,
  setup(__props) {
    const { localeLinks, currentLang } = useLangs({ correspondingLink: true });
    const isOpen = ref(false);
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(localeLinks).length && unref(currentLang).label) {
        _push(`<div${ssrRenderAttrs(mergeProps({
          class: ["VPNavScreenTranslations", { open: isOpen.value }]
        }, _attrs))} data-v-858fe1a4><button class="title" data-v-858fe1a4><span class="vpi-languages icon lang" data-v-858fe1a4></span> ${ssrInterpolate(unref(currentLang).label)} <span class="vpi-chevron-down icon chevron" data-v-858fe1a4></span></button><ul class="list" data-v-858fe1a4><!--[-->`);
        ssrRenderList(unref(localeLinks), (locale) => {
          _push(`<li class="item" data-v-858fe1a4>`);
          _push(ssrRenderComponent(_sfc_main$1a, {
            class: "link",
            href: locale.link
          }, {
            default: withCtx((_, _push2, _parent2, _scopeId) => {
              if (_push2) {
                _push2(`${ssrInterpolate(locale.text)}`);
              } else {
                return [
                  createTextVNode(toDisplayString(locale.text), 1)
                ];
              }
            }),
            _: 2
          }, _parent));
          _push(`</li>`);
        });
        _push(`<!--]--></ul></div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$t = _sfc_main$t.setup;
_sfc_main$t.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreenTranslations.vue");
  return _sfc_setup$t ? _sfc_setup$t(props, ctx) : void 0;
};
const VPNavScreenTranslations = /* @__PURE__ */ _export_sfc(_sfc_main$t, [["__scopeId", "data-v-858fe1a4"]]);
const _sfc_main$s = /* @__PURE__ */ defineComponent({
  __name: "VPNavScreen",
  __ssrInlineRender: true,
  props: {
    open: { type: Boolean }
  },
  setup(__props) {
    const screen = ref(null);
    useScrollLock(inBrowser ? document.body : null);
    return (_ctx, _push, _parent, _attrs) => {
      if (__props.open) {
        _push(`<div${ssrRenderAttrs(mergeProps({
          class: "VPNavScreen",
          ref_key: "screen",
          ref: screen,
          id: "VPNavScreen"
        }, _attrs))} data-v-f2779853><div class="container" data-v-f2779853>`);
        ssrRenderSlot(_ctx.$slots, "nav-screen-content-before", {}, null, _push, _parent);
        _push(ssrRenderComponent(_sfc_main$v, { class: "menu" }, null, _parent));
        _push(ssrRenderComponent(VPNavScreenTranslations, { class: "translations" }, null, _parent));
        _push(ssrRenderComponent(VPNavScreenAppearance, { class: "appearance" }, null, _parent));
        _push(ssrRenderComponent(_sfc_main$u, { class: "social-links" }, null, _parent));
        ssrRenderSlot(_ctx.$slots, "nav-screen-content-after", {}, null, _push, _parent);
        _push(`</div></div>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$s = _sfc_main$s.setup;
_sfc_main$s.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNavScreen.vue");
  return _sfc_setup$s ? _sfc_setup$s(props, ctx) : void 0;
};
const VPNavScreen = /* @__PURE__ */ _export_sfc(_sfc_main$s, [["__scopeId", "data-v-f2779853"]]);
const _sfc_main$r = /* @__PURE__ */ defineComponent({
  __name: "VPNav",
  __ssrInlineRender: true,
  setup(__props) {
    const { isScreenOpen, closeScreen, toggleScreen } = useNav();
    const { frontmatter } = useData();
    const hasNavbar = computed(() => {
      return frontmatter.value.navbar !== false;
    });
    provide("close-screen", closeScreen);
    watchEffect(() => {
      if (inBrowser) {
        document.documentElement.classList.toggle("hide-nav", !hasNavbar.value);
      }
    });
    return (_ctx, _push, _parent, _attrs) => {
      if (hasNavbar.value) {
        _push(`<header${ssrRenderAttrs(mergeProps({ class: "VPNav" }, _attrs))} data-v-ae24b3ad>`);
        _push(ssrRenderComponent(VPNavBar, {
          "is-screen-open": unref(isScreenOpen),
          onToggleScreen: unref(toggleScreen)
        }, {
          "nav-bar-title-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-title-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-title-before", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-title-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-title-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-title-after", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-content-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-content-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-content-before", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-content-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-content-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-content-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(ssrRenderComponent(VPNavScreen, { open: unref(isScreenOpen) }, {
          "nav-screen-content-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-screen-content-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-screen-content-before", {}, void 0, true)
              ];
            }
          }),
          "nav-screen-content-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-screen-content-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-screen-content-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(`</header>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$r = _sfc_main$r.setup;
_sfc_main$r.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPNav.vue");
  return _sfc_setup$r ? _sfc_setup$r(props, ctx) : void 0;
};
const VPNav = /* @__PURE__ */ _export_sfc(_sfc_main$r, [["__scopeId", "data-v-ae24b3ad"]]);
const _sfc_main$q = /* @__PURE__ */ defineComponent({
  __name: "VPSidebarItem",
  __ssrInlineRender: true,
  props: {
    item: {},
    depth: {}
  },
  setup(__props) {
    const props = __props;
    const {
      collapsed,
      collapsible,
      isLink,
      isActiveLink,
      hasActiveLink: hasActiveLink2,
      hasChildren,
      toggle
    } = useSidebarControl(computed(() => props.item));
    const sectionTag = computed(() => hasChildren.value ? "section" : `div`);
    const linkTag = computed(() => isLink.value ? "a" : "div");
    const textTag = computed(() => {
      return !hasChildren.value ? "p" : props.depth + 2 === 7 ? "p" : `h${props.depth + 2}`;
    });
    const itemRole = computed(() => isLink.value ? void 0 : "button");
    const classes = computed(() => [
      [`level-${props.depth}`],
      { collapsible: collapsible.value },
      { collapsed: collapsed.value },
      { "is-link": isLink.value },
      { "is-active": isActiveLink.value },
      { "has-active": hasActiveLink2.value }
    ]);
    function onItemInteraction(e) {
      if ("key" in e && e.key !== "Enter") {
        return;
      }
      !props.item.link && toggle();
    }
    function onCaretClick() {
      props.item.link && toggle();
    }
    return (_ctx, _push, _parent, _attrs) => {
      const _component_VPSidebarItem = resolveComponent("VPSidebarItem", true);
      ssrRenderVNode(_push, createVNode(resolveDynamicComponent(sectionTag.value), mergeProps({
        class: ["VPSidebarItem", classes.value]
      }, _attrs), {
        default: withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            if (__props.item.text) {
              _push2(`<div class="item"${ssrRenderAttr("role", itemRole.value)}${ssrRenderAttr("tabindex", __props.item.items && 0)} data-v-b3fd67f8${_scopeId}><div class="indicator" data-v-b3fd67f8${_scopeId}></div>`);
              if (__props.item.link) {
                _push2(ssrRenderComponent(_sfc_main$1a, {
                  tag: linkTag.value,
                  class: "link",
                  href: __props.item.link,
                  rel: __props.item.rel,
                  target: __props.item.target
                }, {
                  default: withCtx((_2, _push3, _parent3, _scopeId2) => {
                    if (_push3) {
                      ssrRenderVNode(_push3, createVNode(resolveDynamicComponent(textTag.value), { class: "text" }, null), _parent3, _scopeId2);
                    } else {
                      return [
                        (openBlock(), createBlock(resolveDynamicComponent(textTag.value), {
                          class: "text",
                          innerHTML: __props.item.text
                        }, null, 8, ["innerHTML"]))
                      ];
                    }
                  }),
                  _: 1
                }, _parent2, _scopeId));
              } else {
                ssrRenderVNode(_push2, createVNode(resolveDynamicComponent(textTag.value), { class: "text" }, null), _parent2, _scopeId);
              }
              if (__props.item.collapsed != null && __props.item.items && __props.item.items.length) {
                _push2(`<div class="caret" role="button" aria-label="toggle section" tabindex="0" data-v-b3fd67f8${_scopeId}><span class="vpi-chevron-right caret-icon" data-v-b3fd67f8${_scopeId}></span></div>`);
              } else {
                _push2(`<!---->`);
              }
              _push2(`</div>`);
            } else {
              _push2(`<!---->`);
            }
            if (__props.item.items && __props.item.items.length) {
              _push2(`<div class="items" data-v-b3fd67f8${_scopeId}>`);
              if (__props.depth < 5) {
                _push2(`<!--[-->`);
                ssrRenderList(__props.item.items, (i) => {
                  _push2(ssrRenderComponent(_component_VPSidebarItem, {
                    key: i.text,
                    item: i,
                    depth: __props.depth + 1
                  }, null, _parent2, _scopeId));
                });
                _push2(`<!--]-->`);
              } else {
                _push2(`<!---->`);
              }
              _push2(`</div>`);
            } else {
              _push2(`<!---->`);
            }
          } else {
            return [
              __props.item.text ? (openBlock(), createBlock("div", mergeProps({
                key: 0,
                class: "item",
                role: itemRole.value
              }, toHandlers(
                __props.item.items ? { click: onItemInteraction, keydown: onItemInteraction } : {},
                true
              ), {
                tabindex: __props.item.items && 0
              }), [
                createVNode("div", { class: "indicator" }),
                __props.item.link ? (openBlock(), createBlock(_sfc_main$1a, {
                  key: 0,
                  tag: linkTag.value,
                  class: "link",
                  href: __props.item.link,
                  rel: __props.item.rel,
                  target: __props.item.target
                }, {
                  default: withCtx(() => [
                    (openBlock(), createBlock(resolveDynamicComponent(textTag.value), {
                      class: "text",
                      innerHTML: __props.item.text
                    }, null, 8, ["innerHTML"]))
                  ]),
                  _: 1
                }, 8, ["tag", "href", "rel", "target"])) : (openBlock(), createBlock(resolveDynamicComponent(textTag.value), {
                  key: 1,
                  class: "text",
                  innerHTML: __props.item.text
                }, null, 8, ["innerHTML"])),
                __props.item.collapsed != null && __props.item.items && __props.item.items.length ? (openBlock(), createBlock("div", {
                  key: 2,
                  class: "caret",
                  role: "button",
                  "aria-label": "toggle section",
                  onClick: onCaretClick,
                  onKeydown: withKeys(onCaretClick, ["enter"]),
                  tabindex: "0"
                }, [
                  createVNode("span", { class: "vpi-chevron-right caret-icon" })
                ], 32)) : createCommentVNode("", true)
              ], 16, ["role", "tabindex"])) : createCommentVNode("", true),
              __props.item.items && __props.item.items.length ? (openBlock(), createBlock("div", {
                key: 1,
                class: "items"
              }, [
                __props.depth < 5 ? (openBlock(true), createBlock(Fragment, { key: 0 }, renderList(__props.item.items, (i) => {
                  return openBlock(), createBlock(_component_VPSidebarItem, {
                    key: i.text,
                    item: i,
                    depth: __props.depth + 1
                  }, null, 8, ["item", "depth"]);
                }), 128)) : createCommentVNode("", true)
              ])) : createCommentVNode("", true)
            ];
          }
        }),
        _: 1
      }), _parent);
    };
  }
});
const _sfc_setup$q = _sfc_main$q.setup;
_sfc_main$q.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSidebarItem.vue");
  return _sfc_setup$q ? _sfc_setup$q(props, ctx) : void 0;
};
const VPSidebarItem = /* @__PURE__ */ _export_sfc(_sfc_main$q, [["__scopeId", "data-v-b3fd67f8"]]);
const _sfc_main$p = /* @__PURE__ */ defineComponent({
  __name: "VPSidebarGroup",
  __ssrInlineRender: true,
  props: {
    items: {}
  },
  setup(__props) {
    const disableTransition = ref(true);
    let timer = null;
    onMounted(() => {
      timer = setTimeout(() => {
        timer = null;
        disableTransition.value = false;
      }, 300);
    });
    onBeforeUnmount(() => {
      if (timer != null) {
        clearTimeout(timer);
        timer = null;
      }
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<!--[-->`);
      ssrRenderList(__props.items, (item) => {
        _push(`<div class="${ssrRenderClass([{ "no-transition": disableTransition.value }, "group"])}" data-v-c40bc020>`);
        _push(ssrRenderComponent(VPSidebarItem, {
          item,
          depth: 0
        }, null, _parent));
        _push(`</div>`);
      });
      _push(`<!--]-->`);
    };
  }
});
const _sfc_setup$p = _sfc_main$p.setup;
_sfc_main$p.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSidebarGroup.vue");
  return _sfc_setup$p ? _sfc_setup$p(props, ctx) : void 0;
};
const VPSidebarGroup = /* @__PURE__ */ _export_sfc(_sfc_main$p, [["__scopeId", "data-v-c40bc020"]]);
const _sfc_main$o = /* @__PURE__ */ defineComponent({
  __name: "VPSidebar",
  __ssrInlineRender: true,
  props: {
    open: { type: Boolean }
  },
  setup(__props) {
    const { sidebarGroups, hasSidebar } = useSidebar();
    const props = __props;
    const navEl = ref(null);
    const isLocked = useScrollLock(inBrowser ? document.body : null);
    watch(
      [props, navEl],
      () => {
        var _a;
        if (props.open) {
          isLocked.value = true;
          (_a = navEl.value) == null ? void 0 : _a.focus();
        } else isLocked.value = false;
      },
      { immediate: true, flush: "post" }
    );
    const key = ref(0);
    watch(
      sidebarGroups,
      () => {
        key.value += 1;
      },
      { deep: true }
    );
    return (_ctx, _push, _parent, _attrs) => {
      if (unref(hasSidebar)) {
        _push(`<aside${ssrRenderAttrs(mergeProps({
          class: ["VPSidebar", { open: __props.open }],
          ref_key: "navEl",
          ref: navEl
        }, _attrs))} data-v-319d5ca6><div class="curtain" data-v-319d5ca6></div><nav class="nav" id="VPSidebarNav" aria-labelledby="sidebar-aria-label" tabindex="-1" data-v-319d5ca6><span class="visually-hidden" id="sidebar-aria-label" data-v-319d5ca6> Sidebar Navigation </span>`);
        ssrRenderSlot(_ctx.$slots, "sidebar-nav-before", {}, null, _push, _parent);
        _push(ssrRenderComponent(VPSidebarGroup, {
          items: unref(sidebarGroups),
          key: key.value
        }, null, _parent));
        ssrRenderSlot(_ctx.$slots, "sidebar-nav-after", {}, null, _push, _parent);
        _push(`</nav></aside>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$o = _sfc_main$o.setup;
_sfc_main$o.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSidebar.vue");
  return _sfc_setup$o ? _sfc_setup$o(props, ctx) : void 0;
};
const VPSidebar = /* @__PURE__ */ _export_sfc(_sfc_main$o, [["__scopeId", "data-v-319d5ca6"]]);
const _sfc_main$n = /* @__PURE__ */ defineComponent({
  __name: "VPSkipLink",
  __ssrInlineRender: true,
  setup(__props) {
    const { theme: theme2 } = useData();
    const route = useRoute();
    const backToTop = ref();
    watch(() => route.path, () => backToTop.value.focus());
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<!--[--><span tabindex="-1" data-v-0b0ada53></span><a href="#VPContent" class="VPSkipLink visually-hidden" data-v-0b0ada53>${ssrInterpolate(unref(theme2).skipToContentLabel || "Skip to content")}</a><!--]-->`);
    };
  }
});
const _sfc_setup$n = _sfc_main$n.setup;
_sfc_main$n.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSkipLink.vue");
  return _sfc_setup$n ? _sfc_setup$n(props, ctx) : void 0;
};
const VPSkipLink = /* @__PURE__ */ _export_sfc(_sfc_main$n, [["__scopeId", "data-v-0b0ada53"]]);
const _sfc_main$m = /* @__PURE__ */ defineComponent({
  __name: "Layout",
  __ssrInlineRender: true,
  setup(__props) {
    const {
      isOpen: isSidebarOpen,
      open: openSidebar,
      close: closeSidebar
    } = useSidebar();
    const route = useRoute();
    watch(() => route.path, closeSidebar);
    useCloseSidebarOnEscape(isSidebarOpen, closeSidebar);
    const { frontmatter } = useData();
    const slots = useSlots();
    const heroImageSlotExists = computed(() => !!slots["home-hero-image"]);
    provide("hero-image-slot-exists", heroImageSlotExists);
    return (_ctx, _push, _parent, _attrs) => {
      const _component_Content = resolveComponent("Content");
      if (unref(frontmatter).layout !== false) {
        _push(`<div${ssrRenderAttrs(mergeProps({
          class: ["Layout", unref(frontmatter).pageClass]
        }, _attrs))} data-v-5d98c3a5>`);
        ssrRenderSlot(_ctx.$slots, "layout-top", {}, null, _push, _parent);
        _push(ssrRenderComponent(VPSkipLink, null, null, _parent));
        _push(ssrRenderComponent(VPBackdrop, {
          class: "backdrop",
          show: unref(isSidebarOpen),
          onClick: unref(closeSidebar)
        }, null, _parent));
        _push(ssrRenderComponent(VPNav, null, {
          "nav-bar-title-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-title-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-title-before", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-title-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-title-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-title-after", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-content-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-content-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-content-before", {}, void 0, true)
              ];
            }
          }),
          "nav-bar-content-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-bar-content-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-bar-content-after", {}, void 0, true)
              ];
            }
          }),
          "nav-screen-content-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-screen-content-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-screen-content-before", {}, void 0, true)
              ];
            }
          }),
          "nav-screen-content-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "nav-screen-content-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "nav-screen-content-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(ssrRenderComponent(VPLocalNav, {
          open: unref(isSidebarOpen),
          onOpenMenu: unref(openSidebar)
        }, null, _parent));
        _push(ssrRenderComponent(VPSidebar, { open: unref(isSidebarOpen) }, {
          "sidebar-nav-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "sidebar-nav-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "sidebar-nav-before", {}, void 0, true)
              ];
            }
          }),
          "sidebar-nav-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "sidebar-nav-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "sidebar-nav-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(ssrRenderComponent(VPContent, null, {
          "page-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "page-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "page-top", {}, void 0, true)
              ];
            }
          }),
          "page-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "page-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "page-bottom", {}, void 0, true)
              ];
            }
          }),
          "not-found": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "not-found", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "not-found", {}, void 0, true)
              ];
            }
          }),
          "home-hero-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-before", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-before", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info", {}, void 0, true)
              ];
            }
          }),
          "home-hero-info-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-info-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-info-after", {}, void 0, true)
              ];
            }
          }),
          "home-hero-actions-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-actions-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-actions-after", {}, void 0, true)
              ];
            }
          }),
          "home-hero-image": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-image", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-image", {}, void 0, true)
              ];
            }
          }),
          "home-hero-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-hero-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-hero-after", {}, void 0, true)
              ];
            }
          }),
          "home-features-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-features-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-features-before", {}, void 0, true)
              ];
            }
          }),
          "home-features-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "home-features-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "home-features-after", {}, void 0, true)
              ];
            }
          }),
          "doc-footer-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-footer-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-footer-before", {}, void 0, true)
              ];
            }
          }),
          "doc-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-before", {}, void 0, true)
              ];
            }
          }),
          "doc-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-after", {}, void 0, true)
              ];
            }
          }),
          "doc-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-top", {}, void 0, true)
              ];
            }
          }),
          "doc-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "doc-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "doc-bottom", {}, void 0, true)
              ];
            }
          }),
          "aside-top": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-top", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-top", {}, void 0, true)
              ];
            }
          }),
          "aside-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-bottom", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-bottom", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-before", {}, void 0, true)
              ];
            }
          }),
          "aside-outline-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-outline-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-outline-after", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-before": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-before", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-before", {}, void 0, true)
              ];
            }
          }),
          "aside-ads-after": withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              ssrRenderSlot(_ctx.$slots, "aside-ads-after", {}, null, _push2, _parent2, _scopeId);
            } else {
              return [
                renderSlot(_ctx.$slots, "aside-ads-after", {}, void 0, true)
              ];
            }
          }),
          _: 3
        }, _parent));
        _push(ssrRenderComponent(VPFooter, null, null, _parent));
        ssrRenderSlot(_ctx.$slots, "layout-bottom", {}, null, _push, _parent);
        _push(`</div>`);
      } else {
        _push(ssrRenderComponent(_component_Content, _attrs, null, _parent));
      }
    };
  }
});
const _sfc_setup$m = _sfc_main$m.setup;
_sfc_main$m.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/Layout.vue");
  return _sfc_setup$m ? _sfc_setup$m(props, ctx) : void 0;
};
const Layout = /* @__PURE__ */ _export_sfc(_sfc_main$m, [["__scopeId", "data-v-5d98c3a5"]]);
const GridSettings = {
  xmini: [[0, 2]],
  mini: [],
  small: [
    [920, 6],
    [768, 5],
    [640, 4],
    [480, 3],
    [0, 2]
  ],
  medium: [
    [960, 5],
    [832, 4],
    [640, 3],
    [480, 2]
  ],
  big: [
    [832, 3],
    [640, 2]
  ]
};
function useSponsorsGrid({ el, size = "medium" }) {
  const onResize = throttleAndDebounce(manage, 100);
  onMounted(() => {
    manage();
    window.addEventListener("resize", onResize);
  });
  onUnmounted(() => {
    window.removeEventListener("resize", onResize);
  });
  function manage() {
    adjustSlots(el.value, size);
  }
}
function adjustSlots(el, size) {
  const tsize = el.children.length;
  const asize = el.querySelectorAll(".vp-sponsor-grid-item:not(.empty)").length;
  const grid = setGrid(el, size, asize);
  manageSlots(el, grid, tsize, asize);
}
function setGrid(el, size, items) {
  const settings = GridSettings[size];
  const screen = window.innerWidth;
  let grid = 1;
  settings.some(([breakpoint, value]) => {
    if (screen >= breakpoint) {
      grid = items < value ? items : value;
      return true;
    }
  });
  setGridData(el, grid);
  return grid;
}
function setGridData(el, value) {
  el.dataset.vpGrid = String(value);
}
function manageSlots(el, grid, tsize, asize) {
  const diff = tsize - asize;
  const rem = asize % grid;
  const drem = rem === 0 ? rem : grid - rem;
  neutralizeSlots(el, drem - diff);
}
function neutralizeSlots(el, count) {
  if (count === 0) {
    return;
  }
  count > 0 ? addSlots(el, count) : removeSlots(el, count * -1);
}
function addSlots(el, count) {
  for (let i = 0; i < count; i++) {
    const slot = document.createElement("div");
    slot.classList.add("vp-sponsor-grid-item", "empty");
    el.append(slot);
  }
}
function removeSlots(el, count) {
  for (let i = 0; i < count; i++) {
    el.removeChild(el.lastElementChild);
  }
}
const _sfc_main$l = /* @__PURE__ */ defineComponent({
  __name: "VPSponsorsGrid",
  __ssrInlineRender: true,
  props: {
    size: { default: "medium" },
    data: {}
  },
  setup(__props) {
    const props = __props;
    const el = ref(null);
    useSponsorsGrid({ el, size: props.size });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPSponsorsGrid vp-sponsor-grid", [__props.size]],
        ref_key: "el",
        ref: el
      }, _attrs))}><!--[-->`);
      ssrRenderList(__props.data, (sponsor) => {
        _push(`<div class="vp-sponsor-grid-item"><a class="vp-sponsor-grid-link"${ssrRenderAttr("href", sponsor.url)} target="_blank" rel="sponsored noopener"><article class="vp-sponsor-grid-box"><h4 class="visually-hidden">${ssrInterpolate(sponsor.name)}</h4><img class="vp-sponsor-grid-image"${ssrRenderAttr("src", sponsor.img)}${ssrRenderAttr("alt", sponsor.name)}></article></a></div>`);
      });
      _push(`<!--]--></div>`);
    };
  }
});
const _sfc_setup$l = _sfc_main$l.setup;
_sfc_main$l.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSponsorsGrid.vue");
  return _sfc_setup$l ? _sfc_setup$l(props, ctx) : void 0;
};
const _sfc_main$k = /* @__PURE__ */ defineComponent({
  __name: "VPSponsors",
  __ssrInlineRender: true,
  props: {
    mode: { default: "normal" },
    tier: {},
    size: {},
    data: {}
  },
  setup(__props) {
    const props = __props;
    const sponsors = computed(() => {
      const isSponsors = props.data.some((s) => {
        return "items" in s;
      });
      if (isSponsors) {
        return props.data;
      }
      return [
        { tier: props.tier, size: props.size, items: props.data }
      ];
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPSponsors vp-sponsor", [__props.mode]]
      }, _attrs))}><!--[-->`);
      ssrRenderList(sponsors.value, (sponsor, index) => {
        _push(`<section class="vp-sponsor-section">`);
        if (sponsor.tier) {
          _push(`<h3 class="vp-sponsor-tier">${ssrInterpolate(sponsor.tier)}</h3>`);
        } else {
          _push(`<!---->`);
        }
        _push(ssrRenderComponent(_sfc_main$l, {
          size: sponsor.size,
          data: sponsor.items
        }, null, _parent));
        _push(`</section>`);
      });
      _push(`<!--]--></div>`);
    };
  }
});
const _sfc_setup$k = _sfc_main$k.setup;
_sfc_main$k.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPSponsors.vue");
  return _sfc_setup$k ? _sfc_setup$k(props, ctx) : void 0;
};
const _sfc_main$j = /* @__PURE__ */ defineComponent({
  __name: "VPDocAsideSponsors",
  __ssrInlineRender: true,
  props: {
    tier: {},
    size: {},
    data: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "VPDocAsideSponsors" }, _attrs))}>`);
      _push(ssrRenderComponent(_sfc_main$k, {
        mode: "aside",
        tier: __props.tier,
        size: __props.size,
        data: __props.data
      }, null, _parent));
      _push(`</div>`);
    };
  }
});
const _sfc_setup$j = _sfc_main$j.setup;
_sfc_main$j.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPDocAsideSponsors.vue");
  return _sfc_setup$j ? _sfc_setup$j(props, ctx) : void 0;
};
const _sfc_main$i = /* @__PURE__ */ defineComponent({
  __name: "VPHomeSponsors",
  __ssrInlineRender: true,
  props: {
    message: {},
    actionText: { default: "Become a sponsor" },
    actionLink: {},
    data: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<section${ssrRenderAttrs(mergeProps({ class: "VPHomeSponsors" }, _attrs))} data-v-3d121b4a><div class="container" data-v-3d121b4a><div class="header" data-v-3d121b4a><div class="love" data-v-3d121b4a><span class="vpi-heart icon" data-v-3d121b4a></span></div>`);
      if (__props.message) {
        _push(`<h2 class="message" data-v-3d121b4a>${ssrInterpolate(__props.message)}</h2>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div><div class="sponsors" data-v-3d121b4a>`);
      _push(ssrRenderComponent(_sfc_main$k, { data: __props.data }, null, _parent));
      _push(`</div>`);
      if (__props.actionLink) {
        _push(`<div class="action" data-v-3d121b4a>`);
        _push(ssrRenderComponent(VPButton, {
          theme: "sponsor",
          text: __props.actionText,
          href: __props.actionLink
        }, null, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div></section>`);
    };
  }
});
const _sfc_setup$i = _sfc_main$i.setup;
_sfc_main$i.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPHomeSponsors.vue");
  return _sfc_setup$i ? _sfc_setup$i(props, ctx) : void 0;
};
const _sfc_main$h = /* @__PURE__ */ defineComponent({
  __name: "VPTeamMembersItem",
  __ssrInlineRender: true,
  props: {
    size: { default: "medium" },
    member: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<article${ssrRenderAttrs(mergeProps({
        class: ["VPTeamMembersItem", [__props.size]]
      }, _attrs))} data-v-f3fa364a><div class="profile" data-v-f3fa364a><figure class="avatar" data-v-f3fa364a><img class="avatar-img"${ssrRenderAttr("src", __props.member.avatar)}${ssrRenderAttr("alt", __props.member.name)} data-v-f3fa364a></figure><div class="data" data-v-f3fa364a><h1 class="name" data-v-f3fa364a>${ssrInterpolate(__props.member.name)}</h1>`);
      if (__props.member.title || __props.member.org) {
        _push(`<p class="affiliation" data-v-f3fa364a>`);
        if (__props.member.title) {
          _push(`<span class="title" data-v-f3fa364a>${ssrInterpolate(__props.member.title)}</span>`);
        } else {
          _push(`<!---->`);
        }
        if (__props.member.title && __props.member.org) {
          _push(`<span class="at" data-v-f3fa364a> @ </span>`);
        } else {
          _push(`<!---->`);
        }
        if (__props.member.org) {
          _push(ssrRenderComponent(_sfc_main$1a, {
            class: ["org", { link: __props.member.orgLink }],
            href: __props.member.orgLink,
            "no-icon": ""
          }, {
            default: withCtx((_, _push2, _parent2, _scopeId) => {
              if (_push2) {
                _push2(`${ssrInterpolate(__props.member.org)}`);
              } else {
                return [
                  createTextVNode(toDisplayString(__props.member.org), 1)
                ];
              }
            }),
            _: 1
          }, _parent));
        } else {
          _push(`<!---->`);
        }
        _push(`</p>`);
      } else {
        _push(`<!---->`);
      }
      if (__props.member.desc) {
        _push(`<p class="desc" data-v-f3fa364a>${__props.member.desc ?? ""}</p>`);
      } else {
        _push(`<!---->`);
      }
      if (__props.member.links) {
        _push(`<div class="links" data-v-f3fa364a>`);
        _push(ssrRenderComponent(VPSocialLinks, {
          links: __props.member.links
        }, null, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div></div>`);
      if (__props.member.sponsor) {
        _push(`<div class="sp" data-v-f3fa364a>`);
        _push(ssrRenderComponent(_sfc_main$1a, {
          class: "sp-link",
          href: __props.member.sponsor,
          "no-icon": ""
        }, {
          default: withCtx((_, _push2, _parent2, _scopeId) => {
            if (_push2) {
              _push2(`<span class="vpi-heart sp-icon" data-v-f3fa364a${_scopeId}></span> ${ssrInterpolate(__props.member.actionText || "Sponsor")}`);
            } else {
              return [
                createVNode("span", { class: "vpi-heart sp-icon" }),
                createTextVNode(" " + toDisplayString(__props.member.actionText || "Sponsor"), 1)
              ];
            }
          }),
          _: 1
        }, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</article>`);
    };
  }
});
const _sfc_setup$h = _sfc_main$h.setup;
_sfc_main$h.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPTeamMembersItem.vue");
  return _sfc_setup$h ? _sfc_setup$h(props, ctx) : void 0;
};
const VPTeamMembersItem = /* @__PURE__ */ _export_sfc(_sfc_main$h, [["__scopeId", "data-v-f3fa364a"]]);
const _sfc_main$g = /* @__PURE__ */ defineComponent({
  __name: "VPTeamMembers",
  __ssrInlineRender: true,
  props: {
    size: { default: "medium" },
    members: {}
  },
  setup(__props) {
    const props = __props;
    const classes = computed(() => [props.size, `count-${props.members.length}`]);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({
        class: ["VPTeamMembers", classes.value]
      }, _attrs))} data-v-6cb0dbc4><div class="container" data-v-6cb0dbc4><!--[-->`);
      ssrRenderList(__props.members, (member) => {
        _push(`<div class="item" data-v-6cb0dbc4>`);
        _push(ssrRenderComponent(VPTeamMembersItem, {
          size: __props.size,
          member
        }, null, _parent));
        _push(`</div>`);
      });
      _push(`<!--]--></div></div>`);
    };
  }
});
const _sfc_setup$g = _sfc_main$g.setup;
_sfc_main$g.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPTeamMembers.vue");
  return _sfc_setup$g ? _sfc_setup$g(props, ctx) : void 0;
};
const _sfc_main$f = {};
const _sfc_setup$f = _sfc_main$f.setup;
_sfc_main$f.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPTeamPage.vue");
  return _sfc_setup$f ? _sfc_setup$f(props, ctx) : void 0;
};
const _sfc_main$e = {};
const _sfc_setup$e = _sfc_main$e.setup;
_sfc_main$e.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPTeamPageSection.vue");
  return _sfc_setup$e ? _sfc_setup$e(props, ctx) : void 0;
};
const _sfc_main$d = {};
const _sfc_setup$d = _sfc_main$d.setup;
_sfc_main$d.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("../node_modules/vitepress/dist/client/theme-default/components/VPTeamPageTitle.vue");
  return _sfc_setup$d ? _sfc_setup$d(props, ctx) : void 0;
};
const theme = {
  Layout,
  enhanceApp: ({ app }) => {
    app.component("Badge", _sfc_main$1h);
  }
};
const _sfc_main$c = /* @__PURE__ */ defineComponent({
  __name: "VisitCounter",
  __ssrInlineRender: true,
  setup(__props) {
    const { page } = useData$1();
    const enabled = ref(false);
    const siteViews = ref(null);
    const pageViews = ref(null);
    const failed = ref(false);
    let requestId = 0;
    async function updateCount() {
      var _a, _b;
      const currentRequest = ++requestId;
      failed.value = false;
      pageViews.value = null;
      try {
        const response = await fetch("https://busuanzi.9420.ltd/api", {
          method: "POST",
          headers: { "x-bsz-referer": `${location.origin}${location.pathname}` }
        });
        if (!response.ok) throw new Error(`Busuanzi returned ${response.status}`);
        const result = await response.json();
        const site = (_a = result.data) == null ? void 0 : _a.site_pv;
        const currentPage = (_b = result.data) == null ? void 0 : _b.page_pv;
        if (!result.success || typeof site !== "number" || typeof currentPage !== "number") {
          throw new Error("Busuanzi returned invalid counts");
        }
        if (currentRequest !== requestId) return;
        siteViews.value = site;
        pageViews.value = currentPage;
      } catch {
        if (currentRequest === requestId) failed.value = true;
      }
    }
    onMounted(() => {
      enabled.value = location.hostname === "lewislau86.github.io";
      if (enabled.value) void updateCount();
    });
    watch(() => page.value.relativePath, () => {
      if (enabled.value) void updateCount();
    });
    return (_ctx, _push, _parent, _attrs) => {
      if (enabled.value) {
        _push(`<footer${ssrRenderAttrs(mergeProps({
          class: "visit-counter",
          "aria-label": "访问统计"
        }, _attrs))}>`);
        if (failed.value) {
          _push(`<span>访问量暂不可用</span>`);
        } else {
          _push(`<!--[--><span>本站访问量 <strong>${ssrInterpolate(siteViews.value ?? "…")}</strong> 次</span><span>本页阅读量 <strong>${ssrInterpolate(pageViews.value ?? "…")}</strong> 次</span><!--]-->`);
        }
        _push(`</footer>`);
      } else {
        _push(`<!---->`);
      }
    };
  }
});
const _sfc_setup$c = _sfc_main$c.setup;
_sfc_main$c.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/VisitCounter.vue");
  return _sfc_setup$c ? _sfc_setup$c(props, ctx) : void 0;
};
const _sfc_main$b = /* @__PURE__ */ defineComponent({
  __name: "WalineComments",
  __ssrInlineRender: true,
  setup(__props) {
    const serverURL = void 0;
    ref(null);
    const loadFailed = ref(false);
    let instance;
    onMounted(async () => {
      return;
    });
    onBeforeUnmount(() => instance == null ? void 0 : instance.destroy());
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<section${ssrRenderAttrs(mergeProps({
        class: "reader-comments",
        "aria-label": "读者讨论"
      }, _attrs))}><h2>读者讨论</h2><p>无需登录即可留言；昵称可留空。留言经审核后显示。</p>`);
      if (unref(serverURL) && !loadFailed.value) {
        _push(`<div></div>`);
      } else {
        _push(`<p>评论服务正在配置或暂时不可用，请稍后再来。</p>`);
      }
      _push(`</section>`);
    };
  }
});
const _sfc_setup$b = _sfc_main$b.setup;
_sfc_main$b.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/WalineComments.vue");
  return _sfc_setup$b ? _sfc_setup$b(props, ctx) : void 0;
};
const _sfc_main$a = /* @__PURE__ */ defineComponent({
  __name: "Layout",
  __ssrInlineRender: true,
  setup(__props) {
    const route = useRoute();
    const { frontmatter } = useData$1();
    const showComments = computed(
      () => frontmatter.value.search !== false && (/^\/(tinyllm|mini-redis|burn)\//.test(route.path) || /^\/discuss(?:\.html)?$/.test(route.path))
    );
    return (_ctx, _push, _parent, _attrs) => {
      const _component_ClientOnly = resolveComponent("ClientOnly");
      _push(ssrRenderComponent(unref(theme).Layout, _attrs, {
        "doc-after": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(ssrRenderComponent(_component_ClientOnly, null, {
              default: withCtx((_2, _push3, _parent3, _scopeId2) => {
                if (_push3) {
                  if (showComments.value) {
                    _push3(ssrRenderComponent(_sfc_main$b, {
                      key: unref(route).path
                    }, null, _parent3, _scopeId2));
                  } else {
                    _push3(`<!---->`);
                  }
                } else {
                  return [
                    showComments.value ? (openBlock(), createBlock(_sfc_main$b, {
                      key: unref(route).path
                    })) : createCommentVNode("", true)
                  ];
                }
              }),
              _: 1
            }, _parent2, _scopeId));
          } else {
            return [
              createVNode(_component_ClientOnly, null, {
                default: withCtx(() => [
                  showComments.value ? (openBlock(), createBlock(_sfc_main$b, {
                    key: unref(route).path
                  })) : createCommentVNode("", true)
                ]),
                _: 1
              })
            ];
          }
        }),
        "layout-bottom": withCtx((_, _push2, _parent2, _scopeId) => {
          if (_push2) {
            _push2(ssrRenderComponent(_sfc_main$c, null, null, _parent2, _scopeId));
          } else {
            return [
              createVNode(_sfc_main$c)
            ];
          }
        }),
        _: 1
      }, _parent));
    };
  }
});
const _sfc_setup$a = _sfc_main$a.setup;
_sfc_main$a.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/Layout.vue");
  return _sfc_setup$a ? _sfc_setup$a(props, ctx) : void 0;
};
function useSvgLinkPrefetchFix(root) {
  const patch = () => {
    var _a;
    (_a = root.value) == null ? void 0 : _a.querySelectorAll("a").forEach((a) => {
      const href = a.href;
      const url = new URL(href instanceof SVGAnimatedString ? href.animVal : String(href), a.baseURI);
      Object.defineProperty(a, "pathname", { value: url.pathname, configurable: true });
    });
  };
  onMounted(patch);
  onUpdated(patch);
}
const _sfc_main$9 = /* @__PURE__ */ defineComponent({
  __name: "TinyLLMMap",
  __ssrInlineRender: true,
  props: {
    active: {},
    caption: { type: Boolean }
  },
  setup(__props) {
    const props = __props;
    const done = /* @__PURE__ */ new Set([
      "first-run",
      "tensors-and-autograd",
      "architecture-evolution",
      "initialization-and-residuals",
      "normalization",
      "activations-and-ffn",
      "transformer-block",
      "tokenization",
      "self-attention",
      "position-encoding",
      "embeddings-and-output",
      "optimizers",
      "precision",
      "tinyllm-model",
      "gpu-training",
      "data-pipeline",
      "generation",
      "language-model-loss",
      "learning-rate",
      "regularization"
    ]);
    const nodes = [
      { id: "tok", label: "分词器：文本 → token ID", ch: 4, slug: "tokenization", x: 140, y: 52, w: 240, h: 36 },
      { id: "emb", label: "词嵌入：ID → 向量", ch: 5, slug: "embeddings-and-output", x: 140, y: 108, w: 240, h: 36 },
      { id: "n1", label: "RMSNorm", ch: 11, slug: "normalization", x: 160, y: 196, w: 200, h: 32 },
      { id: "att", label: "因果自注意力", ch: 6, slug: "self-attention", x: 160, y: 244, w: 200, h: 36 },
      { id: "pos", label: "位置 RoPE", ch: 7, slug: "position-encoding", x: 400, y: 244, w: 120, h: 36 },
      { id: "n2", label: "RMSNorm", ch: 11, slug: "normalization", x: 160, y: 334, w: 200, h: 32 },
      { id: "ffn", label: "SwiGLU 前馈层", ch: 8, slug: "activations-and-ffn", x: 160, y: 382, w: 200, h: 36 },
      { id: "nf", label: "最终 RMSNorm", ch: 11, slug: "normalization", x: 140, y: 494, w: 240, h: 34 },
      { id: "out", label: "输出层：向量 → logits", ch: 5, slug: "embeddings-and-output", x: 140, y: 546, w: 240, h: 36 },
      { id: "gen", label: "逐个生成 token", ch: 25, slug: "generation", x: 140, y: 604, w: 240, h: 34 },
      { id: "loss", label: "交叉熵损失", ch: 15, slug: "language-model-loss", x: 470, y: 546, w: 190, h: 34 },
      { id: "grad", label: "backward 求梯度", ch: 2, slug: "tensors-and-autograd", x: 470, y: 494, w: 190, h: 34 },
      { id: "opt", label: "优化器更新参数", ch: 16, slug: "optimizers", x: 470, y: 442, w: 190, h: 34 },
      { id: "prec", label: "数值精度 / 混合精度", ch: 19, slug: "precision", x: 470, y: 390, w: 190, h: 34 }
    ];
    const activeSet = computed(() => new Set((props.active ?? "").split(",").map((s) => s.trim()).filter(Boolean)));
    const isActive2 = (slug) => activeSet.value.has(slug);
    const blockActive = computed(() => isActive2("transformer-block") || isActive2("tinyllm-model"));
    const residualActive = computed(() => isActive2("initialization-and-residuals"));
    const modelActive = computed(() => isActive2("tinyllm-model") || isActive2("first-run"));
    const href = (slug) => withBase(`/tinyllm/${slug}`);
    const svgRoot = ref(null);
    useSvgLinkPrefetchFix(svgRoot);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({
        class: ["tinyllm-map", { compact: !!__props.active }]
      }, _attrs))} data-v-fa4b7dbd><svg viewBox="0 0 700 660" role="img" aria-label="TinyLLM 架构总图：文本经分词、词嵌入、N 个 Transformer Block、最终归一化与输出层得到 logits；训练时由损失、反向传播与优化器更新参数" data-v-fa4b7dbd><defs data-v-fa4b7dbd><marker id="tm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse" data-v-fa4b7dbd><path d="M0,0 L10,5 L0,10 z" class="tm-arrowhead" data-v-fa4b7dbd></path></marker></defs>`);
      if (modelActive.value) {
        _push(`<rect x="120" y="40" width="280" height="610" rx="14" class="tm-model-glow" data-v-fa4b7dbd></rect>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<text x="260" y="26" text-anchor="middle" class="tm-plain" data-v-fa4b7dbd>“我在学习 TinyLLM”</text><line x1="260" y1="32" x2="260" y2="50" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="88" x2="260" y2="106" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="144" x2="260" y2="170" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><a${ssrRenderAttr("href", href("transformer-block"))} data-v-fa4b7dbd><rect x="120" y="172" width="280" height="290" rx="12" class="${ssrRenderClass(["tm-block", { active: blockActive.value, planned: !unref(done).has("transformer-block") }])}" data-v-fa4b7dbd></rect><text x="408" y="186" class="tm-block-label" data-v-fa4b7dbd>Transformer Block</text><text x="408" y="202" class="tm-block-label" data-v-fa4b7dbd>× N · 第 9 章</text></a><line x1="260" y1="228" x2="260" y2="242" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="280" x2="260" y2="300" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="324" x2="260" y2="332" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="366" x2="260" y2="380" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="418" x2="260" y2="430" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="454" x2="260" y2="492" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="174" x2="260" y2="194" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><a${ssrRenderAttr("href", href("initialization-and-residuals"))} data-v-fa4b7dbd><path d="M260,184 H146 V312 H246" class="${ssrRenderClass(["tm-residual", { active: residualActive.value }])}" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></path><path d="M260,326 H146 V442 H246" class="${ssrRenderClass(["tm-residual", { active: residualActive.value }])}" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></path><circle cx="260" cy="312" r="12" class="${ssrRenderClass(["tm-add", { active: residualActive.value }])}" data-v-fa4b7dbd></circle><text x="260" y="317" text-anchor="middle" class="tm-add-text" data-v-fa4b7dbd>+</text><circle cx="260" cy="442" r="12" class="${ssrRenderClass(["tm-add", { active: residualActive.value }])}" data-v-fa4b7dbd></circle><text x="260" y="447" text-anchor="middle" class="tm-add-text" data-v-fa4b7dbd>+</text><text x="135" y="380" text-anchor="middle" class="tm-side-label" transform="rotate(-90 135 380)" data-v-fa4b7dbd>残差 · 第 10 章</text></a><line x1="400" y1="262" x2="362" y2="262" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="528" x2="260" y2="544" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="260" y1="582" x2="260" y2="602" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="380" y1="563" x2="468" y2="563" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="565" y1="546" x2="565" y2="530" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><line x1="565" y1="494" x2="565" y2="478" class="tm-edge" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></line><path d="M470,459 H420 V330 H402" class="tm-train" marker-end="url(#tm-arrow)" data-v-fa4b7dbd></path><text x="565" y="378" text-anchor="middle" class="tm-side-label" data-v-fa4b7dbd>训练时才走右侧这一列</text><text x="424" y="320" class="tm-side-label" data-v-fa4b7dbd>更新参数</text><!--[-->`);
      ssrRenderList(nodes, (n) => {
        _push(`<a${ssrRenderAttr("href", href(n.slug))} data-v-fa4b7dbd><rect${ssrRenderAttr("x", n.x)}${ssrRenderAttr("y", n.y)}${ssrRenderAttr("width", n.w)}${ssrRenderAttr("height", n.h)} rx="8" class="${ssrRenderClass(["tm-node", { active: isActive2(n.slug), planned: !unref(done).has(n.slug) }])}" data-v-fa4b7dbd></rect><text${ssrRenderAttr("x", n.x + n.w / 2)}${ssrRenderAttr("y", n.y + n.h / 2 - 1)} text-anchor="middle" dominant-baseline="middle" class="tm-label" data-v-fa4b7dbd>${ssrInterpolate(n.label)}</text><text${ssrRenderAttr("x", n.x + n.w - 6)}${ssrRenderAttr("y", n.y + n.h - 5)} text-anchor="end" class="tm-ch" data-v-fa4b7dbd>${ssrInterpolate(n.ch)}</text></a>`);
      });
      _push(`<!--]--></svg>`);
      if (__props.caption !== false) {
        _push(`<figcaption data-v-fa4b7dbd> TinyLLM 全书地图。<span class="tm-key active" data-v-fa4b7dbd>高亮</span>是本章负责的零件；实线框已成文，虚线框还在规划中；右下角数字是章节号，点击任一零件可跳到对应章节。 </figcaption>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</figure>`);
    };
  }
});
const _sfc_setup$9 = _sfc_main$9.setup;
_sfc_main$9.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/TinyLLMMap.vue");
  return _sfc_setup$9 ? _sfc_setup$9(props, ctx) : void 0;
};
const TinyLLMMap = /* @__PURE__ */ _export_sfc(_sfc_main$9, [["__scopeId", "data-v-fa4b7dbd"]]);
const _sfc_main$8 = /* @__PURE__ */ defineComponent({
  __name: "MiniRedisMap",
  __ssrInlineRender: true,
  props: {
    active: {}
  },
  setup(__props) {
    const props = __props;
    const nodes = [
      { id: "cli", label: "CLI / 你的程序", ch: 1, slug: "first-run", x: 30, y: 70, w: 190, h: 40 },
      { id: "client", label: "Client", sub: "Buffered / Blocking", ch: 9, slug: "clients", x: 30, y: 135, w: 190, h: 48 },
      { id: "connc", label: "Connection", sub: "命令 → Frame → 字节", ch: 4, slug: "resp-and-connection", x: 30, y: 208, w: 190, h: 48 },
      { id: "serverrun", label: "server::run", sub: "运行时、监听、关闭信号", ch: 5, slug: "tokio-server", x: 330, y: 62, w: 200, h: 48 },
      { id: "listener", label: "Listener", sub: "取配额 → accept → spawn", ch: 5, slug: "tokio-server", x: 330, y: 130, w: 200, h: 48 },
      { id: "shutdown", label: "Shutdown 通知", sub: "broadcast + mpsc", ch: 10, slug: "shutdown-and-tests", x: 560, y: 62, w: 170, h: 48 },
      { id: "read", label: "Connection::read_frame", sub: "字节 → Frame", ch: 4, slug: "resp-and-connection", x: 345, y: 228, w: 230, h: 44 },
      { id: "cmd", label: "Command::from_frame", sub: "Parse → Set / Get …", ch: 3, slug: "request-path", x: 345, y: 284, w: 230, h: 44 },
      { id: "apply", label: "apply", sub: "Set / Get / Publish / Subscribe", ch: 3, slug: "request-path", x: 345, y: 340, w: 230, h: 44 },
      { id: "purge", label: "后台清理任务", sub: "sleep_until / Notify", ch: 7, slug: "expiration", x: 600, y: 228, w: 130, h: 48 },
      { id: "entries", label: "entries", sub: "HashMap 键值", ch: 6, slug: "shared-storage", x: 345, y: 448, w: 120, h: 44 },
      { id: "expirations", label: "expirations", sub: "BTreeSet 过期索引", ch: 7, slug: "expiration", x: 608, y: 448, w: 122, h: 44 },
      { id: "pubsub", label: "pub_sub", sub: "频道 → broadcast", ch: 8, slug: "pubsub", x: 477, y: 448, w: 120, h: 44 }
    ];
    const highlight = {
      "first-run": ["cli", "client", "serverrun"],
      "rust-foundations": ["cmd", "entries"],
      "request-path": ["client", "connc", "tcp", "read", "cmd", "apply", "entries"],
      "resp-and-connection": ["connc", "tcp", "read"],
      "tokio-server": ["serverrun", "listener", "handler"],
      "shared-storage": ["db", "entries"],
      "expiration": ["expirations", "purge"],
      "pubsub": ["pubsub", "apply"],
      "clients": ["client", "connc"],
      "shutdown-and-tests": ["serverrun", "shutdown", "handler"],
      "ttl-test-debugging": ["expirations", "purge", "read"]
    };
    const on = computed(() => new Set(highlight[props.active ?? ""] ?? []));
    const isOn = (id) => on.value.has(id);
    const href = (slug) => withBase(`/mini-redis/${slug}`);
    const svgRoot = ref(null);
    useSvgLinkPrefetchFix(svgRoot);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({
        class: ["mr-map", { compact: !!__props.active }]
      }, _attrs))} data-v-05087bc9><svg viewBox="0 0 760 530" role="img" aria-label="mini-redis 架构图：客户端进程中的 Client 与 Connection 通过 TCP 字节流连接服务端；服务端由 server::run 启动 Listener，为每个连接创建 Handler 任务，依次读帧、解析命令、执行 apply，访问共享的 Db；后台任务清理过期键，Shutdown 负责停机通知" data-v-05087bc9><defs data-v-05087bc9><marker id="mr-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse" data-v-05087bc9><path d="M0,0 L10,5 L0,10 z" class="mr-arrowhead" data-v-05087bc9></path></marker></defs><rect x="12" y="30" width="226" height="250" rx="12" class="mr-process" data-v-05087bc9></rect><text x="24" y="52" class="mr-group" data-v-05087bc9>客户端进程</text><rect x="312" y="30" width="436" height="490" rx="12" class="mr-process" data-v-05087bc9></rect><text x="324" y="52" class="mr-group" data-v-05087bc9>服务端进程</text><a${ssrRenderAttr("href", href("tokio-server"))} data-v-05087bc9><rect x="333" y="200" width="254" height="196" rx="10" class="${ssrRenderClass(["mr-container", { active: isOn("handler") }])}" data-v-05087bc9></rect><text x="345" y="219" class="mr-container-label" data-v-05087bc9>Handler 任务（每个连接一个）· 第 5 章</text></a><a${ssrRenderAttr("href", href("shared-storage"))} data-v-05087bc9><rect x="333" y="414" width="405" height="94" rx="10" class="${ssrRenderClass(["mr-container", { active: isOn("db") }])}" data-v-05087bc9></rect><text x="345" y="434" class="mr-container-label" data-v-05087bc9>Db = Arc&lt;Shared&gt;，所有任务共享一份 · 第 6 章</text></a><a${ssrRenderAttr("href", href("resp-and-connection"))} data-v-05087bc9><path d="M222,222 H343" class="${ssrRenderClass(["mr-tcp", { active: isOn("tcp") }])}" marker-end="url(#mr-arrow)" data-v-05087bc9></path><path d="M343,262 H222" class="${ssrRenderClass(["mr-tcp", { active: isOn("tcp") }])}" marker-end="url(#mr-arrow)" data-v-05087bc9></path><text x="282" y="212" text-anchor="middle" class="mr-edge-label" data-v-05087bc9>请求</text><text x="282" y="280" text-anchor="middle" class="mr-edge-label" data-v-05087bc9>响应</text><text x="282" y="246" text-anchor="middle" class="${ssrRenderClass(["mr-tcp-label", { active: isOn("tcp") }])}" data-v-05087bc9>TCP·RESP</text></a><line x1="125" y1="110" x2="125" y2="133" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="125" y1="183" x2="125" y2="206" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="430" y1="110" x2="430" y2="128" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="430" y1="178" x2="430" y2="198" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="460" y1="272" x2="460" y2="282" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="460" y1="328" x2="460" y2="338" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><line x1="405" y1="384" x2="405" y2="446" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></line><path d="M530,86 H558" class="mr-edge" marker-end="url(#mr-arrow)" data-v-05087bc9></path><path d="M645,110 V160 H560 V198" class="mr-dashed" marker-end="url(#mr-arrow)" data-v-05087bc9></path><text x="650" y="150" class="mr-edge-label" data-v-05087bc9>停机时通知</text><path d="M665,276 V446" class="mr-dashed" marker-end="url(#mr-arrow)" data-v-05087bc9></path><text x="671" y="360" class="mr-edge-label" data-v-05087bc9>删除到期键</text><path d="M537,384 V446" class="mr-dashed" marker-end="url(#mr-arrow)" data-v-05087bc9></path><text x="543" y="404" class="mr-edge-label" data-v-05087bc9>订阅</text><!--[-->`);
      ssrRenderList(nodes, (n) => {
        _push(`<a${ssrRenderAttr("href", href(n.slug))} data-v-05087bc9><rect${ssrRenderAttr("x", n.x)}${ssrRenderAttr("y", n.y)}${ssrRenderAttr("width", n.w)}${ssrRenderAttr("height", n.h)} rx="8" class="${ssrRenderClass(["mr-node", { active: isOn(n.id) }])}" data-v-05087bc9></rect><text${ssrRenderAttr("x", n.x + n.w / 2)}${ssrRenderAttr("y", n.sub ? n.y + n.h / 2 - 5 : n.y + n.h / 2 + 1)} text-anchor="middle" dominant-baseline="middle" class="mr-label" data-v-05087bc9>${ssrInterpolate(n.label)}</text>`);
        if (n.sub) {
          _push(`<text${ssrRenderAttr("x", n.x + n.w / 2)}${ssrRenderAttr("y", n.y + n.h / 2 + 12)} text-anchor="middle" dominant-baseline="middle" class="mr-sub" data-v-05087bc9>${ssrInterpolate(n.sub)}</text>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<text${ssrRenderAttr("x", n.x + n.w - 5)}${ssrRenderAttr("y", n.y + 11)} text-anchor="end" class="mr-ch" data-v-05087bc9>${ssrInterpolate(n.ch)}</text></a>`);
      });
      _push(`<!--]--></svg><figcaption data-v-05087bc9> mini-redis 全书地图。`);
      if (on.value.size) {
        _push(`<span data-v-05087bc9><span class="mr-key" data-v-05087bc9>高亮</span>是本章讲解的部件；</span>`);
      } else {
        _push(`<!---->`);
      }
      _push(`实线箭头是同一任务内的调用，虚线是跨任务的通知或消息；右上角数字是主讲章节，点击部件可跳转。 </figcaption></figure>`);
    };
  }
});
const _sfc_setup$8 = _sfc_main$8.setup;
_sfc_main$8.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/MiniRedisMap.vue");
  return _sfc_setup$8 ? _sfc_setup$8(props, ctx) : void 0;
};
const MiniRedisMap = /* @__PURE__ */ _export_sfc(_sfc_main$8, [["__scopeId", "data-v-05087bc9"]]);
function usePlayer(total, options = {}) {
  const n = typeof total === "function" ? computed(total) : total;
  const frame = ref(options.start === "last" ? n.value - 1 : 0);
  const playing = ref(false);
  let timer;
  function stop() {
    playing.value = false;
    if (timer) clearInterval(timer);
    timer = void 0;
  }
  function next() {
    if (frame.value < n.value - 1) frame.value++;
    else stop();
  }
  function step() {
    stop();
    next();
  }
  function prev() {
    stop();
    if (frame.value > 0) frame.value--;
  }
  function restart() {
    stop();
    frame.value = 0;
  }
  function toggle() {
    if (playing.value) return stop();
    if (frame.value >= n.value - 1) frame.value = 0;
    playing.value = true;
    timer = setInterval(next, options.interval ?? 900);
  }
  function seek(f) {
    stop();
    frame.value = Math.max(0, Math.min(n.value - 1, f));
  }
  onBeforeUnmount(stop);
  return { frame, playing, total: n, next, step, prev, restart, toggle, seek, stop };
}
const _sfc_main$7 = /* @__PURE__ */ defineComponent({
  __name: "PlayerControls",
  __ssrInlineRender: true,
  props: {
    p: {},
    label: {}
  },
  setup(__props) {
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "pc" }, _attrs))} data-v-7f29bbaf><button data-v-7f29bbaf>从头</button><button data-v-7f29bbaf>上一步</button><button class="pc-play" data-v-7f29bbaf>`);
      if (!__props.p.playing) {
        _push(`<svg viewBox="0 0 10 10" aria-hidden="true" data-v-7f29bbaf><path d="M2 1L9 5L2 9Z" data-v-7f29bbaf></path></svg>`);
      } else {
        _push(`<svg viewBox="0 0 10 10" aria-hidden="true" data-v-7f29bbaf><path d="M2 1H4V9H2ZM6 1H8V9H6Z" data-v-7f29bbaf></path></svg>`);
      }
      _push(` ${ssrInterpolate(__props.p.playing ? "暂停" : "播放")}</button><button data-v-7f29bbaf>下一步</button><input type="range" min="0"${ssrRenderAttr("max", __props.p.total - 1)}${ssrRenderAttr("value", __props.p.frame)} aria-label="拖动到任意一步" data-v-7f29bbaf><span class="pc-count" data-v-7f29bbaf>${ssrInterpolate(__props.label ?? `${__props.p.frame + 1} / ${__props.p.total}`)}</span></div>`);
    };
  }
});
const _sfc_setup$7 = _sfc_main$7.setup;
_sfc_main$7.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/PlayerControls.vue");
  return _sfc_setup$7 ? _sfc_setup$7(props, ctx) : void 0;
};
const PlayerControls = /* @__PURE__ */ _export_sfc(_sfc_main$7, [["__scopeId", "data-v-7f29bbaf"]]);
const vocab_size = 556;
const temperature = 0.8;
const before = { "prompt": "春", "steps": [{ "top": [["润", 0.02985], ["文", 0.02027], ["竹", 0.01989], ["送", 0.01879], ["飞", 0.01801]], "pick": "问", "p": 9e-4, "rank": 273 }, { "top": [["送", 0.03267], ["侵", 0.02826], ["孙", 0.02358], ["炉", 0.02026], ["前", 0.01767]], "pick": "巾", "p": 698e-5, "rank": 22 }, { "top": [["孙", 0.08084], ["侵", 0.03876], ["炉", 0.02763], ["巾", 0.02529], ["送", 0.02374]], "pick": "兹", "p": 35e-5, "rank": 399 }, { "top": [["旷", 0.0356], ["车", 0.03026], ["侵", 0.02398], ["飞", 0.0234], ["自", 0.01643]], "pick": "戎", "p": 0.01279, "rank": 9 }, { "top": [["戎", 0.12545], ["飞", 0.03636], ["孙", 0.02448], ["疏", 0.01975], ["旷", 0.01926]], "pick": "除", "p": 0.01516, "rank": 9 }, { "top": [["除", 0.0822], ["疏", 0.03567], ["侵", 0.02997], ["横", 0.0269], ["自", 0.02589]], "pick": "至", "p": 72e-4, "rank": 29 }, { "top": [["至", 0.13109], ["当", 0.03178], ["旷", 0.02127], ["车", 0.02116], ["侵", 0.02052]], "pick": "细", "p": 145e-5, "rank": 148 }, { "top": [["平", 0.01924], ["车", 0.01896], ["桑", 0.01851], ["蓬", 0.01441], ["疏", 0.01254]], "pick": "车", "p": 0.01896, "rank": 2 }, { "top": [["车", 0.20108], ["至", 0.03079], ["搔", 0.01968], ["旷", 0.01854], ["送", 0.01145]], "pick": "秀", "p": 202e-5, "rank": 112 }, { "top": [["侵", 0.03924], ["怀", 0.02257], ["成", 0.02128], ["自", 0.01802], ["炉", 0.01681]], "pick": "无", "p": 747e-5, "rank": 24 }, { "top": [["无", 0.04996], ["侵", 0.03877], ["平", 0.01606], ["车", 0.01565], ["至", 0.01508]], "pick": "孙", "p": 618e-5, "rank": 33 }, { "top": [["孙", 0.3233], ["侵", 0.03706], ["自", 0.02169], ["怀", 0.02129], ["怨", 0.02083]], "pick": "除", "p": 599e-5, "rank": 15 }, { "top": [["除", 0.1582], ["况", 0.02562], ["水", 0.01792], ["胜", 0.01591], ["孙", 0.01382]], "pick": "秦", "p": 118e-5, "rank": 191 }, { "top": [["怀", 0.02133], ["更", 0.01993], ["房", 0.01748], ["况", 0.01688], ["怨", 0.01638]], "pick": "蓬", "p": 0.01466, "rank": 7 }, { "top": [["况", 0.04573], ["蓬", 0.04045], ["今", 0.02464], ["无", 0.0185], ["门", 0.01792]], "pick": "宦", "p": 9e-4, "rank": 246 }, { "top": [["应", 0.02911], ["寄", 0.01867], ["侵", 0.01821], ["况", 0.01802], ["自", 0.01753]], "pick": "胜", "p": 897e-5, "rank": 17 }, { "top": [["胜", 0.33894], ["门", 0.02134], ["风", 0.01861], ["惊", 0.01617], ["当", 0.01583]], "pick": "胜", "p": 0.33894, "rank": 1 }, { "top": [["胜", 0.28143], ["戍", 0.0223], ["除", 0.01683], ["况", 0.01617], ["决", 0.01562]], "pick": "俱", "p": 543e-5, "rank": 25 }, { "top": [["俱", 0.08853], ["门", 0.02199], ["怨", 0.01948], ["成", 0.01798], ["鸟", 0.01795]], "pick": "浑", "p": 414e-5, "rank": 62 }, { "top": [["至", 0.03451], ["怨", 0.02081], ["今", 0.02013], ["醅", 0.01701], ["岱", 0.01648]], "pick": "戍", "p": 829e-5, "rank": 20 }, { "top": [["戍", 0.28233], ["胸", 0.03655], ["胜", 0.03162], ["门", 0.01161], ["入", 0.01138]], "pick": "除", "p": 812e-5, "rank": 14 }, { "top": [["除", 0.2253], ["况", 0.03314], ["更", 0.02299], ["门", 0.0194], ["戍", 0.01616]], "pick": "短", "p": 927e-5, "rank": 11 }, { "top": [["短", 0.05972], ["更", 0.04126], ["文", 0.01816], ["佳", 0.01576], ["胸", 0.01328]], "pick": "有", "p": 268e-5, "rank": 96 }, { "top": [["有", 0.02806], ["鼓", 0.02427], ["戍", 0.02176], ["况", 0.01966], ["成", 0.01628]], "pick": "入", "p": 31e-4, "rank": 85 }, { "top": [["入", 0.04347], ["况", 0.03074], ["襄", 0.02562], ["戍", 0.02526], ["胜", 0.02183]], "pick": "鱼", "p": 248e-5, "rank": 106 }, { "top": [["鱼", 0.22274], ["况", 0.04476], ["戍", 0.01894], ["醅", 0.01425], ["时", 0.01422]], "pick": "五", "p": 0.01208, "rank": 7 }, { "top": [["五", 0.13654], ["应", 0.03829], ["戍", 0.03624], ["当", 0.02145], ["况", 0.01986]], "pick": "醅", "p": 0.01273, "rank": 7 }, { "top": [["醅", 0.13254], ["戍", 0.05269], ["自", 0.01936], ["弟", 0.01709], ["苍", 0.01693]], "pick": "就", "p": 193e-5, "rank": 113 }, { "top": [["就", 0.06261], ["戍", 0.02086], ["蒸", 0.01834], ["复", 0.0164], ["粒", 0.01498]], "pick": "杯", "p": 942e-5, "rank": 18 }, { "top": [["杯", 0.3573], ["百", 0.02936], ["秋", 0.01988], ["应", 0.01683], ["无", 0.01657]], "pick": "杯", "p": 0.3573, "rank": 1 }, { "top": [["杯", 0.4447], ["无", 0.01549], ["百", 0.01252], ["今", 0.01177], ["除", 0.01082]], "pick": "怜", "p": 533e-5, "rank": 21 }, { "top": [["怜", 0.15831], ["颗", 0.02765], ["杯", 0.02303], ["圆", 0.01668], ["中", 0.01216]], "pick": "乾", "p": 553e-5, "rank": 27 }, { "top": [["乾", 0.05623], ["应", 0.02392], ["悦", 0.01973], ["重", 0.01862], ["若", 0.01768]], "pick": "桑", "p": 344e-5, "rank": 72 }, { "top": [["桑", 0.16659], ["戍", 0.03418], ["地", 0.01312], ["苍", 0.01182], ["班", 0.01077]], "pick": "地", "p": 0.01312, "rank": 3 }, { "top": [["地", 0.13899], ["堪", 0.01763], ["戍", 0.01719], ["桑", 0.01436], ["晨", 0.01315]], "pick": "厌", "p": 481e-5, "rank": 37 }, { "top": [["厌", 0.05461], ["适", 0.03167], ["堪", 0.02403], ["颗", 0.02185], ["地", 0.01935]], "pick": "适", "p": 0.03167, "rank": 2 }, { "top": [["适", 0.6733], ["弟", 0.02533], ["割", 0.01348], ["颗", 937e-5], ["苍", 64e-4]], "pick": "适", "p": 0.6733, "rank": 1 }, { "top": [["适", 0.67081], ["弟", 0.03123], ["戍", 0.01583], ["颗", 0.01271], ["割", 791e-5]], "pick": "适", "p": 0.67081, "rank": 1 }, { "top": [["适", 0.45546], ["弟", 0.0279], ["颗", 0.02029], ["割", 0.01997], ["歇", 0.01812]], "pick": "歇", "p": 0.01812, "rank": 5 }, { "top": [["歇", 0.29823], ["寐", 0.03673], ["浦", 0.0241], ["苍", 0.01571], ["弟", 0.01484]], "pick": "歇", "p": 0.29823, "rank": 1 }, { "top": [["歇", 0.34054], ["寐", 0.02457], ["浦", 0.02087], ["苍", 0.01789], ["割", 0.0169]], "pick": "戍", "p": 0.01149, "rank": 10 }, { "top": [["戍", 0.4291], ["弟", 0.01695], ["割", 0.01668], ["适", 0.01496], ["自", 0.01349]], "pick": "适", "p": 0.01496, "rank": 4 }, { "top": [["适", 0.51373], ["弟", 0.05607], ["歇", 0.02352], ["戍", 0.01653], ["名", 0.01034]], "pick": "名", "p": 0.01034, "rank": 5 }, { "top": [["名", 0.17437], ["适", 0.11042], ["戍", 0.03074], ["歇", 0.01479], ["颗", 0.0132]], "pick": "王", "p": 72e-5, "rank": 235 }, { "top": [["适", 0.03417], ["歇", 0.03068], ["颗", 0.02445], ["水", 0.02153], ["戍", 0.01931]], "pick": "杯", "p": 309e-5, "rank": 85 }, { "top": [["杯", 0.13857], ["弟", 0.09753], ["疏", 0.02388], ["适", 0.02103], ["水", 0.02024]], "pick": "适", "p": 0.02103, "rank": 4 }, { "top": [["适", 0.52052], ["弟", 0.05233], ["疏", 0.01517], ["自", 0.01437], ["风", 947e-5]], "pick": "适", "p": 0.52052, "rank": 1 }, { "top": [["适", 0.45409], ["弟", 0.04429], ["自", 0.03403], ["名", 0.01491], ["颗", 0.01235]], "pick": "幽", "p": 186e-5, "rank": 59 }] };
const after = { "prompt": "春", "steps": [{ "top": [["乃", 0.36191], ["涧", 0.11123], ["山", 0.11013], ["入", 0.09697], ["风", 0.09324]], "pick": "乃", "p": 0.36191, "rank": 1 }, { "top": [["发", 0.99339], ["中", 209e-5], ["未", 89e-5], ["地", 51e-5], ["时", 33e-5]], "pick": "发", "p": 0.99339, "rank": 1 }, { "top": [["生", 0.98742], ["几", 0.01209], ["城", 3e-5], ["休", 2e-5], ["物", 2e-5]], "pick": "生", "p": 0.98742, "rank": 1 }, { "top": [["。", 0.99996], ["明", 1e-5], ["风", 0], ["春", 0], ["林", 0]], "pick": "。", "p": 0.99996, "rank": 1 }, { "top": [["随", 0.99936], ["远", 15e-5], ["野", 3e-5], ["郭", 2e-5], ["愿", 2e-5]], "pick": "随", "p": 0.99936, "rank": 1 }, { "top": [["风", 0.99893], ["平", 6e-5], ["草", 6e-5], ["微", 6e-5], ["日", 6e-5]], "pick": "风", "p": 0.99893, "rank": 1 }, { "top": [["潜", 0.99814], ["吹", 88e-5], ["雨", 9e-5], ["潭", 7e-5], ["辅", 6e-5]], "pick": "潜", "p": 0.99814, "rank": 1 }, { "top": [["入", 0.99932], ["风", 5e-5], ["潜", 4e-5], ["欲", 3e-5], ["乃", 3e-5]], "pick": "入", "p": 0.99932, "rank": 1 }, { "top": [["夜", 0.99965], ["残", 5e-5], ["旧", 4e-5], ["最", 2e-5], ["深", 1e-5]], "pick": "夜", "p": 0.99965, "rank": 1 }, { "top": [["，", 0.99963], ["归", 6e-5], ["天", 6e-5], ["舟", 5e-5], ["白", 2e-5]], "pick": "，", "p": 0.99963, "rank": 1 }, { "top": [["润", 0.9993], ["江", 18e-5], ["危", 9e-5], ["云", 3e-5], ["深", 2e-5]], "pick": "润", "p": 0.9993, "rank": 1 }, { "top": [["物", 0.99958], ["云", 4e-5], ["延", 3e-5], ["最", 3e-5], ["满", 2e-5]], "pick": "物", "p": 0.99958, "rank": 1 }, { "top": [["细", 0.99845], ["最", 102e-5], ["生", 7e-5], ["撷", 5e-5], ["物", 3e-5]], "pick": "细", "p": 0.99845, "rank": 1 }, { "top": [["无", 0.99966], ["草", 9e-5], ["思", 5e-5], ["兹", 2e-5], ["一", 1e-5]], "pick": "无", "p": 0.99966, "rank": 1 }, { "top": [["声", 0.99945], ["。", 1e-4], ["老", 3e-5], ["图", 3e-5], ["餐", 2e-5]], "pick": "声", "p": 0.99945, "rank": 1 }, { "top": [["。", 0.99996], ["，", 1e-5], ["声", 1e-5], ["云", 0], ["语", 0]], "pick": "。", "p": 0.99996, "rank": 1 }, { "top": [["野", 0.99965], ["随", 9e-5], ["适", 2e-5], ["潮", 1e-5], ["远", 1e-5]], "pick": "野", "p": 0.99965, "rank": 1 }, { "top": [["径", 0.99932], ["阔", 21e-5], ["旷", 5e-5], ["离", 4e-5], ["正", 4e-5]], "pick": "径", "p": 0.99932, "rank": 1 }, { "top": [["云", 0.99952], ["，", 13e-5], ["物", 5e-5], ["通", 2e-5], ["落", 1e-5]], "pick": "云", "p": 0.99952, "rank": 1 }, { "top": [["俱", 0.99919], ["危", 7e-5], ["润", 6e-5], ["独", 6e-5], ["黑", 5e-5]], "pick": "俱", "p": 0.99919, "rank": 1 }, { "top": [["黑", 0.99923], ["俱", 26e-5], ["前", 4e-5], ["斜", 4e-5], ["无", 3e-5]], "pick": "黑", "p": 0.99923, "rank": 1 }, { "top": [["，", 0.99994], ["天", 2e-5], ["云", 1e-5], ["明", 0], ["。", 0]], "pick": "，", "p": 0.99994, "rank": 1 }, { "top": [["江", 0.99979], ["大", 2e-5], ["润", 1e-5], ["寒", 1e-5], ["火", 1e-5]], "pick": "江", "p": 0.99979, "rank": 1 }, { "top": [["船", 0.99883], ["清", 62e-5], ["涌", 7e-5], ["径", 3e-5], ["南", 3e-5]], "pick": "船", "p": 0.99883, "rank": 1 }, { "top": [["火", 0.99922], ["云", 6e-5], ["寒", 5e-5], ["白", 5e-5], ["不", 3e-5]], "pick": "火", "p": 0.99922, "rank": 1 }, { "top": [["独", 0.99779], ["连", 59e-5], ["炉", 41e-5], ["远", 35e-5], ["绮", 4e-5]], "pick": "独", "p": 0.99779, "rank": 1 }, { "top": [["明", 0.99825], ["月", 46e-5], ["幽", 2e-4], ["游", 1e-4], ["海", 7e-5]], "pick": "明", "p": 0.99825, "rank": 1 }, { "top": [["。", 0.99989], ["月", 2e-5], ["明", 2e-5], ["河", 0], ["林", 0]], "pick": "。", "p": 0.99989, "rank": 1 }, { "top": [["晓", 0.9985], ["火", 3e-4], ["野", 29e-5], ["当", 12e-5], ["禾", 7e-5]], "pick": "晓", "p": 0.9985, "rank": 1 }, { "top": [["看", 0.99933], ["照", 12e-5], ["连", 5e-5], ["少", 3e-5], ["当", 3e-5]], "pick": "看", "p": 0.99933, "rank": 1 }, { "top": [["红", 0.99872], ["两", 19e-5], ["当", 9e-5], ["莲", 4e-5], ["禾", 4e-5]], "pick": "红", "p": 0.99872, "rank": 1 }, { "top": [["湿", 0.99839], ["红", 31e-5], ["豆", 25e-5], ["处", 9e-5], ["泥", 5e-5]], "pick": "湿", "p": 0.99839, "rank": 1 }, { "top": [["处", 0.99943], ["晚", 14e-5], ["湿", 6e-5], ["日", 2e-5], ["房", 2e-5]], "pick": "处", "p": 0.99943, "rank": 1 }, { "top": [["，", 0.99979], ["处", 4e-5], ["达", 4e-5], ["闻", 2e-5], ["天", 2e-5]], "pick": "，", "p": 0.99979, "rank": 1 }, { "top": [["花", 0.99946], ["禅", 13e-5], ["绕", 5e-5], ["木", 3e-5], ["恨", 2e-5]], "pick": "花", "p": 0.99946, "rank": 1 }, { "top": [["重", 0.99912], ["锦", 11e-5], ["溅", 9e-5], ["别", 6e-5], ["木", 3e-5]], "pick": "重", "p": 0.99912, "rank": 1 }, { "top": [["锦", 0.99662], ["重", 229e-5], ["船", 5e-5], ["宦", 4e-5], ["房", 3e-5]], "pick": "锦", "p": 0.99662, "rank": 1 }, { "top": [["官", 0.99938], ["锦", 5e-5], ["光", 4e-5], ["独", 3e-5], ["黍", 3e-5]], "pick": "官", "p": 0.99938, "rank": 1 }, { "top": [["城", 0.99931], ["孙", 5e-5], ["应", 3e-5], ["生", 3e-5], ["花", 3e-5]], "pick": "城", "p": 0.99931, "rank": 1 }, { "top": [["。", 0.99998], ["城", 0], ["春", 0], ["河", 0], ["，", 0]], "pick": "。", "p": 0.99998, "rank": 1 }, { "top": [["\n", 0.99989], ["青", 2e-5], ["幽", 1e-5], ["感", 1e-5], ["吴", 0]], "pick": "\n", "p": 0.99989, "rank": 1 }] };
const trace = {
  vocab_size,
  temperature,
  before,
  after
};
const _sfc_main$6 = /* @__PURE__ */ defineComponent({
  __name: "NextTokenPlayer",
  __ssrInlineRender: true,
  props: {
    stage: { default: "after" }
  },
  setup(__props) {
    const props = __props;
    const stage = ref(props.stage);
    const data = computed(() => trace[stage.value]);
    const vocab = trace.vocab_size;
    const p = reactive(usePlayer(() => data.value.steps.length * 2, { interval: 750 }));
    const i = computed(() => Math.floor(p.frame / 2));
    const revealed = computed(() => p.frame % 2 === 1);
    const step = computed(() => data.value.steps[i.value]);
    const shown = (c) => c === "\n" ? "⏎" : c;
    const done = computed(() => data.value.steps.slice(0, i.value).map((s) => shown(s.pick)).join(""));
    const rest = computed(() => Math.max(0, 1 - step.value.top.reduce((a, [, p2]) => a + p2, 0)));
    const pickInTop = computed(() => step.value.rank <= step.value.top.length);
    function pct(p2) {
      if (p2 >= 0.01) return (p2 * 100).toFixed(1) + "%";
      if (p2 >= 1e-4) return (p2 * 100).toFixed(2) + "%";
      return "<0.01%";
    }
    function switchStage(s) {
      p.stop();
      stage.value = s;
      p.frame = 0;
    }
    watch(() => props.stage, (s) => switchStage(s));
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card ntp" }, _attrs))} data-v-5f82b783><div class="ntp-tabs" role="tablist" data-v-5f82b783><button role="tab"${ssrRenderAttr("aria-selected", stage.value === "before")} class="${ssrRenderClass({ on: stage.value === "before" })}" data-v-5f82b783>训练前（随机参数）</button><button role="tab"${ssrRenderAttr("aria-selected", stage.value === "after")} class="${ssrRenderClass({ on: stage.value === "after" })}" data-v-5f82b783>训练 600 步之后</button></div><div class="ntp-text" aria-label="已经写出的文字" data-v-5f82b783><span class="ntp-prompt" data-v-5f82b783>${ssrInterpolate(data.value.prompt)}</span><span class="ntp-done" data-v-5f82b783>${ssrInterpolate(done.value)}</span><span class="${ssrRenderClass(["ntp-slot", { filled: revealed.value }])}" data-v-5f82b783>${ssrInterpolate(revealed.value ? shown(step.value.pick) : "?")}</span></div><p class="ntp-caption" aria-live="polite" data-v-5f82b783>`);
      if (!revealed.value) {
        _push(`<!--[--> 第 ${ssrInterpolate(i.value + 1)} 步：模型读入前面 ${ssrInterpolate(data.value.prompt.length + i.value)} 个字，给词表里 ${ssrInterpolate(unref(vocab))} 个字各算出一个概率。下面是最高的 5 个： <!--]-->`);
      } else {
        _push(`<!--[--> 按概率抽签，抽中“${ssrInterpolate(shown(step.value.pick))}”：概率 ${ssrInterpolate(pct(step.value.p))}，在 ${ssrInterpolate(unref(vocab))} 个字里排第 ${ssrInterpolate(step.value.rank)}。把它接在后面，进入下一步。 <!--]-->`);
      }
      _push(`</p><div class="ntp-bars" data-v-5f82b783><!--[-->`);
      ssrRenderList(step.value.top, ([c, p2], k2) => {
        _push(`<div class="${ssrRenderClass(["ntp-row", { pick: revealed.value && pickInTop.value && k2 === step.value.rank - 1 }])}" data-v-5f82b783><span class="ntp-char" data-v-5f82b783>${ssrInterpolate(shown(c))}</span><span class="ntp-track" data-v-5f82b783><span class="ntp-bar" style="${ssrRenderStyle({ width: Math.max(p2 * 100, 0.4) + "%" })}" data-v-5f82b783></span></span><span class="ntp-p" data-v-5f82b783>${ssrInterpolate(pct(p2))}</span></div>`);
      });
      _push(`<!--]-->`);
      if (revealed.value && !pickInTop.value) {
        _push(`<div class="ntp-row pick" data-v-5f82b783><span class="ntp-char" data-v-5f82b783>${ssrInterpolate(shown(step.value.pick))}</span><span class="ntp-track" data-v-5f82b783><span class="ntp-bar" style="${ssrRenderStyle({ width: Math.max(step.value.p * 100, 0.4) + "%" })}" data-v-5f82b783></span></span><span class="ntp-p" data-v-5f82b783>${ssrInterpolate(pct(step.value.p))} · 第 ${ssrInterpolate(step.value.rank)} 名</span></div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<div class="ntp-row ntp-rest" data-v-5f82b783><span class="ntp-char" data-v-5f82b783>…</span><span class="ntp-track" data-v-5f82b783><span class="ntp-bar" style="${ssrRenderStyle({ width: rest.value * 100 + "%" })}" data-v-5f82b783></span></span><span class="ntp-p" data-v-5f82b783>其余 ${ssrInterpolate(unref(vocab) - 5)} 个字合计 ${ssrInterpolate(pct(rest.value))}</span></div></div>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: `${i.value + 1} / ${data.value.steps.length}`
      }, null, _parent));
      _push(`<figcaption data-v-5f82b783> 真实记录：第 1 章的模型以“${ssrInterpolate(data.value.prompt)}”开头、温度 0.8、随机种子 1 时每一步的概率。播放、单步或拖动滑块查看任意一步。 </figcaption></figure>`);
    };
  }
});
const _sfc_setup$6 = _sfc_main$6.setup;
_sfc_main$6.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/NextTokenPlayer.vue");
  return _sfc_setup$6 ? _sfc_setup$6(props, ctx) : void 0;
};
const NextTokenPlayer = /* @__PURE__ */ _export_sfc(_sfc_main$6, [["__scopeId", "data-v-5f82b783"]]);
const names = ["我", "在", "学习"];
const Q = [[1, 0], [0, 1], [1, 1]];
const K = [[1, 0], [0, 1], [1, 1]];
const V = [[1, 0], [0, 2], [3, 3]];
const scores = [[0.7071067690849304, 0, 0.7071067690849304], [0, 0.7071067690849304, 0.7071067690849304], [0.7071067690849304, 0.7071067690849304, 1.4142135381698608]];
const future = [[false, true, true], [false, false, true], [false, false, false]];
const weights = [[1, 0, 0], [0.3302384614944458, 0.6697615385055542, 0], [0.24825508892536163, 0.24825508892536163, 0.5034898519515991]];
const out = [[1, 0], [0.3302384614944458, 1.3395230770111084], [1.7587246894836426, 2.0069797039031982]];
const d$5 = {
  names,
  Q,
  K,
  V,
  scores,
  future,
  weights,
  out
};
const _sfc_main$5 = /* @__PURE__ */ defineComponent({
  __name: "AttentionStepper",
  __ssrInlineRender: true,
  setup(__props) {
    const names2 = d$5.names;
    const PHASES = ["① 打分", "② 遮住未来", "③ softmax", "④ 按权重取 V"];
    const p = reactive(usePlayer(() => names2.length * 4, { interval: 1300, start: "last" }));
    const r = computed(() => Math.floor(p.frame / 4));
    const ph = computed(() => p.frame % 4);
    const f2 = (x2) => x2.toFixed(2);
    const shown = (row, phase) => row < r.value || row === r.value && ph.value >= phase;
    const isFuture = (i, j) => d$5.future[i][j];
    const caption = computed(() => {
      const i = r.value, n = names2[i], q2 = d$5.Q[i];
      if (ph.value === 0) {
        const parts = names2.map((m, j) => `${m} (${q2[0]}·${d$5.K[j][0]} + ${q2[1]}·${d$5.K[j][1]}) / √2 = ${f2(d$5.scores[i][j])}`);
        return `<b>第 ${i + 1} 行“${n}”打分</b>：它的 q = [${q2.join(", ")}] 和每个位置的 k 做点积，再除以 √2。${parts.join("；")}。`;
      }
      if (ph.value === 1) {
        const fut = names2.filter((_, j) => isFuture(i, j));
        return fut.length ? `<b>遮住未来</b>：“${n}”只能看自己和前面，把 ${fut.map((m) => `“${m}”`).join("、")} 的分数改成 −∞，softmax 之后它们的权重就是 0。` : `<b>遮住未来</b>：“${n}”是最后一个位置，前面的字都能看，这一行没有要遮的。`;
      }
      if (ph.value === 2) {
        const vis = names2.map((m, j) => isFuture(i, j) ? null : `${m} ${f2(d$5.weights[i][j])}`).filter(Boolean);
        return `<b>softmax</b>：把这一行的分数取指数再归一化，变成加起来等于 1 的权重：${vis.join("，")}。分数高的位置分到的权重多，−∞ 变成 0。`;
      }
      const terms = names2.map((m, j) => isFuture(i, j) ? null : `${f2(d$5.weights[i][j])}×v${m}`).filter(Boolean);
      return `<b>按权重取 V</b>：输出 = ${terms.join(" + ")} = [${d$5.out[i].map(f2).join(", ")}]。“${n}”这个位置就这样从前文取回了信息。`;
    });
    const hl = (mat, row) => {
      if (ph.value === 0) return mat === "Q" ? row === r.value : mat === "K";
      if (ph.value === 3) return mat === "V" && !isFuture(r.value, row);
      return false;
    };
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card att" }, _attrs))} data-v-d916007a><div class="att-inputs" data-v-d916007a><!--[-->`);
      ssrRenderList(["Q", "K", "V"], (mat) => {
        _push(`<div class="att-mat small" data-v-d916007a><div class="att-title" data-v-d916007a>${ssrInterpolate(mat)}</div><div class="att-grid" style="${ssrRenderStyle({ gridTemplateColumns: `3rem repeat(2, 2.4rem)` })}" data-v-d916007a><!--[-->`);
        ssrRenderList(unref(d$5)[mat], (row, i) => {
          _push(`<!--[--><span class="att-rl" data-v-d916007a>${ssrInterpolate(unref(names2)[i])}</span><!--[-->`);
          ssrRenderList(row, (v, j) => {
            _push(`<span class="${ssrRenderClass(["att-cell", { hl: hl(mat, i) }])}" data-v-d916007a>${ssrInterpolate(v)}</span>`);
          });
          _push(`<!--]--><!--]-->`);
        });
        _push(`<!--]--></div></div>`);
      });
      _push(`<!--]--></div><div class="att-steps" data-v-d916007a><!--[-->`);
      ssrRenderList(PHASES, (title, k2) => {
        _push(`<div class="${ssrRenderClass(["att-mat", { active: ph.value === k2 }])}" data-v-d916007a><div class="att-title" data-v-d916007a>${ssrInterpolate(title)}</div><div class="att-grid" style="${ssrRenderStyle({ gridTemplateColumns: `3rem repeat(${k2 === 3 ? 2 : 3}, 2.9rem)` })}" data-v-d916007a><span class="att-rl" data-v-d916007a></span><!--[-->`);
        ssrRenderList(k2 === 3 ? ["d0", "d1"] : unref(names2), (c, j) => {
          _push(`<span class="att-ch" data-v-d916007a>${ssrInterpolate(c)}</span>`);
        });
        _push(`<!--]--><!--[-->`);
        ssrRenderList(unref(names2), (_, i) => {
          _push(`<!--[--><span class="${ssrRenderClass(["att-rl", { cur: i === r.value }])}" data-v-d916007a>${ssrInterpolate(unref(names2)[i])}</span>`);
          if (k2 < 3) {
            _push(`<!--[-->`);
            ssrRenderList(unref(names2), (_2, j) => {
              _push(`<span class="${ssrRenderClass(["att-cell", { cur: i === r.value && ph.value === k2, off: k2 > 0 && isFuture(i, j) && shown(i, k2), blank: !shown(i, k2) }])}" data-v-d916007a>`);
              if (shown(i, k2)) {
                _push(`<!--[-->${ssrInterpolate(k2 === 0 ? f2(unref(d$5).scores[i][j]) : k2 === 1 ? isFuture(i, j) ? "−∞" : f2(unref(d$5).scores[i][j]) : isFuture(i, j) ? "0" : f2(unref(d$5).weights[i][j]))}<!--]-->`);
              } else {
                _push(`<!---->`);
              }
              _push(`</span>`);
            });
            _push(`<!--]-->`);
          } else {
            _push(`<!--[-->`);
            ssrRenderList(unref(d$5).out[i], (v, j) => {
              _push(`<span class="${ssrRenderClass(["att-cell", { cur: i === r.value && ph.value === 3, blank: !shown(i, 3) }])}" data-v-d916007a>`);
              if (shown(i, 3)) {
                _push(`<!--[-->${ssrInterpolate(f2(v))}<!--]-->`);
              } else {
                _push(`<!---->`);
              }
              _push(`</span>`);
            });
            _push(`<!--]-->`);
          }
          _push(`<!--]-->`);
        });
        _push(`<!--]--></div></div>`);
      });
      _push(`<!--]--></div><p class="anim-caption" aria-live="polite" data-v-d916007a>${caption.value ?? ""}</p>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: `第 ${r.value + 1} 行 · ${PHASES[ph.value]}`
      }, null, _parent));
      _push(`<figcaption data-v-d916007a>数值来自本章 self-attention.py 里 hand、causal 两段代码的真实输出。一开始显示的是全部算完的结果；点“播放”从第一行重演，每一行依次经过打分、遮住未来、softmax、按权重取 V 四步。<a${ssrRenderAttr("href", unref(withBase)("/tinyllm/figures/attention-steps.svg"))} target="_blank" data-v-d916007a>打开静态图</a>（打印或不便播放时使用）。</figcaption></figure>`);
    };
  }
});
const _sfc_setup$5 = _sfc_main$5.setup;
_sfc_main$5.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/AttentionStepper.vue");
  return _sfc_setup$5 ? _sfc_setup$5(props, ctx) : void 0;
};
const AttentionStepper = /* @__PURE__ */ _export_sfc(_sfc_main$5, [["__scopeId", "data-v-d916007a"]]);
const q = [0.8032760620117188, 0.17483338713645935, 0.08897809684276581, -0.6137180328369141, 0.04618244990706444, -1.3682591915130615, 0.3374950885772705, 1.0111159086227417];
const k = [-1.435179352760315, 0.9774317741394043, 0.5220499634742737, 1.2379167079925537, -0.8646355867385864, 0.2989608347415924, 0.41921865940093994, -0.0798543244600296];
const base = 1e4;
const check = { "3,1": 0.32476210594177246, "13,11": 0.32476216554641724, "40,38": 0.3247620463371277, "3,0": 0.13968253135681152 };
const d$4 = {
  q,
  k,
  base,
  check
};
const MAX = 40;
const R = 92, C = 120;
const _sfc_main$4 = /* @__PURE__ */ defineComponent({
  __name: "RopeSlider",
  __ssrInlineRender: true,
  setup(__props) {
    const D = d$4.q.length;
    const thetas = Array.from({ length: D / 2 }, (_, i) => Math.pow(d$4.base, -2 * i / D));
    const m = ref(3);
    const n = ref(1);
    const pair = ref(1);
    function rotate(v, i, pos) {
      const a = pos * thetas[i], x1 = v[2 * i], x2 = v[2 * i + 1];
      return [x1 * Math.cos(a) - x2 * Math.sin(a), x1 * Math.sin(a) + x2 * Math.cos(a)];
    }
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
    const contrib = (i) => dot(rotate(d$4.q, i, m.value), rotate(d$4.k, i, n.value));
    const total = computed(() => thetas.reduce((s, _, i) => s + contrib(i), 0));
    const scale = computed(() => R / Math.max(Math.hypot(d$4.q[2 * pair.value], d$4.q[2 * pair.value + 1]), Math.hypot(d$4.k[2 * pair.value], d$4.k[2 * pair.value + 1])));
    const qv = computed(() => rotate(d$4.q, pair.value, m.value));
    const kv = computed(() => rotate(d$4.k, pair.value, n.value));
    const pt = (v) => [C + v[0] * scale.value, C - v[1] * scale.value];
    const lx = (v) => v[0] >= 0 ? Math.min(pt(v)[0] + 6, 240 - 74) : Math.max(pt(v)[0] - 6, 74);
    const deg = (v) => Math.atan2(v[1], v[0]) * 180 / Math.PI;
    const between = computed(() => {
      let a = deg(qv.value) - deg(kv.value);
      a = (a + 540) % 360 - 180;
      return a;
    });
    const arc = computed(() => {
      const a0 = Math.atan2(kv.value[1], kv.value[0]), a1 = a0 + between.value * Math.PI / 180;
      const r = 30, large = Math.abs(between.value) > 180 ? 1 : 0, sweep = between.value > 0 ? 0 : 1;
      return `M${C + r * Math.cos(a0)} ${C - r * Math.sin(a0)} A${r} ${r} 0 ${large} ${sweep} ${C + r * Math.cos(a1)} ${C - r * Math.sin(a1)}`;
    });
    const moving = ref(false);
    let timer;
    function stopMove() {
      moving.value = false;
      if (timer) clearInterval(timer);
      timer = void 0;
    }
    onBeforeUnmount(stopMove);
    const f4 = (x2) => x2.toFixed(4);
    const thetaLabel = (t) => t >= 0.1 ? t.toFixed(1) : t >= 0.01 ? t.toFixed(2) : t.toFixed(3);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card rope" }, _attrs))} data-v-1a1a16f1><div class="rope-body" data-v-1a1a16f1><svg viewBox="0 0 240 240" class="rope-svg" role="img"${ssrRenderAttr("aria-label", `第 ${pair.value + 1} 对维度：q 转了 ${m.value}θ，k 转了 ${n.value}θ，夹角 ${Math.abs(between.value).toFixed(0)} 度`)} data-v-1a1a16f1><defs data-v-1a1a16f1><marker id="rope-q" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto" data-v-1a1a16f1><path d="M0 0L10 5L0 10Z" class="q-fill" data-v-1a1a16f1></path></marker><marker id="rope-k" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto" data-v-1a1a16f1><path d="M0 0L10 5L0 10Z" class="k-fill" data-v-1a1a16f1></path></marker></defs><circle${ssrRenderAttr("cx", C)}${ssrRenderAttr("cy", C)}${ssrRenderAttr("r", R)} class="ring" data-v-1a1a16f1></circle><line${ssrRenderAttr("x1", C - R - 8)}${ssrRenderAttr("y1", C)}${ssrRenderAttr("x2", C + R + 8)}${ssrRenderAttr("y2", C)} class="axis" data-v-1a1a16f1></line><line${ssrRenderAttr("x1", C)}${ssrRenderAttr("y1", C - R - 8)}${ssrRenderAttr("x2", C)}${ssrRenderAttr("y2", C + R + 8)} class="axis" data-v-1a1a16f1></line><path${ssrRenderAttr("d", arc.value)} class="arc" data-v-1a1a16f1></path><line${ssrRenderAttr("x1", C)}${ssrRenderAttr("y1", C)}${ssrRenderAttr("x2", pt(kv.value)[0])}${ssrRenderAttr("y2", pt(kv.value)[1])} class="k-line" marker-end="url(#rope-k)" data-v-1a1a16f1></line><line${ssrRenderAttr("x1", C)}${ssrRenderAttr("y1", C)}${ssrRenderAttr("x2", pt(qv.value)[0])}${ssrRenderAttr("y2", pt(qv.value)[1])} class="q-line" marker-end="url(#rope-q)" data-v-1a1a16f1></line><text${ssrRenderAttr("x", lx(qv.value))}${ssrRenderAttr("y", pt(qv.value)[1] - 6)}${ssrRenderAttr("text-anchor", qv.value[0] >= 0 ? "start" : "end")} class="q-text" data-v-1a1a16f1>q（位置 ${ssrInterpolate(m.value)}）</text><text${ssrRenderAttr("x", lx(kv.value))}${ssrRenderAttr("y", pt(kv.value)[1] + 14)}${ssrRenderAttr("text-anchor", kv.value[0] >= 0 ? "start" : "end")} class="k-text" data-v-1a1a16f1>k（位置 ${ssrInterpolate(n.value)}）</text></svg><div class="rope-panel" data-v-1a1a16f1><label class="rope-slider q" data-v-1a1a16f1><span data-v-1a1a16f1>q 的位置 m = <b data-v-1a1a16f1>${ssrInterpolate(m.value)}</b></span><input type="range" min="0"${ssrRenderAttr("max", MAX)}${ssrRenderAttr("value", m.value)} data-v-1a1a16f1></label><label class="rope-slider k" data-v-1a1a16f1><span data-v-1a1a16f1>k 的位置 n = <b data-v-1a1a16f1>${ssrInterpolate(n.value)}</b></span><input type="range" min="0"${ssrRenderAttr("max", MAX)}${ssrRenderAttr("value", n.value)} data-v-1a1a16f1></label><div class="rope-read" data-v-1a1a16f1><div data-v-1a1a16f1>相隔 m − n = <b data-v-1a1a16f1>${ssrInterpolate(m.value - n.value)}</b></div><div data-v-1a1a16f1>图中这一对：夹角 ${ssrInterpolate(Math.abs(between.value).toFixed(1))}°，贡献 ${ssrInterpolate(f4(contrib(pair.value)))}</div><div class="score" data-v-1a1a16f1>4 对加起来（8 维 q·k）= <b data-v-1a1a16f1>${ssrInterpolate(f4(total.value))}</b></div></div><div class="rope-btns" data-v-1a1a16f1><button class="go" data-v-1a1a16f1>${ssrInterpolate(moving.value ? "停下" : "保持相隔，一起往后移")}</button><button data-v-1a1a16f1>回到 m=3, n=1</button></div></div></div><div class="rope-pairs" data-v-1a1a16f1><span data-v-1a1a16f1>看哪一对维度：</span><!--[-->`);
      ssrRenderList(unref(thetas), (t, i) => {
        _push(`<button class="${ssrRenderClass({ on: pair.value === i })}" data-v-1a1a16f1>第 ${ssrInterpolate(i + 1)} 对 · 每个位置转 ${ssrInterpolate(thetaLabel(t))} 弧度</button>`);
      });
      _push(`<!--]--></div><p class="anim-caption" data-v-1a1a16f1> 拖动两个滑块：q、k 各自按自己的位置旋转。点“保持相隔，一起往后移”，两根箭头一起转，夹角不变，右边的分数也一直不变。只改变相隔的距离，分数才会变。 </p><figcaption data-v-1a1a16f1>q、k 是本章 position-encoding.py 里 rope-relative 那段代码的 8 维 q_vec、k_vec，旋转方式与 rope() 函数相同；m=3、n=1 时分数为 ${ssrInterpolate(f4(unref(d$4).check["3,1"]))}，与代码输出一致。8 维被分成 4 对，每对转速不同，图中画的是其中一对。</figcaption></figure>`);
    };
  }
});
const _sfc_setup$4 = _sfc_main$4.setup;
_sfc_main$4.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/RopeSlider.vue");
  return _sfc_setup$4 ? _sfc_setup$4(props, ctx) : void 0;
};
const RopeSlider = /* @__PURE__ */ _export_sfc(_sfc_main$4, [["__scopeId", "data-v-1a1a16f1"]]);
const curvature = [1, 25];
const paths = { "SGD (lr=0.075)": [[-4.5, 1.600000023841858], [-4.162499904632568, -1.4000000953674316], [-3.8503124713897705, 1.225000262260437], [-3.5615389347076416, -1.0718752145767212], [-3.2944235801696777, 0.9378909468650818], [-3.047341823577881, -0.8206546306610107], [-2.818791151046753, 0.7180728316307068], [-2.607381820678711, -0.6283137202262878], [-2.4118282794952393, 0.5497745275497437], [-2.2309410572052, -0.4810527265071869], [-2.0636205673217773, 0.4209212064743042], [-1.9088490009307861, -0.36830610036849976], [-1.7656853199005127, 0.3222678303718567], [-1.6332589387893677, -0.2819843888282776], [-1.510764479637146, 0.24673636257648468], [-1.3974571228027344, -0.21589432656764984], [-1.2926478385925293, 0.18890753388404846], [-1.1956992149353027, -0.1652940958738327], [-1.106021761894226, 0.14463233947753906], [-1.0230700969696045, -0.12655331194400787], [-0.9463398456573486, 0.11073416471481323], [-0.875364363193512, -0.09689240902662277], [-0.8097120523452759, 0.08478085696697235], [-0.74898362159729, -0.07418325543403625], [-0.6928098201751709, 0.06491035223007202], [-0.6408490538597107, -0.056796565651893616], [-0.5927853584289551, 0.04969699680805206], [-0.5483264327049255, -0.043484877794981], [-0.5072019696235657, 0.03804927319288254], [-0.4691618084907532, -0.033293116837739944], [-0.4339746832847595, 0.02913147769868374], [-0.4014265835285187, -0.025490043684840202], [-0.37131959199905396, 0.022303789854049683], [-0.34347063302993774, -0.01951581984758377], [-0.31771034002304077, 0.017076343297958374], [-0.2938820719718933, -0.014941801317036152], [-0.2718409299850464, 0.013074076734483242], [-0.25145286321640015, -0.011439817026257515], [-0.23259389400482178, 0.010009841062128544], [-0.21514935791492462, -0.008758611045777798], [-0.19901315867900848, 0.007663785479962826]], "Momentum (lr=0.01, 0.9)": [[-4.5, 1.600000023841858], [-4.454999923706055, 1.2000000476837158], [-4.369949817657471, 0.5400000810623169], [-4.2497053146362305, -0.18899992108345032], [-4.098988056182861, -0.7978499531745911], [-3.9223527908325195, -1.1463524103164673], [-3.7241575717926025, -1.1734166145324707], [-3.508540391921997, -0.9044201970100403], [-3.2793993949890137, -0.43621838092803955], [-3.0403785705566406, 0.09421785920858383], [-2.794856071472168, 0.5480560064315796], [-2.5459372997283936, 0.8194963335990906], [-2.2964510917663574, 0.8589185476303101], [-2.0489490032196045, 0.6796689033508301], [-1.805707573890686, 0.3484269976615906], [-1.5687332153320312, -0.03679744899272919], [-1.3397690057754517, -0.3743000626564026], [-1.1203035116195679, -0.584477424621582], [-0.9115815162658691, -0.6275177001953125], [-0.7146158814430237, -0.5093744993209839], [-0.5302006602287292, -0.27570199966430664], [-0.3589249551296234, 0.0035287414211779833], [-0.20118756592273712, 0.2539542019367218], [-0.05721205472946167, 0.41584858298301697], [0.07293802499771118, 0.45759138464927673], [0.18934370577335358, 0.3807620406150818], [0.29221537709236145, 0.21642513573169708], [0.38187775015830994, 0.014415633864700794], [0.45875510573387146, -0.17099682986736298], [0.5233571529388428, -0.2951188087463379], [0.5762654542922974, -0.33304888010025024], [0.6181202530860901, -0.2839237451553345], [0.6496083736419678, -0.16873018443584442], [0.6714515686035156, -0.022873425856232643], [0.684395968914032, 0.11411601305007935], [0.6892019510269165, 0.20887750387191772], [0.6866353154182434, 0.24194346368312836], [0.6774590015411377, 0.2112169712781906], [0.662425696849823, 0.1307588815689087], [0.6422714591026306, 0.025656888261437416], [0.6177099347114563, -0.0753491222858429]], "RMSProp (lr=0.1)": [[-4.5, 1.600000023841858], [-3.5, 0.6000000238418579], [-2.8841376304626465, 0.24732717871665955], [-2.4297752380371094, 0.10275384783744812], [-2.070718288421631, 0.04249691590666771], [-1.7767659425735474, 0.017458174377679825], [-1.531043529510498, 0.007120730355381966], [-1.3228981494903564, 0.002883155830204487], [-1.145026445388794, 0.0011587372282519937], [-0.9921147227287292, 46220398508012295e-20], [-0.8601210713386536, 18296702182851732e-20], [-0.7458648681640625, 7187204755609855e-20], [-0.6467770934104919, 2801251321216114e-20], [-0.5607404112815857, 10831903637154028e-21], [-0.48598265647888184, 41550229070708156e-22], [-0.4210028052330017, 15809275737410644e-22], [-0.36451804637908936, 5965864602330839e-22], [-0.3154245615005493, 22325940562950564e-23], [-0.2727678716182709, 8284611396902619e-23], [-0.2357195019721985, 30479682777695416e-24], [-0.2035585343837738, 11116636500219101e-24], [-0.1756564825773239, 40189132022305785e-25], [-0.1514647901058197, 14400003411907392e-25], [-0.13050433993339539, 5113054979410947e-25], [-0.11235649883747101, 17988963096904342e-26], [-0.09665551036596298, 6270209351733058e-26], [-0.08308182656764984, 21649584902583285e-27], [-0.07135637104511261, 7403693977336978e-27], [-0.06123552843928337, 2507361505921235e-27], [-0.05250675231218338, 8407982426614224e-28], [-0.04498472437262535, 27913104770280195e-29], [-0.03850795701146126, 9172751534031187e-29], [-0.03293585032224655, 2983306960843701e-29], [-0.02814607508480549, 9601367484813987e-30], [-0.02403227984905243, 30572671672925156e-31], [-0.020502077415585518, 9629972634475712e-31], [-0.01747528277337551, 30000763497268525e-32], [-0.01488235592842102, 9242246479243608e-32], [-0.012663040310144424, 2815014076781671e-32], [-0.010765167884528637, 8475380237363252e-33], [-0.009143613278865814, 2521905770009833e-33]], "Adam (lr=0.2)": [[-4.5, 1.600000023841858], [-4.300000190734863, 1.399999976158142], [-4.1002888679504395, 1.201136589050293], [-3.9010777473449707, 1.004440188407898], [-3.702594041824341, 0.8112004995346069], [-3.505080223083496, 0.6230086088180542], [-3.3087944984436035, 0.44178497791290283], [-3.114010810852051, 0.2697755694389343], [-2.9210188388824463, 0.10949276387691498], [-2.730123519897461, -0.03641985356807709], [-2.541645050048828, -0.16540370881557465], [-2.355917453765869, -0.2752556800842285], [-2.1732876300811768, -0.3643916845321655], [-1.9941139221191406, -0.4320300817489624], [-1.8187639713287354, -0.47824621200561523], [-1.6476125717163086, -0.5038987994194031], [-1.4810385704040527, -0.5104721784591675], [-1.3194217681884766, -0.4998919367790222], [-1.16313898563385, -0.4743577241897583], [-1.0125598907470703, -0.4362150728702545], [-0.868042528629303, -0.3878677189350128], [-0.729928195476532, -0.33172228932380676], [-0.5985366106033325, -0.2701530456542969], [-0.474160760641098, -0.20547544956207275], [-0.3570619821548462, -0.13991978764533997], [-0.2474651336669922, -0.07559910416603088], [-0.14555443823337555, -0.01446906104683876], [-0.05146971344947815, 0.04171881079673767], [0.034696608781814575, 0.09146662801504135], [0.11290158331394196, 0.13357609510421753], [0.18315309286117554, 0.16718429327011108], [0.24551008641719818, 0.1917838603258133], [0.3000820279121399, 0.20722481608390808], [0.34702736139297485, 0.21369844675064087], [0.3865513205528259, 0.21170589327812195], [0.41890281438827515, 0.2020159214735031], [0.44437092542648315, 0.1856161504983902], [0.46328091621398926, 0.1636614203453064], [0.4759897291660309, 0.13742169737815857], [0.4828815460205078, 0.10823085904121399], [0.48436301946640015, 0.07743699848651886]] };
const d$3 = {
  curvature,
  paths
};
const _sfc_main$3 = /* @__PURE__ */ defineComponent({
  __name: "OptimizerRace",
  __ssrInlineRender: true,
  setup(__props) {
    const [ca, cb] = d$3.curvature;
    const runs = Object.entries(d$3.paths);
    const COLORS = ["#dc2626", "#d97706", "#7c3aed", "#0d9488"];
    const steps = runs[0][1].length;
    const p = reactive(usePlayer(() => steps, { interval: 260, start: "last" }));
    const X = (a) => (a + 5) * 100;
    const Y = (b) => (2 - b) * 100;
    const LEVELS = [0.5, 2, 5, 10, 20, 35];
    const f = (a, b) => 0.5 * (ca * a * a + cb * b * b);
    const poly = (pts) => pts.slice(0, p.frame + 1).map(([a, b]) => `${X(a)},${Y(b)}`).join(" ");
    const cur = computed(() => runs.map(([, pts]) => pts[p.frame]));
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card opt" }, _attrs))} data-v-2dff63ba><svg viewBox="0 0 650 400" class="opt-svg" role="img" aria-label="四种优化器在狭长山谷里从同一点出发，逐步走向最低点" data-v-2dff63ba><defs data-v-2dff63ba><clipPath id="opt-clip" data-v-2dff63ba><rect width="650" height="400" data-v-2dff63ba></rect></clipPath></defs><g clip-path="url(#opt-clip)" data-v-2dff63ba><!--[-->`);
      ssrRenderList(LEVELS, (L) => {
        _push(`<ellipse${ssrRenderAttr("cx", X(0))}${ssrRenderAttr("cy", Y(0))}${ssrRenderAttr("rx", Math.sqrt(2 * L / unref(ca)) * 100)}${ssrRenderAttr("ry", Math.sqrt(2 * L / unref(cb)) * 100)} class="lvl" data-v-2dff63ba></ellipse>`);
      });
      _push(`<!--]--><text${ssrRenderAttr("x", X(0) + 10)}${ssrRenderAttr("y", Y(0) + 34)} class="lbl" data-v-2dff63ba>最低点</text><path${ssrRenderAttr("d", `M${X(0) - 7} ${Y(0)}h14M${X(0)} ${Y(0) - 7}v14`)} class="star" data-v-2dff63ba></path><text${ssrRenderAttr("x", X(unref(runs)[0][1][0][0]) - 4)}${ssrRenderAttr("y", Y(unref(runs)[0][1][0][1]) - 12)} class="lbl" data-v-2dff63ba>起点</text><!--[-->`);
      ssrRenderList(unref(runs), ([name, pts], k2) => {
        _push(`<g data-v-2dff63ba><polyline${ssrRenderAttr("points", poly(pts))}${ssrRenderAttr("stroke", COLORS[k2])} class="path" data-v-2dff63ba></polyline><!--[-->`);
        ssrRenderList(pts.slice(0, p.frame + 1), (q2, s) => {
          _push(`<circle${ssrRenderAttr("cx", X(q2[0]))}${ssrRenderAttr("cy", Y(q2[1]))} r="2.4"${ssrRenderAttr("fill", COLORS[k2])} data-v-2dff63ba></circle>`);
        });
        _push(`<!--]--><circle${ssrRenderAttr("cx", X(cur.value[k2][0]))}${ssrRenderAttr("cy", Y(cur.value[k2][1]))} r="7"${ssrRenderAttr("fill", COLORS[k2])} class="head" data-v-2dff63ba></circle></g>`);
      });
      _push(`<!--]--></g></svg><div class="opt-legend" data-v-2dff63ba><!--[-->`);
      ssrRenderList(unref(runs), ([name], k2) => {
        _push(`<div class="opt-item" data-v-2dff63ba><span class="sw" style="${ssrRenderStyle({ background: COLORS[k2] })}" data-v-2dff63ba></span><span class="nm" data-v-2dff63ba>${ssrInterpolate(name)}</span><span class="lv" data-v-2dff63ba>损失 ${ssrInterpolate(f(cur.value[k2][0], cur.value[k2][1]).toFixed(3))}</span></div>`);
      });
      _push(`<!--]--></div><p class="anim-caption" data-v-2dff63ba> 损失 f = 0.5(a² + 25b²)：b 方向比 a 方向陡 25 倍，像一条狭长的山谷，椭圆是等高线。四种优化器从同一点出发，各走 ${ssrInterpolate(unref(steps) - 1)} 步。 SGD 在陡的 b 方向来回折返，沿缓的 a 方向挪得很慢；Momentum 记住过去的方向，越走越快，冲过了谷底；RMSProp 给每个方向单独定步长，几乎直达最低点；Adam 两者兼有，这次也冲过了头。 </p>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: `第 ${p.frame} / ${unref(steps) - 1} 步`
      }, null, _parent));
      _push(`<figcaption data-v-2dff63ba>轨迹是 PyTorch 自带优化器的真实运行记录（scripts/tinyllm-figure-data.py）。一开始显示全部 ${ssrInterpolate(unref(steps) - 1)} 步的结果；点“播放”从起点重演，四种优化器同时走。<a${ssrRenderAttr("href", unref(withBase)("/tinyllm/figures/optimizer-paths.svg"))} target="_blank" data-v-2dff63ba>打开静态图</a>（打印或不便播放时使用）。</figcaption></figure>`);
    };
  }
});
const _sfc_setup$3 = _sfc_main$3.setup;
_sfc_main$3.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/OptimizerRace.vue");
  return _sfc_setup$3 ? _sfc_setup$3(props, ctx) : void 0;
};
const OptimizerRace = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["__scopeId", "data-v-2dff63ba"]]);
const w = 2;
const x = 3;
const target = 1;
const lr = 0.01;
const values = { "p": 6, "d": 5, "L": 25 };
const grads = { "L": 1, "d": 10, "p": 10, "w": 30 };
const new_w = 1.7;
const new_loss = 16.810003;
const d$2 = {
  w,
  x,
  target,
  lr,
  values,
  grads,
  new_w,
  new_loss
};
const _sfc_main$2 = /* @__PURE__ */ defineComponent({
  __name: "BackpropFlow",
  __ssrInlineRender: true,
  setup(__props) {
    const v = d$2.values, g = d$2.grads;
    const nodes = [
      { name: "w", sub: "参数", val: d$2.w, grad: g.w, gname: "∂L/∂w" },
      { name: "p = w·x", sub: `乘以 x = ${d$2.x}`, val: v.p, grad: g.p, gname: "∂L/∂p" },
      { name: "d = p − t", sub: `减去 t = ${d$2.target}`, val: v.d, grad: g.d, gname: "∂L/∂d" },
      { name: "L = d²", sub: "平方", val: v.L, grad: g.L, gname: "∂L/∂L" }
    ];
    const local = [`× x = ×${d$2.x}`, "× 1", `× 2d = ×${2 * v.d}`];
    const XS = [90, 270, 450, 630];
    const p = reactive(usePlayer(() => 9, { interval: 1300, start: "last" }));
    const fwd = (i) => p.frame >= i;
    const bwd = (i) => p.frame >= 4 + (3 - i);
    const fwdEdge = computed(() => p.frame >= 1 && p.frame <= 3 ? p.frame - 1 : -1);
    const bwdEdge = computed(() => p.frame >= 5 && p.frame <= 7 ? 7 - p.frame : -1);
    const n = (x2) => Number.isInteger(x2) ? String(x2) : x2.toFixed(2);
    const caption = computed(() => {
      const f = p.frame;
      if (f === 0) return `<b>起点</b>：参数 w = ${n(d$2.w)}，输入 x = ${n(d$2.x)}，目标 t = ${n(d$2.target)}。点“播放”，先从左往右算一遍。`;
      if (f === 1) return `<b>前向 ①</b>：p = w · x = ${n(d$2.w)} × ${n(d$2.x)} = ${n(v.p)}。PyTorch 一边算，一边把“这里做了乘法”记进计算图。`;
      if (f === 2) return `<b>前向 ②</b>：d = p − t = ${n(v.p)} − ${n(d$2.target)} = ${n(v.d)}。`;
      if (f === 3) return `<b>前向 ③</b>：L = d² = ${n(v.L)}。前向结束，得到损失。接下来调用 loss.backward()，沿原路往回走。`;
      if (f === 4) return `<b>反向 ①</b>：从终点出发，∂L/∂L = ${n(g.L)}。`;
      if (f === 5) return `<b>反向 ②</b>：经过“平方”，乘它的局部导数 2d = ${n(2 * v.d)}：∂L/∂d = ${n(g.L)} × ${n(2 * v.d)} = ${n(g.d)}。`;
      if (f === 6) return `<b>反向 ③</b>：经过“减去 t”，局部导数是 1：∂L/∂p = ${n(g.d)} × 1 = ${n(g.p)}。`;
      if (f === 7) return `<b>反向 ④</b>：经过“乘以 x”，局部导数是 x = ${n(d$2.x)}：∂L/∂w = ${n(g.p)} × ${n(d$2.x)} = ${n(g.w)}。这就是 w.grad。`;
      return `<b>更新</b>：梯度为正，说明 w 变大损失会变大，所以往反方向走一小步：w ← ${n(d$2.w)} − ${d$2.lr} × ${n(g.w)} = ${n(d$2.new_w)}，损失从 ${n(v.L)} 降到 ${d$2.new_loss.toFixed(2)}。`;
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card bp" }, _attrs))} data-v-8775d802><svg viewBox="0 0 720 250" class="bp-svg" role="img" aria-label="单参数计算图：前向从左往右算出 p、d、L，反向从 L 往左乘局部导数得到 w 的梯度" data-v-8775d802><defs data-v-8775d802><marker id="bp-f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto" data-v-8775d802><path d="M0 0L10 5L0 10Z" class="f-fill" data-v-8775d802></path></marker><marker id="bp-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto" data-v-8775d802><path d="M0 0L10 5L0 10Z" class="b-fill" data-v-8775d802></path></marker></defs><!--[-->`);
      ssrRenderList(3, (i) => {
        _push(`<g data-v-8775d802><line${ssrRenderAttr("x1", XS[i - 1] + 62)} y1="108"${ssrRenderAttr("x2", XS[i] - 64)} y2="108" class="${ssrRenderClass(["edge-f", { lit: fwd(i), now: fwdEdge.value === i - 1 }])}" marker-end="url(#bp-f)" data-v-8775d802></line><line${ssrRenderAttr("x1", XS[i] - 62)} y1="142"${ssrRenderAttr("x2", XS[i - 1] + 64)} y2="142" class="${ssrRenderClass(["edge-b", { lit: bwd(i - 1), now: bwdEdge.value === i - 1 }])}" marker-end="url(#bp-b)" data-v-8775d802></line><text${ssrRenderAttr("x", (XS[i - 1] + XS[i]) / 2)} y="164" class="${ssrRenderClass(["local", { lit: bwd(i - 1) }])}" data-v-8775d802>${ssrInterpolate(local[i - 1])}</text>`);
        if (fwdEdge.value === i - 1) {
          _push(`<circle${ssrRenderAttr("cx", XS[i - 1] + 62)} cy="108" r="6" class="pulse f" style="${ssrRenderStyle({ "--dx": XS[i] - XS[i - 1] - 126 + "px" })}" data-v-8775d802></circle>`);
        } else {
          _push(`<!---->`);
        }
        if (bwdEdge.value === i - 1) {
          _push(`<circle${ssrRenderAttr("cx", XS[i] - 62)} cy="142" r="6" class="pulse b" style="${ssrRenderStyle({ "--dx": -(XS[i] - XS[i - 1] - 126) + "px" })}" data-v-8775d802></circle>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</g>`);
      });
      _push(`<!--]--><!--[-->`);
      ssrRenderList(nodes, (nd, i) => {
        _push(`<g data-v-8775d802><rect${ssrRenderAttr("x", XS[i] - 60)} y="90" width="120" height="70" rx="10" class="${ssrRenderClass(["node", { param: i === 0 }])}" data-v-8775d802></rect><text${ssrRenderAttr("x", XS[i])} y="121" class="nname" data-v-8775d802>${ssrInterpolate(nd.name)}</text><text${ssrRenderAttr("x", XS[i])} y="145" class="nsub" data-v-8775d802>${ssrInterpolate(nd.sub)}</text><text${ssrRenderAttr("x", XS[i])} y="70" class="${ssrRenderClass(["val", { show: fwd(i) }])}" data-v-8775d802>值 ${ssrInterpolate(i === 0 && p.frame === 8 ? `${n(unref(d$2).w)} → ${n(unref(d$2).new_w)}` : n(nd.val))}</text><text${ssrRenderAttr("x", XS[i])} y="200" class="${ssrRenderClass(["grad", { show: bwd(i) }])}" data-v-8775d802>${ssrInterpolate(nd.gname)} = ${ssrInterpolate(n(nd.grad))}</text></g>`);
      });
      _push(`<!--]--><text x="20" y="30" class="legend f" data-v-8775d802>前向：从左往右算数值</text><text x="700" y="30" class="legend b" text-anchor="end" data-v-8775d802>反向：从右往左，每过一个运算乘它的局部导数</text>`);
      if (p.frame === 8) {
        _push(`<text x="360" y="236" class="upd" data-v-8775d802>L：${ssrInterpolate(n(unref(v).L))} → ${ssrInterpolate(unref(d$2).new_loss.toFixed(2))}</text>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</svg><p class="anim-caption" aria-live="polite" data-v-8775d802>${caption.value ?? ""}</p>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: p.frame === 0 ? "起点" : p.frame <= 3 ? `前向 ${p.frame}/3` : p.frame <= 7 ? `反向 ${p.frame - 3}/4` : "更新"
      }, null, _parent));
      _push(`<figcaption data-v-8775d802>数值来自本章 tensors-and-autograd.py 的真实运行（retain_grad 取出中间结果的梯度）。一开始显示全部算完的状态；点“播放”从头重演：先前向，再反向，最后更新一次参数。<a${ssrRenderAttr("href", unref(withBase)("/tinyllm/figures/compute-graph.svg"))} target="_blank" data-v-8775d802>打开静态图</a>（打印或不便播放时使用）。</figcaption></figure>`);
    };
  }
});
const _sfc_setup$2 = _sfc_main$2.setup;
_sfc_main$2.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/BackpropFlow.vue");
  return _sfc_setup$2 ? _sfc_setup$2(props, ctx) : void 0;
};
const BackpropFlow = /* @__PURE__ */ _export_sfc(_sfc_main$2, [["__scopeId", "data-v-8775d802"]]);
const tokens = ["春", "乃", "发", "生", "。", "随", "风", "潜", "入", "夜", "，", "润"];
const no_cache = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
const with_cache = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1];
const d$1 = {
  tokens,
  no_cache,
  with_cache
};
const _sfc_main$1 = /* @__PURE__ */ defineComponent({
  __name: "KVCacheRace",
  __ssrInlineRender: true,
  setup(__props) {
    const tokens2 = d$1.tokens;
    const T = tokens2.length;
    const p = reactive(usePlayer(() => T, { interval: 900, start: "last" }));
    const t = computed(() => p.frame);
    const sum = (a, k2) => a.slice(0, k2 + 1).reduce((s, x2) => s + x2, 0);
    const panels = computed(() => [
      {
        key: "full",
        title: "不缓存：每一步把前面所有字重新算一遍 K、V",
        now: d$1.no_cache[t.value],
        total: sum(d$1.no_cache, t.value),
        state: (j) => j > t.value ? "future" : "recompute"
      },
      {
        key: "cache",
        title: "KV cache：旧字的 K、V 从缓存里拿，只算新来的一个",
        now: d$1.with_cache[t.value],
        total: sum(d$1.with_cache, t.value),
        state: (j) => j > t.value ? "future" : j === t.value ? "new" : "cached"
      }
    ]);
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card kv" }, _attrs))} data-v-10c27ea3><!--[-->`);
      ssrRenderList(panels.value, (pn) => {
        _push(`<div class="kv-panel" data-v-10c27ea3><div class="kv-title" data-v-10c27ea3>${ssrInterpolate(pn.title)}</div><div class="kv-grid" style="${ssrRenderStyle({ gridTemplateColumns: `2.4rem repeat(${unref(T)}, minmax(1.6rem, 1fr))` })}" data-v-10c27ea3><span class="kv-rl" data-v-10c27ea3></span><!--[-->`);
        ssrRenderList(unref(tokens2), (c, j) => {
          _push(`<span class="${ssrRenderClass(["kv-tok", { cur: j === t.value, fut: j > t.value }])}" data-v-10c27ea3>${ssrInterpolate(c)}</span>`);
        });
        _push(`<!--]--><!--[-->`);
        ssrRenderList(["K", "V"], (row) => {
          _push(`<!--[--><span class="kv-rl" data-v-10c27ea3>${ssrInterpolate(row)}</span><!--[-->`);
          ssrRenderList(unref(tokens2), (_, j) => {
            _push(`<span class="${ssrRenderClass(["kv-cell", pn.state(j)])}" data-v-10c27ea3></span>`);
          });
          _push(`<!--]--><!--]-->`);
        });
        _push(`<!--]--></div><div class="kv-count" data-v-10c27ea3>这一步算了 <b data-v-10c27ea3>${ssrInterpolate(pn.now)}</b> 行 K、V · 累计 <b data-v-10c27ea3>${ssrInterpolate(pn.total)}</b> 行</div></div>`);
      });
      _push(`<!--]--><div class="kv-key" data-v-10c27ea3><span data-v-10c27ea3><i class="kv-cell recompute" data-v-10c27ea3></i>本步重新计算</span><span data-v-10c27ea3><i class="kv-cell new" data-v-10c27ea3></i>本步新算</span><span data-v-10c27ea3><i class="kv-cell cached" data-v-10c27ea3></i>从缓存读取</span></div><p class="anim-caption" data-v-10c27ea3> 生成第 ${ssrInterpolate(t.value + 1)} 个字“${ssrInterpolate(unref(tokens2)[t.value])}”时，新字的 Q 都要和前面所有字的 K 打分、对所有 V 加权求和。区别只在 K、V 从哪里来： 不缓存时前面 ${ssrInterpolate(t.value + 1)} 个字全部重算，生成 ${ssrInterpolate(unref(T))} 个字一共算 ${ssrInterpolate(sum(unref(d$1).no_cache, unref(T) - 1))} 行；有缓存时每步只算 1 行，一共 ${ssrInterpolate(sum(unref(d$1).with_cache, unref(T) - 1))} 行，两种做法的输出完全一样。 </p>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: `第 ${t.value + 1} / ${unref(T)} 个字`
      }, null, _parent));
      _push(`<figcaption data-v-10c27ea3>每一步的行数由本章 inference-efficiency.py 中 count 那段代码真实数出，并核对了两种做法输出一致；字只是位置的标签。一开始显示生成完 ${ssrInterpolate(unref(T))} 个字时的状态；点“播放”从第一个字重演。</figcaption></figure>`);
    };
  }
});
const _sfc_setup$1 = _sfc_main$1.setup;
_sfc_main$1.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/KVCacheRace.vue");
  return _sfc_setup$1 ? _sfc_setup$1(props, ctx) : void 0;
};
const KVCacheRace = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["__scopeId", "data-v-10c27ea3"]]);
const lens = { "举头望明月，低头思故": { "answer": "乡", "stops": [{ "where": "嵌入", "top": [["故", 0.9974], ["雨", 1e-4], ["海", 1e-4], ["春", 1e-4], ["乡", 1e-4]], "rms": 0.16946062445640564 }, { "where": "第 1 层 注意力", "top": [["故", 0.9824], ["圆", 7e-4], ["辛", 6e-4], ["海", 5e-4], ["去", 4e-4]], "rms": 0.17852449417114258, "update": 0.0912628024816513, "attn": [[0.053, 0.117, 0.072, 0.074, 0.06, 0.187, 0.043, 0.073, 0.03, 0.292], [0.038, 0.199, 0.069, 0.091, 0.026, 0.054, 0.243, 0.171, 0.032, 0.076], [0.03, 0.065, 0.054, 0.078, 0.103, 0.241, 0.111, 0.107, 0.078, 0.132], [0.079, 0.103, 0.164, 0.111, 0.054, 0.086, 0.078, 0.102, 0.095, 0.128]] }, { "where": "第 1 层 前馈", "top": [["乡", 0.1048], ["开", 0.042], ["眠", 0.0291], ["出", 0.0237], ["连", 0.0228]], "rms": 0.4123653769493103, "update": 0.3752816617488861 }, { "where": "第 2 层 注意力", "top": [["乡", 0.2288], ["阳", 0.023], ["开", 0.0214], ["故", 0.0209], ["眠", 0.0206]], "rms": 0.4103984534740448, "update": 0.12694096565246582, "attn": [[0.035, 0.073, 0.085, 0.03, 0.087, 0.051, 0.207, 0.236, 0.091, 0.104], [0.014, 0.013, 0.025, 0.038, 0.06, 0.206, 0.09, 0.081, 0.235, 0.237], [0.024, 0.04, 0.133, 0.027, 0.047, 0.158, 0.177, 0.138, 0.168, 0.088], [0.038, 0.061, 0.061, 0.125, 0.147, 0.099, 0.085, 0.107, 0.16, 0.116]] }, { "where": "第 2 层 前馈", "top": [["乡", 0.5253], ["三", 0.0365], ["晓", 0.0197], ["云", 0.0124], ["觉", 0.0113]], "rms": 0.5611101388931274, "update": 0.3279368579387665 }, { "where": "第 3 层 注意力", "top": [["乡", 0.5528], ["三", 0.0427], ["晓", 0.025], ["觉", 0.0144], ["石", 0.0104]], "rms": 0.5800420045852661, "update": 0.17307494580745697, "attn": [[0.023, 0.047, 0.084, 0.044, 0.024, 0.093, 0.052, 0.11, 0.144, 0.38], [0.032, 0.025, 0.065, 0.16, 0.054, 0.097, 0.14, 0.106, 0.196, 0.124], [0.081, 0.016, 0.049, 0.034, 0.03, 0.172, 0.056, 0.099, 0.315, 0.148], [0.052, 0.125, 0.045, 0.111, 0.064, 0.059, 0.053, 0.138, 0.186, 0.167]] }, { "where": "第 3 层 前馈", "top": [["乡", 0.7077], ["三", 0.029], ["不", 93e-4], ["相", 82e-4], ["村", 62e-4]], "rms": 0.6598119139671326, "update": 0.3196936249732971 }, { "where": "第 4 层 注意力", "top": [["乡", 0.7613], ["三", 0.0208], ["不", 82e-4], ["相", 57e-4], ["村", 55e-4]], "rms": 0.5888983011245728, "update": 0.15517418086528778, "attn": [[0.032, 0.01, 0.018, 0.027, 0.041, 0.041, 0.03, 0.103, 0.326, 0.371], [0.165, 0.166, 0.072, 0.024, 0.014, 0.057, 0.087, 0.115, 0.054, 0.246], [0.076, 0.098, 0.052, 0.064, 0.053, 0.048, 0.097, 0.154, 0.281, 0.076], [0.044, 0.101, 0.027, 0.059, 0.024, 0.065, 0.098, 0.17, 0.275, 0.138]] }, { "where": "第 4 层 前馈", "top": [["乡", 0.9713], ["人", 16e-4], ["归", 15e-4], ["山", 12e-4], ["三", 8e-4]], "rms": 0.7715571522712708, "update": 0.47390061616897583 }] }, "床前明月光，疑是地上": { "answer": "霜", "stops": [{ "where": "嵌入", "top": [["上", 0.997], ["随", 1e-4], ["荣", 1e-4], ["图", 1e-4], ["两", 1e-4]], "rms": 0.168891042470932 }, { "where": "第 1 层 注意力", "top": [["上", 0.9763], ["图", 15e-4], ["随", 9e-4], ["荣", 6e-4], ["芳", 6e-4]], "rms": 0.18049658834934235, "update": 0.09787967801094055, "attn": [[0.091, 0.085, 0.07, 0.12, 0.046, 0.048, 0.21, 0.037, 0.171, 0.122], [0.053, 0.087, 0.156, 0.073, 0.195, 0.101, 0.043, 0.087, 0.06, 0.147], [0.067, 0.069, 0.044, 0.085, 0.113, 0.106, 0.075, 0.08, 0.148, 0.212], [0.08, 0.086, 0.078, 0.131, 0.075, 0.086, 0.081, 0.185, 0.09, 0.109]] }, { "where": "第 1 层 前馈", "top": [["上", 0.1503], ["霜", 0.0361], ["休", 0.0318], ["比", 0.0227], ["金", 0.018]], "rms": 0.3977760076522827, "update": 0.34176087379455566 }, { "where": "第 2 层 注意力", "top": [["上", 0.0826], ["霜", 0.0366], ["流", 0.0328], ["休", 0.0233], ["比", 0.0228]], "rms": 0.4225231111049652, "update": 0.12656667828559875, "attn": [[0.048, 0.081, 0.052, 0.069, 0.085, 0.317, 0.127, 0.045, 0.092, 0.085], [0.213, 0.106, 0.04, 0.068, 0.017, 0.079, 0.082, 0.064, 0.078, 0.252], [0.069, 0.067, 0.111, 0.052, 0.116, 0.075, 0.076, 0.128, 0.166, 0.141], [0.053, 0.091, 0.075, 0.06, 0.083, 0.358, 0.04, 0.124, 0.023, 0.095]] }, { "where": "第 2 层 前馈", "top": [["霜", 0.0376], ["未", 0.033], ["手", 0.0263], ["地", 0.0217], ["花", 0.0213]], "rms": 0.4699304699897766, "update": 0.22365856170654297 }, { "where": "第 3 层 注意力", "top": [["霜", 0.0875], ["上", 0.0269], ["未", 0.0241], ["收", 0.024], ["萧", 0.0194]], "rms": 0.4425106942653656, "update": 0.14239582419395447, "attn": [[0.045, 0.036, 0.061, 0.118, 0.082, 0.092, 0.056, 0.067, 0.244, 0.199], [0.031, 0.039, 0.062, 0.038, 0.096, 0.106, 0.032, 0.205, 0.105, 0.287], [0.059, 0.091, 0.122, 0.024, 0.038, 0.064, 0.074, 0.286, 0.166, 0.075], [0.049, 0.021, 0.021, 0.023, 0.044, 0.146, 0.039, 0.07, 0.043, 0.545]] }, { "where": "第 3 层 前馈", "top": [["霜", 0.2756], ["未", 0.0234], ["收", 0.023], ["萋", 0.0202], ["岳", 0.0189]], "rms": 0.4839615225791931, "update": 0.2684531807899475 }, { "where": "第 4 层 注意力", "top": [["霜", 0.4298], ["休", 0.0149], ["未", 0.0147], ["上", 0.0141], ["返", 0.0135]], "rms": 0.49246829748153687, "update": 0.12438704073429108, "attn": [[0.035, 0.027, 0.076, 0.081, 0.127, 0.145, 0.159, 0.127, 0.118, 0.105], [0.051, 0.085, 0.109, 0.06, 0.208, 0.164, 0.05, 0.059, 0.098, 0.115], [0.058, 0.084, 0.265, 0.038, 0.045, 0.129, 0.12, 0.112, 0.089, 0.059], [0.08, 0.09, 0.148, 0.085, 0.152, 0.106, 0.109, 0.091, 0.085, 0.053]] }, { "where": "第 4 层 前馈", "top": [["霜", 0.7023], ["收", 0.0103], ["休", 84e-4], ["。", 71e-4], ["地", 64e-4]], "rms": 0.6143794655799866, "update": 0.31865838170051575 }] }, "春眠不觉晓，处处闻啼": { "answer": "鸟", "stops": [{ "where": "嵌入", "top": [["啼", 0.9879], ["披", 5e-4], ["鸡", 5e-4], ["洞", 3e-4], ["移", 3e-4]], "rms": 0.15304158627986908 }, { "where": "第 1 层 注意力", "top": [["啼", 0.9634], ["洞", 17e-4], ["鸡", 14e-4], ["移", 1e-3], ["衣", 1e-3]], "rms": 0.20130518078804016, "update": 0.08949049562215805, "attn": [[0.106, 0.054, 0.109, 0.124, 0.063, 0.099, 0.113, 0.097, 0.127, 0.106], [0.113, 0.087, 0.102, 0.131, 0.097, 0.067, 0.11, 0.107, 0.1, 0.086], [0.128, 0.044, 0.098, 0.092, 0.094, 0.21, 0.086, 0.079, 0.075, 0.093], [0.067, 0.062, 0.077, 0.055, 0.069, 0.05, 0.184, 0.164, 0.098, 0.173]] }, { "where": "第 1 层 前馈", "top": [["啼", 0.7697], ["鸟", 98e-4], ["吠", 55e-4], ["送", 5e-3], ["百", 43e-4]], "rms": 0.24698850512504578, "update": 0.14744655787944794 }, { "where": "第 2 层 注意力", "top": [["啼", 0.8002], ["鸟", 0.0137], ["子", 6e-3], ["路", 49e-4], ["送", 47e-4]], "rms": 0.27230048179626465, "update": 0.1211991012096405, "attn": [[0.025, 0.029, 0.084, 0.124, 0.164, 0.111, 0.116, 0.156, 0.026, 0.166], [0.054, 0.118, 0.087, 0.072, 0.049, 0.254, 0.13, 0.125, 0.041, 0.069], [0.048, 0.042, 0.08, 0.242, 0.083, 0.065, 0.092, 0.069, 0.058, 0.222], [0.039, 0.089, 0.103, 0.197, 0.077, 0.061, 0.112, 0.14, 0.069, 0.114]] }, { "where": "第 2 层 前馈", "top": [["鸟", 0.3603], ["啼", 0.2891], ["入", 79e-4], ["百", 59e-4], ["望", 57e-4]], "rms": 0.426192045211792, "update": 0.2577035427093506 }, { "where": "第 3 层 注意力", "top": [["鸟", 0.453], ["啼", 0.1767], ["汉", 0.0105], ["闻", 96e-4], ["望", 71e-4]], "rms": 0.4272015392780304, "update": 0.18661579489707947, "attn": [[0.143, 0.107, 0.089, 0.097, 0.089, 0.167, 0.105, 0.087, 0.055, 0.062], [0.11, 0.068, 0.111, 0.104, 0.082, 0.124, 0.184, 0.119, 0.055, 0.042], [0.05, 0.055, 0.253, 0.121, 0.052, 0.07, 0.098, 0.112, 0.116, 0.072], [0.092, 0.028, 0.045, 0.05, 0.055, 0.118, 0.209, 0.127, 0.194, 0.082]] }, { "where": "第 3 层 前馈", "top": [["鸟", 0.8873], ["啼", 0.0145], ["岸", 35e-4], ["闻", 32e-4], ["，", 26e-4]], "rms": 0.5383962988853455, "update": 0.2666226923465729 }, { "where": "第 4 层 注意力", "top": [["鸟", 0.8373], ["啼", 0.0377], ["岸", 39e-4], ["芳", 29e-4], ["闻", 26e-4]], "rms": 0.5068483948707581, "update": 0.13541847467422485, "attn": [[0.117, 0.104, 0.076, 0.112, 0.06, 0.125, 0.122, 0.196, 0.042, 0.046], [0.058, 0.08, 0.079, 0.088, 0.063, 0.075, 0.077, 0.184, 0.153, 0.143], [0.076, 0.096, 0.086, 0.262, 0.132, 0.092, 0.082, 0.071, 0.053, 0.049], [0.156, 0.102, 0.107, 0.123, 0.107, 0.109, 0.096, 0.08, 0.076, 0.044]] }, { "where": "第 4 层 前馈", "top": [["鸟", 0.9727], ["啼", 38e-4], ["。", 27e-4], ["洞", 8e-4], ["望", 7e-4]], "rms": 0.7187322974205017, "update": 0.3950784206390381 }] } };
const d = {
  lens
};
const _sfc_main = /* @__PURE__ */ defineComponent({
  __name: "ResidualStreamLens",
  __ssrInlineRender: true,
  setup(__props) {
    const prompts = Object.keys(d.lens);
    const prompt = ref(prompts[0]);
    const cur = computed(() => d.lens[prompt.value]);
    const stops = computed(() => cur.value.stops);
    const p = reactive(usePlayer(() => stops.value.length, { interval: 1400, start: "last" }));
    const stop = computed(() => stops.value[p.frame]);
    const ctx = computed(() => [...prompt.value]);
    const last = computed(() => ctx.value[ctx.value.length - 1]);
    const answerP = (s) => {
      var _a;
      return (_a = s.top.find(([c]) => c === cur.value.answer)) == null ? void 0 : _a[1];
    };
    const pct = (x2) => x2 >= 0.995 ? ">99%" : x2 >= 0.01 ? Math.round(x2 * 100) + "%" : "<1%";
    const caption = computed(() => {
      const s = stop.value, a = cur.value.answer, ap = answerP(s);
      const read = ap === void 0 ? `正确答案“${a}”还不在前 5 名` : `读出“${a}”的概率是 ${pct(ap)}`;
      if (p.frame === 0)
        return `<b>嵌入</b>：刚查完词表，还没进任何 Block。输入和输出共用一张表，“${last.value}”的向量最像的就是“${last.value}”自己，所以这时读出来几乎全是“${s.top[0][0]}”。`;
      const isAttn = !!s.attn;
      const what = isAttn ? `最后一个字“${last.value}”从前面的字里取回信息（下方是 4 个头各自看向哪里），结果加回残差流` : "只加工当前这个位置，不看别的字，结果加回残差流";
      const end = p.frame === stops.value.length - 1 ? "这就是模型最终交给输出层的结果。" : "";
      return `<b>${s.where}</b>：${what}。${read}。${end}`;
    });
    const heat = (w2, row) => `color-mix(in srgb, var(--vp-c-brand-1) ${Math.round(w2 / Math.max(...row) * 85)}%, transparent)`;
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<figure${ssrRenderAttrs(mergeProps({ class: "anim-card rsl" }, _attrs))} data-v-44d83c7c><div class="rsl-prompts" data-v-44d83c7c><!--[-->`);
      ssrRenderList(unref(prompts), (pr) => {
        _push(`<button class="${ssrRenderClass({ on: pr === prompt.value })}" data-v-44d83c7c>${ssrInterpolate(pr)}<b data-v-44d83c7c>?</b></button>`);
      });
      _push(`<!--]--></div><div class="rsl-body" data-v-44d83c7c><ol class="rsl-route" data-v-44d83c7c><!--[-->`);
      ssrRenderList(stops.value, (s, k2) => {
        _push(`<li class="${ssrRenderClass({ on: k2 === p.frame, past: k2 < p.frame })}" data-v-44d83c7c><span class="nm" data-v-44d83c7c>${ssrInterpolate(s.where)}</span><span class="mini" data-v-44d83c7c><span style="${ssrRenderStyle({ width: (k2 <= p.frame ? (answerP(s) ?? 0) * 100 : 0) + "%" })}" data-v-44d83c7c></span></span><span class="pv" data-v-44d83c7c>${ssrInterpolate(k2 <= p.frame ? answerP(s) === void 0 ? "—" : pct(answerP(s)) : "")}</span></li>`);
      });
      _push(`<!--]--></ol><div class="rsl-main" data-v-44d83c7c><div class="rsl-sub" data-v-44d83c7c>如果在这里就把残差流交给输出层，模型会猜：</div><!--[-->`);
      ssrRenderList(stop.value.top, ([c, pr], k2) => {
        _push(`<div class="${ssrRenderClass(["rsl-row", { ans: c === cur.value.answer }])}" data-v-44d83c7c><span class="ch" data-v-44d83c7c>${ssrInterpolate(c === "\n" ? "⏎" : c)}</span><span class="tr" data-v-44d83c7c><span class="bar" style="${ssrRenderStyle({ width: Math.max(pr * 100, 0.5) + "%" })}" data-v-44d83c7c></span></span><span class="pv" data-v-44d83c7c>${ssrInterpolate(pct(pr))}</span></div>`);
      });
      _push(`<!--]--><div class="rsl-meta" data-v-44d83c7c>残差流长度（RMS）${ssrInterpolate(stop.value.rms.toFixed(2))}`);
      if (stop.value.update !== void 0) {
        _push(`<!--[--> · 这一站加上去 ${ssrInterpolate(stop.value.update.toFixed(2))}<!--]-->`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div>`);
      if (stop.value.attn) {
        _push(`<div class="rsl-attn" data-v-44d83c7c><div class="rsl-sub" data-v-44d83c7c>“${ssrInterpolate(last.value)}”在看谁（4 个头，颜色越深权重越大）：</div><div class="hm" style="${ssrRenderStyle({ gridTemplateColumns: `3rem repeat(${ctx.value.length}, 1fr)` })}" data-v-44d83c7c><span data-v-44d83c7c></span><!--[-->`);
        ssrRenderList(ctx.value, (c, j) => {
          _push(`<span class="hc" data-v-44d83c7c>${ssrInterpolate(c)}</span>`);
        });
        _push(`<!--]--><!--[-->`);
        ssrRenderList(stop.value.attn, (row, h2) => {
          _push(`<!--[--><span class="hl" data-v-44d83c7c>头 ${ssrInterpolate(h2 + 1)}</span><!--[-->`);
          ssrRenderList(row, (w2, j) => {
            _push(`<span class="cell" style="${ssrRenderStyle({ background: heat(w2, row) })}"${ssrRenderAttr("title", w2.toFixed(3))} data-v-44d83c7c></span>`);
          });
          _push(`<!--]--><!--]-->`);
        });
        _push(`<!--]--></div></div>`);
      } else if (p.frame > 0) {
        _push(`<div class="rsl-note" data-v-44d83c7c>前馈层不看别的字，这一站没有注意力权重。</div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div></div><p class="anim-caption" aria-live="polite" data-v-44d83c7c>${caption.value ?? ""}</p>`);
      _push(ssrRenderComponent(PlayerControls, {
        p,
        label: stop.value.where
      }, null, _parent));
      _push(`<figcaption data-v-44d83c7c>本章 transformer-block.py 里训练好的 4 层 Pre-Norm 模型的真实读数：在每一站之后，直接用最后的 RMSNorm 和输出层读出当前的残差流。一开始显示最后一站；点“播放”从嵌入开始，或点左边任意一站。</figcaption></figure>`);
    };
  }
});
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add(".vitepress/theme/components/ResidualStreamLens.vue");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const ResidualStreamLens = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-44d83c7c"]]);
const RawTheme = {
  extends: theme,
  Layout: _sfc_main$a,
  enhanceApp({ app }) {
    app.component("TinyLLMMap", TinyLLMMap);
    app.component("MiniRedisMap", MiniRedisMap);
    app.component("NextTokenPlayer", NextTokenPlayer);
    app.component("AttentionStepper", AttentionStepper);
    app.component("RopeSlider", RopeSlider);
    app.component("OptimizerRace", OptimizerRace);
    app.component("BackpropFlow", BackpropFlow);
    app.component("KVCacheRace", KVCacheRace);
    app.component("ResidualStreamLens", ResidualStreamLens);
  }
};
const ClientOnly = defineComponent({
  setup(_, { slots }) {
    const show = ref(false);
    onMounted(() => {
      show.value = true;
    });
    return () => show.value && slots.default ? slots.default() : null;
  }
});
function useCodeGroups() {
  if (inBrowser) {
    window.addEventListener("click", (e) => {
      var _a;
      const el = e.target;
      if (el.matches(".vp-code-group input")) {
        const group = (_a = el.parentElement) == null ? void 0 : _a.parentElement;
        if (!group)
          return;
        const i = Array.from(group.querySelectorAll("input")).indexOf(el);
        if (i < 0)
          return;
        const blocks = group.querySelector(".blocks");
        if (!blocks)
          return;
        const current = Array.from(blocks.children).find((child) => child.classList.contains("active"));
        if (!current)
          return;
        const next = blocks.children[i];
        if (!next || current === next)
          return;
        current.classList.remove("active");
        next.classList.add("active");
        const label = group == null ? void 0 : group.querySelector(`label[for="${el.id}"]`);
        label == null ? void 0 : label.scrollIntoView({ block: "nearest" });
      }
    });
  }
}
function useCopyCode() {
  if (inBrowser) {
    const timeoutIdMap = /* @__PURE__ */ new WeakMap();
    window.addEventListener("click", (e) => {
      var _a;
      const el = e.target;
      if (el.matches('div[class*="language-"] > button.copy')) {
        const parent = el.parentElement;
        const sibling = (_a = el.nextElementSibling) == null ? void 0 : _a.nextElementSibling;
        if (!parent || !sibling) {
          return;
        }
        const isShell = /language-(shellscript|shell|bash|sh|zsh)/.test(parent.className);
        const ignoredNodes = [".vp-copy-ignore", ".diff.remove"];
        const clone = sibling.cloneNode(true);
        clone.querySelectorAll(ignoredNodes.join(",")).forEach((node) => node.remove());
        let text = clone.textContent || "";
        if (isShell) {
          text = text.replace(/^ *(\$|>) /gm, "").trim();
        }
        copyToClipboard(text).then(() => {
          el.classList.add("copied");
          clearTimeout(timeoutIdMap.get(el));
          const timeoutId = setTimeout(() => {
            el.classList.remove("copied");
            el.blur();
            timeoutIdMap.delete(el);
          }, 2e3);
          timeoutIdMap.set(el, timeoutId);
        });
      }
    });
  }
}
async function copyToClipboard(text) {
  try {
    return navigator.clipboard.writeText(text);
  } catch {
    const element = document.createElement("textarea");
    const previouslyFocusedElement = document.activeElement;
    element.value = text;
    element.setAttribute("readonly", "");
    element.style.contain = "strict";
    element.style.position = "absolute";
    element.style.left = "-9999px";
    element.style.fontSize = "12pt";
    const selection = document.getSelection();
    const originalRange = selection ? selection.rangeCount > 0 && selection.getRangeAt(0) : null;
    document.body.appendChild(element);
    element.select();
    element.selectionStart = 0;
    element.selectionEnd = text.length;
    document.execCommand("copy");
    document.body.removeChild(element);
    if (originalRange) {
      selection.removeAllRanges();
      selection.addRange(originalRange);
    }
    if (previouslyFocusedElement) {
      previouslyFocusedElement.focus();
    }
  }
}
function useUpdateHead(route, siteDataByRouteRef) {
  let isFirstUpdate = true;
  let managedHeadElements = [];
  const updateHeadTags = (newTags) => {
    if (isFirstUpdate) {
      isFirstUpdate = false;
      newTags.forEach((tag) => {
        const headEl = createHeadElement(tag);
        for (const el of document.head.children) {
          if (el.isEqualNode(headEl)) {
            managedHeadElements.push(el);
            return;
          }
        }
      });
      return;
    }
    const newElements = newTags.map(createHeadElement);
    managedHeadElements.forEach((oldEl, oldIndex) => {
      const matchedIndex = newElements.findIndex((newEl) => newEl == null ? void 0 : newEl.isEqualNode(oldEl ?? null));
      if (matchedIndex !== -1) {
        delete newElements[matchedIndex];
      } else {
        oldEl == null ? void 0 : oldEl.remove();
        delete managedHeadElements[oldIndex];
      }
    });
    newElements.forEach((el) => el && document.head.appendChild(el));
    managedHeadElements = [...managedHeadElements, ...newElements].filter(Boolean);
  };
  watchEffect(() => {
    const pageData = route.data;
    const siteData2 = siteDataByRouteRef.value;
    const pageDescription = pageData && pageData.description;
    const frontmatterHead = pageData && pageData.frontmatter.head || [];
    const title = createTitle(siteData2, pageData);
    if (title !== document.title) {
      document.title = title;
    }
    const description = pageDescription || siteData2.description;
    let metaDescriptionElement = document.querySelector(`meta[name=description]`);
    if (metaDescriptionElement) {
      if (metaDescriptionElement.getAttribute("content") !== description) {
        metaDescriptionElement.setAttribute("content", description);
      }
    } else {
      createHeadElement(["meta", { name: "description", content: description }]);
    }
    updateHeadTags(mergeHead(siteData2.head, filterOutHeadDescription(frontmatterHead)));
  });
}
function createHeadElement([tag, attrs, innerHTML]) {
  const el = document.createElement(tag);
  for (const key in attrs) {
    el.setAttribute(key, attrs[key]);
  }
  if (innerHTML) {
    el.innerHTML = innerHTML;
  }
  if (tag === "script" && attrs.async == null) {
    el.async = false;
  }
  return el;
}
function isMetaDescription(headConfig) {
  return headConfig[0] === "meta" && headConfig[1] && headConfig[1].name === "description";
}
function filterOutHeadDescription(head) {
  return head.filter((h2) => !isMetaDescription(h2));
}
const hasFetched = /* @__PURE__ */ new Set();
const createLink = () => document.createElement("link");
const viaDOM = (url) => {
  const link2 = createLink();
  link2.rel = `prefetch`;
  link2.href = url;
  document.head.appendChild(link2);
};
const viaXHR = (url) => {
  const req = new XMLHttpRequest();
  req.open("GET", url, req.withCredentials = true);
  req.send();
};
let link;
const doFetch = inBrowser && (link = createLink()) && link.relList && link.relList.supports && link.relList.supports("prefetch") ? viaDOM : viaXHR;
function usePrefetch() {
  if (!inBrowser) {
    return;
  }
  if (!window.IntersectionObserver) {
    return;
  }
  let conn;
  if ((conn = navigator.connection) && (conn.saveData || /2g/.test(conn.effectiveType))) {
    return;
  }
  const rIC = window.requestIdleCallback || setTimeout;
  let observer = null;
  const observeLinks = () => {
    if (observer) {
      observer.disconnect();
    }
    observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const link2 = entry.target;
          observer.unobserve(link2);
          const { pathname } = link2;
          if (!hasFetched.has(pathname)) {
            hasFetched.add(pathname);
            const pageChunkPath = pathToFile(pathname);
            if (pageChunkPath)
              doFetch(pageChunkPath);
          }
        }
      });
    });
    rIC(() => {
      document.querySelectorAll("#app a").forEach((link2) => {
        const { hostname, pathname } = new URL(link2.href instanceof SVGAnimatedString ? link2.href.animVal : link2.href, link2.baseURI);
        const extMatch = pathname.match(/\.\w+$/);
        if (extMatch && extMatch[0] !== ".html") {
          return;
        }
        if (
          // only prefetch same tab navigation, since a new tab will load
          // the lean js chunk instead.
          link2.target !== "_blank" && // only prefetch inbound links
          hostname === location.hostname
        ) {
          if (pathname !== location.pathname) {
            observer.observe(link2);
          } else {
            hasFetched.add(pathname);
          }
        }
      });
    });
  };
  onMounted(observeLinks);
  const route = useRoute();
  watch(() => route.path, observeLinks);
  onUnmounted(() => {
    observer && observer.disconnect();
  });
}
function resolveThemeExtends(theme2) {
  if (theme2.extends) {
    const base2 = resolveThemeExtends(theme2.extends);
    return {
      ...base2,
      ...theme2,
      async enhanceApp(ctx) {
        if (base2.enhanceApp)
          await base2.enhanceApp(ctx);
        if (theme2.enhanceApp)
          await theme2.enhanceApp(ctx);
      }
    };
  }
  return theme2;
}
const Theme = resolveThemeExtends(RawTheme);
const VitePressApp = defineComponent({
  name: "VitePressApp",
  setup() {
    const { site, lang, dir } = useData$1();
    onMounted(() => {
      watchEffect(() => {
        document.documentElement.lang = lang.value;
        document.documentElement.dir = dir.value;
      });
    });
    if (site.value.router.prefetchLinks) {
      usePrefetch();
    }
    useCopyCode();
    useCodeGroups();
    if (Theme.setup)
      Theme.setup();
    return () => h(Theme.Layout);
  }
});
async function createApp() {
  globalThis.__VITEPRESS__ = true;
  const router = newRouter();
  const app = newApp();
  app.provide(RouterSymbol, router);
  const data = initData(router.route);
  app.provide(dataSymbol, data);
  app.component("Content", Content);
  app.component("ClientOnly", ClientOnly);
  Object.defineProperties(app.config.globalProperties, {
    $frontmatter: {
      get() {
        return data.frontmatter.value;
      }
    },
    $params: {
      get() {
        return data.page.value.params;
      }
    }
  });
  if (Theme.enhanceApp) {
    await Theme.enhanceApp({
      app,
      router,
      siteData: siteDataRef
    });
  }
  return { app, router, data };
}
function newApp() {
  return createSSRApp(VitePressApp);
}
function newRouter() {
  let isInitialPageLoad = inBrowser;
  return createRouter((path) => {
    let pageFilePath = pathToFile(path);
    let pageModule = null;
    if (pageFilePath) {
      if (isInitialPageLoad) {
        pageFilePath = pageFilePath.replace(/\.js$/, ".lean.js");
      }
      if (false) ;
      else {
        pageModule = import(
          /*@vite-ignore*/
          pageFilePath
        );
      }
    }
    if (inBrowser) {
      isInitialPageLoad = false;
    }
    return pageModule;
  }, Theme.NotFound);
}
if (inBrowser) {
  createApp().then(({ app, router, data }) => {
    router.go().then(() => {
      useUpdateHead(router.route, data.site);
      app.mount("#app");
    });
  });
}
async function render(path) {
  const { app, router } = await createApp();
  await router.go(path);
  const ctx = { content: "", vpSocialIcons: /* @__PURE__ */ new Set() };
  ctx.content = await renderToString(app, ctx);
  return ctx;
}
export {
  useRouter as a,
  createSearchTranslate as c,
  dataSymbol as d,
  escapeRegExp as e,
  inBrowser as i,
  pathToFile as p,
  render,
  useData as u
};
