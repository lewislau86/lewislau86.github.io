# AGENTS.md

本仓库是 VitePress 文档站（https://lewislau86.github.io/），包含 TinyLLM、mini-redis、Burn 三个系列教程。
任何人或 AI 助手修改本仓库前，先读这份文件，再读完整规范 `docs/guide/course-conventions.md`。

## 必须遵守的约束

1. **网站是唯一来源。** 教程正文直接改 `docs/<课程>/`，不要从其他仓库导入或覆盖。
2. **文件名用主题名，不用编号。** 章节顺序由 `docs/.vitepress/<课程>-sidebar.json` 决定；改名时在原位置留跳转页。
3. **章节结构统一。** frontmatter、顶部导航、`::: tip 本章学习目标`、课程地图组件、正文、`::: warning 常见误区`、本章结论、检查理解（折叠答案）、参考资料、下一章链接。模板见规范第 4 节。
4. **配图由脚本生成，不手改 SVG。** TinyLLM：`scripts/generate-tinyllm-figures.py`（实验数据先跑 `scripts/tinyllm-figure-data.py`）；mini-redis：`scripts/generate-mini-redis-figures.py`；Burn：`scripts/generate-burn-math-figures.py`。图中数字必须来自真实运行或官方资料。
5. **教程代码必须能独立运行，文章只引用、不手抄。**（TinyLLM 已在第 1 章试点，其余章节逐步迁移）
   - 每章一个完整脚本：`docs/public/tinyllm/code/<章节文件名>.py`，自带全部 `import`，`python <文件>` 从头跑到尾能复现正文里的所有输出。
   - 正文中的代码块用 VitePress 片段导入：在脚本里用 `# region 名字` / `# endregion 名字` 圈出片段，Markdown 里写 `<<< @/public/tinyllm/code/<文件>.py#名字`。不要在 Markdown 里另抄一份可运行代码。
   - 只为说明某个 API 参数、本身不打算运行的几行示意代码，可以留在 Markdown 里，但要在旁边写明“示意”并链接完整脚本。
   - notebook 由脚本生成：`python scripts/build-tinyllm-code.py [章节]` 会运行脚本、生成 `docs/public/tinyllm/notebooks/<章节>.ipynb` 并保存输出，同时生成站内只读预览页 `docs/tinyllm/notebooks/<章节>.md`（网址 `/tinyllm/notebooks/<章节>`，带 Colab、下载、GitHub 链接）。不要手改 notebook 和预览页；只想刷新预览页用 `--pages`。
   - 正文里提到 notebook 时链接到预览页 `[x.ipynb](/tinyllm/notebooks/x)`，不要直接链接 `.ipynb` 文件（那样浏览器只会下载）。
   - 改了任何 `code/*.py` 后运行 `python scripts/build-tinyllm-code.py --check`，确保所有脚本都能跑通；正文引用的输出要和实际运行结果一致。
6. **折叠答案写成多行。** `<details><summary>参考答案</summary>` 后、`</details>` 前各空一行，否则公式和行内代码不渲染，`<eos>` 这类尖括号还会让构建失败。
7. **加粗以中文标点结尾、后面紧跟文字时用 `<strong>`**，`**…。**后文` 不会被识别。
8. **提交前构建。** `npm run docs:build` 必须通过且没有死链。

## 常用命令

```sh
npm ci && npm run docs:dev                     # 本地预览
npm run docs:build                             # 构建（检查死链）
python scripts/build-tinyllm-code.py --check   # 运行所有 TinyLLM 章节脚本
python scripts/build-tinyllm-code.py           # 运行脚本并重新生成 notebook
python scripts/tinyllm-figure-data.py          # 重跑配图用的实验数据（需要 torch）
python scripts/generate-tinyllm-figures.py     # 重新生成 TinyLLM 配图
python scripts/generate-mini-redis-figures.py  # 重新生成 mini-redis 配图
python scripts/package-mini-redis.py           # 重新打包 mini-redis 学习包
```
