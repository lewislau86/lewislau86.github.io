# 课程写作规范

本站的三个系列教程（TinyLLM、mini-redis、Burn）按同一套规范组织。新增章节、调整顺序或补配图时，先对照这一页。

## 1. 网站是唯一来源

所有课程正文都直接在本仓库的 `docs/<课程>/` 里编写和修改，不再从其他仓库导入。配套代码（notebook、Rust 学习包、源码快照）作为下载文件放在 `docs/public/<课程>/`。

这样做的好处是：章节重排、配图、交叉链接都在一处完成，页底的“在 GitHub 上编辑此页”也始终指向真正的源文件。

| 课程 | 正文 | 下载与配图 | 侧栏 | 状态 |
| --- | --- | --- | --- | --- |
| TinyLLM | `docs/tinyllm/` | `docs/public/tinyllm/{notebooks,figures}/` | `tinyllm-sidebar.json` | 已按本规范迁移 |
| Burn | `docs/burn/` | `docs/public/burn/` | `burn-sidebar.json` | 已符合 |
| mini-redis | `docs/mini-redis/` | `docs/public/mini-redis/{source,mini-redis-study.zip}` | `mini-redis-sidebar.json`、`mini-redis-source-sidebar.json` | 已按本规范迁移 |

## 2. 文件名与 URL

- **文件名用主题，不用编号。** 例如 `tinyllm/normalization.md`，而不是 `chapter4_normalization.md`。章节号只出现在标题和侧栏里，调整顺序时 URL 不变。
- 全部小写，单词之间用连字符：`tensors-and-autograd.md`。
- 每个课程目录有一个 `index.md` 作为课程总览。

## 3. 侧栏决定顺序

章节顺序由 `docs/.vitepress/<课程>-sidebar.json` 决定，页底的“上一篇 / 下一篇”也按侧栏顺序生成。

- 按“部分”分组，组名写成 `第一部分 · 先跑起来` 的形式。
- 条目文字写成 `第 N 章 · 标题`。
- 尚未成文的章节集中放进最后一个折叠分组 `规划中（尚未成文）`，避免读者顺着“下一篇”掉进空页面。
- 章节成文后，把它从规划分组移到对应部分；TinyLLM 还要同步更新 `TinyLLMMap.vue` 里的 `done` 列表和总览页的“已成文的章节”表。

## 4. 章节模板

### 已成文的章节

```md
---
title: "第 N 章：标题"
description: "一句话说明本章回答什么问题。"
pageClass: tinyllm-course        # Burn 用 burn-course，mini-redis 用 mini-redis-course
---

# 第 N 章：标题

[课程总览](./index.md) · [上一章](./prev.md) · [下一章](./next.md)

::: tip 本章学习目标
读完后能做到的 2～3 件具体的事。

**前置：** 需要先读哪几章，链接到具体章节。

**实践方式：** 配套 notebook 或学习包的下载链接，以及运行环境。
:::

开场：从上一章留下的问题或一个具体现象出发，说明本章要解决什么。

<TinyLLMMap active="本章文件名" />   <!-- 仅 TinyLLM：高亮本章负责的零件 -->

## 1. 用一个具体例子展开……
## 2. ……
## 动手实验

## 在真实模型里

（TinyLLM 专用，由 scripts/tinyllm-real-model-refs.py 生成：本章零件对应的 Hugging Face transformers 源码，固定版本、精确到行）

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

::: warning 常见误区
:::

## 检查理解

1. 问题

   <details><summary>参考答案</summary>

   答案

   </details>

## 参考资料

下一章预告与链接。
```

要点：

- **先例子，后结论。** “本章结论 / 主线选择”放在章末，等读者理解了概念再给结论，不在开头抛出尚未解释的术语。
- **每章只引入当前需要的概念。** 用到后面章节的内容时，给一句直觉解释并链接过去，不在本章展开。需要后续知识才能理解的方法，挪到那一章去讲。
- **检查理解要带答案**，用 `<details>` 折叠。`<summary>` 之后和 `</details>` 之前各留一个空行，答案里的公式、行内代码和 `<eos>` 这类尖括号文本才会按 Markdown 处理；写在同一行会被当成原始 HTML，尖括号还会让构建报错。

### 规划中的章节

```md
---
title: "第 N 章：标题"
description: "……"
pageClass: tinyllm-course
---

# 第 N 章：标题

[课程总览](./index.md) · [上一章](./prev.md) · [下一章](./next.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。计划覆盖……
:::

## 本章主线选择（待实验验证）
```

从其他章节移入、已经写好的小节，可以先放在规划章节里，并在提示框中说明。

## 5. 写作风格

