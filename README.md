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

## 编写 Burn 教程

《深入理解 Burn 深度学习框架》位于 `docs/burn/`，由本站直接维护，通过 `/burn/` 访问。全书分七部分、18 章，从环境与数学、张量与 Rust、GPU/CUDA，逐步进入 Burn 模型、后端、训练、执行性能、部署扩展和源码实验。
`docs/.vitepress/burn-sidebar.json` 管理统一目录。正文路由使用主题名称，章节顺序由目录组织；旧地址直接跳转到对应正文。文章统一使用章节标题、学习目标、实践方式、描述性小标题与章间导航。
第 5 章将 GPU 基础与 learn-cuda 阅读练习合并，第 6 章介绍 Rust GPU 与 CubeCL。第 18 章记录实验验证范围和后续计划，资料基线集中在 `references.md`。
`docs/public/burn/first-inference/` 提供固定 Burn 0.22.1 的 CPU 学习包。第 16 章用 `comparison.rs` 与 `pytorch_compare.py` 对照两套框架；第 11、14 章用 `regression_train.rs` / `regression_verify.rs` 验证训练、保存与新进程加载。Python 环境与 Cargo 依赖分别管理。

修改正文后运行 `npm run docs:build`；若修改学习包，重新验证程序并更新 `docs/public/burn/first-inference.zip`。
运行包内代码时应在解压目录构建，或为 Cargo 指定站点目录之外的 `CARGO_TARGET_DIR`，避免把编译产物作为静态资源发布。

## 同步 TinyLLM 文档集

TinyLLM 位于网站 `/tinyllm/`，按照原仓库 `SUMMARY.md` 导入 27 个页面
（课程总览 + 26 章）和文档中引用的 6 个 notebook。导入按目录识别连续的章节编号，新增章节会进入侧栏，不修改源仓库。

```sh
python3 scripts/import-tinyllm.py /Users/lewislau/MyResearch/TinyLLM
npm run docs:build
```

导入会更新章节、侧栏与下载文件；`scripts/tinyllm-source.json` 记录源提交和文件哈希。
源内容保留原样，仅适配 README 链接、章节锚点、notebook 下载及 GitBook 导出的强调/行内公式转义。
源总览尚未登记已完成的第 13 章时，导入会为网站总览补上优化器教案及 notebook 入口。
源仓库更新后需重新运行导入并提交本站；当前不是跨仓库自动同步。
TinyLLM 页底的编辑入口指向源仓库，避免下次同步覆盖对本站副本的手动修改。

## 同步 mini-redis 教程

网站 `/mini-redis/` 发布本地 `mini-redis/docs` 的当前版本（整体架构导读、13 章正文、28 篇逐文件分析、Rust 源码阅读说明、总览、实验说明和验证记录）。

```sh
python3 scripts/import-mini-redis.py /Users/lewislau/MyResearch/mini-redis/docs
npm run docs:build
```

导入不修改源仓库。`scripts/mini-redis-source.json` 记录源码基线与发布文件哈希，
其中教程可能是源仓库尚未提交的本地内容。保留原验证记录的时间和限制，本次发布检查不等于重新执行 Rust 实验。
源码链接指向本站仓库 `docs/public/mini-redis/source/` 的文件；完整学习包包含源码、锁文件、LICENSE 和 docs/labs，保留实验所需的相对路径依赖。
修改原始 docs 后，重新导入、构建并提交本站即可更新；当前不跨仓库自动同步。
