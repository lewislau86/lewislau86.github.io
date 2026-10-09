# Lewis 的知识库

使用 VitePress 构建的中文文档库，替代原有 Jane 博客。

网站：https://lewislau86.github.io/

## 本地开发

建议使用 Node.js 24。

```sh
npm ci
npm run docs:dev
```

## 构建检查

```sh
npm run docs:build
npm run docs:preview
```

## 维护内容

- 文档：`docs/**/*.md`
- 导航、侧栏和搜索：`docs/.vitepress/config.mts`
- 主题样式：`docs/.vitepress/theme/style.css`
- 静态资源：`docs/public/`

新增文档后，在配置中加入侧栏链接。详细说明见 `docs/guide/writing.md`。

## 部署

GitHub Pages 的部署来源设置为 **GitHub Actions**。推送到 `master` 后，
`.github/workflows/deploy.yml` 自动安装依赖、构建并部署 `docs/.vitepress/dist`。

原 Jane 示例站点保留在 Git 历史中（迁移前提交：`4d739be`）。

## 依赖说明

VitePress 固定使用稳定版 1.6.4；通过 npm overrides 将 Vite 固定为 6.4.4，
避开旧版开发服务器的已知漏洞。升级 VitePress 后应重新评估此覆盖配置。

## 同步 TinyLLM 文档集

TinyLLM 位于网站 `/tinyllm/`，按照原仓库 `SUMMARY.md` 导入 26 个页面
（课程总览 + 25 章）和文档中引用的 3 个 notebook。导入不会修改源仓库。

```sh
python3 scripts/import-tinyllm.py /Users/lewislau/MyResearch/TinyLLM
npm run docs:build
```

导入会更新章节、侧栏与下载文件；`scripts/tinyllm-source.json` 记录源提交和文件哈希。
源内容保留原样，仅适配 README 链接、章节锚点、notebook 下载及 GitBook 导出的强调/行内公式转义。
源仓库更新后需重新运行导入并提交本站；当前不是跨仓库自动同步。
TinyLLM 页底的编辑入口指向源仓库，避免下次同步覆盖对本站副本的手动修改。