- **叙事式推进。** 一章围绕一条主线（一个小例子、一次计算）往前走，而不是把多个方法平行罗列成手册。理想参照：TinyLLM 第 2 章、Burn 第 10 章。
- **先猜后验。** 给出形状或数值时，先让读者预测，再用代码或手算核对。
- **少用否定句堆叠。** 正文说清“它是什么、怎么用”；“不能 / 不等于 / 不是”这类边界说明，保留最关键的一两条，其余集中到章末的 `::: warning 常见误区`。
- **加粗只用于少量关键句。** 用 `**…**`；当加粗内容以标点结尾、后面紧跟文字时（如 `**结论。**后文`），Markdown 无法识别，改用 `<strong>…</strong>`。
- 中文与数字、英文之间留空格：`第 4 章`、`RMSNorm 的输出`。
- 引用论文或文档时直接链接到原始来源；论文在特定实验中的结论，写明适用范围。

## 6. 配图

每个关键概念至少配一张图。配图分两类：

| 类型 | 做法 | 例子 |
| --- | --- | --- |
| 示意图（数据流、计算图、张量形状） | 在生成脚本中手写 SVG，文字保留为可选中文本 | `compute-graph.svg`、`pre-post-norm.svg` |
| 数据图（曲线、柱状图） | matplotlib 生成 SVG，文字转为路径，避免字体缺失 | `norm-motivation.svg`、`first-run-loss.svg` |

- 图由脚本生成，不手工编辑 SVG：TinyLLM 用 `scripts/generate-tinyllm-figures.py`，mini-redis 用 `scripts/generate-mini-redis-figures.py`，Burn 用 `scripts/generate-burn-math-figures.py`。改图就改脚本，再重新运行。
- 数据图的数据来自真实运行。需要训练记录的图，把记录保存在 `scripts/data/`，脚本只负责读取和绘制。
- 图片的替代文本写成一句完整描述，说明图中“看到了什么结论”，而不只是图名。
- 图下紧跟一段“怎么读这张图”，指出读者应该注意的地方。
- 配色：蓝 `#2563eb`、青 `#0f766e`、橙 `#b45309`、红 `#b91c1c`、灰 `#64748b`，浅灰底 `#f8fafc`。
- notebook 内的交互图表统一用 Plotly。

TinyLLM 与 mini-redis 各有一个全书架构图 Vue 组件：`TinyLLMMap.vue`、`MiniRedisMap.vue`（位于 `docs/.vitepress/theme/components/`）。在章节开头写 `<TinyLLMMap active="normalization" />` 或 `<MiniRedisMap active="tokio-server" />`，就会高亮本章负责的部件；架构或章节对应关系变化时只改组件文件。

能用图表达的结构（调用链、数据流、时间线、内存布局）不要再写成字符画；字节序列、程序输出、日志这类“原样文本”仍用代码块。

### 动画与交互

只有两类内容值得做成动画：**按时间展开的过程**（逐字生成、注意力的四个步骤、前向与反向传播、优化器轨迹、KV cache 的逐步增长）和**调一个参数看结果怎么变**（RoPE 的位置滑块）。讲结构的图（形状、架构）保持静态。

| 章 | 组件 | 数据 |
| --- | --- | --- |
| 第 1 章 | `<NextTokenPlayer stage="before" />`、`stage="after"` | `tinyllm-first-run-generation.json`（first-run.py） |
| 第 2 章 | `<BackpropFlow />` | `tinyllm-autograd-chain.json`（tensors-and-autograd.py） |
| 第 6 章 | `<AttentionStepper />` | `tinyllm-attention-steps.json`（self-attention.py） |
| 第 7 章 | `<RopeSlider />` | `tinyllm-rope-demo.json`（position-encoding.py） |
| 第 9 章 | `<ResidualStreamLens />` | `tinyllm-block-depth.json`（transformer-block.py） |
| 第 16 章 | `<OptimizerRace />` | `tinyllm-optimizer-paths.json`（tinyllm-figure-data.py） |
| 第 26 章 | `<KVCacheRace />` | `tinyllm-kv-cache-counts.json`（inference-efficiency.py） |

做法约定：

- 组件在 `docs/.vitepress/theme/components/`，在 `theme/index.ts` 注册；播放逻辑统一用 `usePlayer.ts`（帧号、播放 / 暂停、单步、从头、拖动），控制条统一用 `PlayerControls.vue`，外框用全局样式 `.anim-card`，说明文字用 `.anim-caption`。
- 数据从 `scripts/data/*.json` 导入，由章节脚本真实运行导出，并在 `scripts/build-tinyllm-code.py` 的 `ARTIFACTS` 里登记；组件不手写数值。脚本导出数据时不能改变其他输出：需要随机数就先保存状态、用完恢复，并核对导出的结果和正文打印的一致。
- 单步类动画默认停在最后一帧，读者先看到完整结果（等同于原来的静态图），点“播放”从头重演；不自动播放；动效遵守 `prefers-reduced-motion`；颜色用 VitePress 主题变量，深色模式下也要检查。
- 被动画替换的静态图继续由脚本生成，并在动画图注里给出“打开静态图”链接，供打印或不便播放时使用。
- 改完后构建站点，用浏览器截取初始帧和中间帧检查，并确认控制台没有报错。

