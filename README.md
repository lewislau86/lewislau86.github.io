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
