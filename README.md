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
learn-cuda 固定版本的 15 个主题已分别在第 5、12、13、15 章讲解；GPU 实践主线使用 NVIDIA/cuda-rust，第 6 章展开 SIMT、Tile、三个小型 Rust GPU 程序与 CubeCL 的关系，第 17～18 章记录调用链与验收步骤。源码基线集中在 `references.md`，讲解覆盖不等于设备验证。

`docs/public/burn/learn-cuda-reference.rs` 提供 Rust 标准库数学参考，八组检查已通过。`docs/public/burn/nvidia-gpu-labs/` 提供固定 NVIDIA 提交与 Cargo.lock 的 Tile 加法、Softmax、小矩阵乘法；本机未编译或运行 CUDA。`learn-cuda-coverage.json` 记录源码、正文与验证状态，15 个主题的完整 Rust GPU 移植和硬件性能复现仍未完成。
`docs/public/burn/first-inference/` 提供固定 Burn 0.22.1 的 CPU 学习包。第 16 章用 `comparison.rs` 与 `pytorch_compare.py` 对照两套框架；第 11、14 章用 `regression_train.rs` / `regression_verify.rs` 验证训练、保存与新进程加载。Python 环境与 Cargo 依赖分别管理。

数学预备篇通过 `/burn/math-foundations` 访问，公式使用 VitePress 的 MathJax；图解保存在 `docs/public/burn/`。六张数学图可用 `python scripts/generate-burn-math-figures.py` 重新生成（需要 matplotlib、NumPy 和中文字体；Windows 自动选择微软雅黑，其他平台可安装 Noto Sans CJK SC）。

修改正文后运行 `npm run docs:build`；若修改学习包，重新验证程序并更新 `docs/public/burn/first-inference.zip`。
运行包内代码时应在解压目录构建，或为 Cargo 指定站点目录之外的 `CARGO_TARGET_DIR`，避免把编译产物作为静态资源发布。

## 编写 TinyLLM 教程

TinyLLM 位于 `docs/tinyllm/`，由本站直接维护（不再从 tinyllm 仓库导入），通过 `/tinyllm/` 访问。
课程分五部分、27 章：先用第 1 章跑通一个字符级小模型，再依次讲可训练的网络、构造语言模型、数据与训练、生成与扩展。
文件名使用主题名（如 `normalization.md`），章节顺序由 `docs/.vitepress/tinyllm-sidebar.json` 决定；
旧的 `chapterN_*.md` 地址保留为跳转页。

- 每章 notebook：`docs/public/tinyllm/notebooks/<文件名>.ipynb`（第 1 章另附 `first-run.py`）。
- 配图：`python scripts/generate-tinyllm-figures.py` 重新生成 `docs/public/tinyllm/figures/` 下的 SVG
  （需要 matplotlib、NumPy 和中文字体）。第 1 章损失曲线读取 `scripts/data/tinyllm-first-run-log.json`，
  该文件由运行 `first-run.py` 得到的 `first_run_log.json` 复制而来。
- 全书架构图：`docs/.vitepress/theme/components/TinyLLMMap.vue`，章节中写 `<TinyLLMMap active="文件名" />`。
  章节成文后，同步更新组件中的 `done` 列表、侧栏和总览页。

三个课程共用的写作与目录规范见 `docs/guide/course-conventions.md`。

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