## 7. 配套代码

**原则：代码只有一个来源，文章只引用、不手抄。** 正文里手抄的代码会缺 `import`、依赖前文变量，改了 notebook 也没人会发现两边对不上。

- TinyLLM：每章一个能独立运行的完整脚本，放在 `docs/public/tinyllm/code/<文件名>.py`，与正文同名，自带全部 `import`，`python <文件>` 从头跑到尾能复现正文中的所有输出。（已成文的 9 章都已按此迁移。）
- 正文中的代码块用 VitePress 片段导入。在脚本里圈出片段：

  ```python
  # region model
  class TinyLLM(nn.Module):
      ...
  # endregion model
  ```

  Markdown 里写一行 `<<< @/public/tinyllm/code/first-run.py#model`，构建时会把这段代码原样嵌入页面（标记行本身不会显示）。每章第一个代码块之前放一个 `::: info` 框，说明代码出处并给出完整脚本的下载和 GitHub 链接。
- 只为说明某个 API 参数、本身不打算运行的几行示意代码，可以留在 Markdown 里，旁边写明“示意”并链接完整脚本。
- notebook 由脚本生成，不要手改：脚本里 `# %%` 开始一个代码格，`# %% [markdown]` 开始一个说明格。运行 `python scripts/build-tinyllm-code.py <章节>` 会执行脚本、生成 `docs/public/tinyllm/notebooks/<文件名>.ipynb` 并保存输出；`--check` 只运行、不写文件。同时会生成站内只读预览页 `docs/tinyllm/notebooks/<文件名>.md`（网址 `/tinyllm/notebooks/<文件名>`），显示全部代码和保存的输出，并提供“在 Colab 中运行”“下载 .ipynb / .py”“在 GitHub 上查看”链接；正文提到 notebook 时链接到这个预览页，而不是 `.ipynb` 文件本身。只刷新预览页用 `--pages`。notebook 中回到正文的链接使用完整网址 `https://lewislau86.github.io/tinyllm/<文件名>`。
- Burn、mini-redis：学习包放在各自的 `docs/public/<课程>/` 下，并提供 zip 下载。mini-redis 的 zip 由 `scripts/package-mini-redis.py` 从源码快照生成，只含代码与实验，教程正文以网站为准。
- 正文中引用的输出（损失、生成样例、打印结果）必须来自实际运行，并写明运行环境。

### 对照实验的写法

- **控制变量。** 被比较的模型按同一组预先生成的 batch 训练：用单独的 `torch.Generator` 生成 batch 计划，第几步就用第几个 batch；随机种子只决定初始参数，避免不同结构初始化时消耗的随机数改变 batch 顺序。
- **多种子。** 用来下结论的对比至少跑 3 个种子，报告平均和范围；受运行时间限制只能跑一个种子时，正文写明“单个种子”，不解读很小的差别。
- **标清指标口径。** 训练集损失、验证集损失（训练时没用过的数据）、合成任务测试集（新生成的数据）分开写；在训练语料上的评估只能说明“背没背下来”或某个因素（如长度）的影响，不当作泛化结果。
- **写明实验边界。** 例如“用 PyTorch 默认初始化，不是最终配方”“最多测到 8 层、100 步”。结论只说到实验条件支持的程度；同时改了两样东西时，要么补单独改一样的对照组，要么写明只验证了组合。
- **核对。** 正文 ```text 块里引用的输出由 `scripts/check-tinyllm-outputs.py` 与 notebook 逐行核对；不是程序输出的示意块，在前一行写 `<!-- output-check: skip -->`。

## 8. 调整顺序与旧地址跳转

文件名不含编号，所以调整顺序通常只需要：

1. 修改侧栏 JSON 中的顺序与“第 N 章”文字；
2. 修改各章标题、frontmatter 的 `title` 和顶部导航中的上一章 / 下一章；
3. 全文搜索“第 N 章”的文字引用并更新。

如果确实要改文件名，在原位置保留一个跳转页，避免外部链接失效：

```md
---
title: 页面已移动
search: false
sidebar: false
outline: false
head:
  - - meta
    - http-equiv: refresh
      content: "0; url=/tinyllm/new-name.html"
---

# 页面已移动

请继续阅读[第 N 章：标题](./new-name.md)。
```

TinyLLM 的 `chapterN_*.md`、mini-redis 的 `NN-*.md`、Burn 的旧编号页都是这样的跳转页。

## 9. 发布前检查

```sh
python scripts/generate-tinyllm-figures.py   # 改了配图时
npm run docs:build                           # 构建会报告死链
npm run docs:preview
```

在预览中至少检查：新章节的侧栏位置、顶部导航、配图在浅色和深色模式下都清晰、notebook 能下载。
