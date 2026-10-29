---
title: "实验环境：安装与代码下载"
description: "TinyLLM 教程的实验环境怎样搭：安装 Python 和 PyTorch，下载全部章节代码与 notebook，数据从哪里来，以及常见问题。"
pageClass: tinyllm-course
---

# 实验环境：安装与代码下载

[课程总览](./index.md) · [第 1 章](./first-run.md)

开始第 1 章之前，先把实验环境准备好。整个课程**只需要 CPU**，不需要显卡；每章的脚本在普通笔记本上最长约两分半。按下面四步做一遍，大约十分钟。

::: tip 只想先看看
不想在本机安装也可以：每章开头都有“在线查看”（站内只读预览，带运行结果）和“在 Colab 中直接运行”两个链接，Colab 里自带 PyTorch，点开就能跑。
:::

## 1. 准备 Python

需要 **Python 3.10 或更高版本**。在终端里检查一下：

```sh
python --version
```

没有的话，到 [python.org](https://www.python.org/downloads/) 下载安装；Windows 安装时勾选 “Add python.exe to PATH”。

接着为这门课建一个单独的虚拟环境，避免和电脑上其他项目的包互相影响：

::: code-group

```powershell [Windows（PowerShell）]
mkdir tinyllm; cd tinyllm
python -m venv .venv
.venv\Scripts\Activate.ps1
```

```sh [macOS / Linux]
mkdir tinyllm && cd tinyllm
python3 -m venv .venv
source .venv/bin/activate
```

:::

激活后，命令行前面会出现 `(.venv)`。以后每次打开新终端做实验，都先进入这个目录再激活一次。

## 2. 安装 PyTorch

PyTorch 是课程唯一必需的库。只用 CPU 时，安装命令是：

::: code-group

```sh [Windows / Linux]
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```sh [macOS]
python -m pip install --upgrade pip
python -m pip install torch
```

:::

Windows 和 Linux 上加 `--index-url` 是为了只下载 CPU 版，体积小得多；有 NVIDIA 显卡、想用 GPU 的话，到 [PyTorch 官网](https://pytorch.org/get-started/locally/)按自己的系统和 CUDA 版本生成命令。课程里的模型都很小，GPU 不是必需的。

## 3. 下载代码，安装其余依赖

每章的代码都是一个能独立运行的 Python 文件，另外每章还有一个由同一个文件生成、保存了运行结果的 notebook。有三种拿法，任选一种：

| 方式 | 适合 | 怎么做 |
| --- | --- | --- |
| **整包下载**（推荐） | 想一次拿全 | 下载 <a href="/tinyllm/tinyllm-code.zip" download>tinyllm-code.zip</a>，解压到上面建的 `tinyllm` 目录 |
| 单章下载 | 只做某一章 | 每章开头“实践方式”里的 `.py` 下载链接 |
| 用 git 只取代码目录 | 想跟着仓库更新 | 见下面的命令 |

整包解压后的结构：

```text
tinyllm-code/
├── README.md            每章对应哪个文件
├── requirements.txt     依赖清单
├── code/                每章一个 .py，例如 first-run.py
├── notebooks/           每章一个 .ipynb，已保存运行结果
└── data/                统一唐诗语料 tang-poems.jsonl 及说明
```

用 git 的话，只把代码所在的目录取下来，不用下载整个网站：

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/lewislau86/lewislau86.github.io.git
cd lewislau86.github.io
git sparse-checkout set docs/public/tinyllm
```

代码在 `docs/public/tinyllm/code/`，notebook 在 `docs/public/tinyllm/notebooks/`，语料在 `docs/public/tinyllm/data/`。网站会把 `docs/public/` 原样放到根目录，所以仓库里的 `docs/public/tinyllm/code/first-run.py`，在网站上的地址就是 `/tinyllm/code/first-run.py`；在 GitHub 上浏览可以直接打开 [docs/public/tinyllm/code](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/tinyllm/code)。

然后安装其余依赖（整包里已经带了 `requirements.txt`，也可以<a href="/tinyllm/requirements.txt" download>单独下载</a>）：

```sh
python -m pip install -r requirements.txt
```

| 包 | 用在哪里 | 不装会怎样 |
| --- | --- | --- |
| `torch` | 所有章节 | 无法运行 |
| `tokenizers` | 第 4 章：训练字节级 BPE | 第 4 章无法运行 |
| `plotly` | 第 4、8、10、15 章的交互图表 | 这几章画图那一步报错 |
| `jupyterlab` | 在本地打开 notebook | 不影响 `.py` 脚本，只是不能用 notebook |

本站最近一次完整运行用的是 Python 3.10.12、torch 2.14.1、tokenizers 0.23.3、plotly 7.1.0。版本更新一些通常没问题；个别随机结果的末几位可能和正文不同。

## 4. 验证：跑一下第 1 章

```sh
cd tinyllm-code/code
python first-run.py
```

开头几行应该是这样（PyTorch 版本号以你装的为准）：

```text
PyTorch 2.14.1+cpu
诗的数量： 39   训练字符数： 1235   验证字符数： 196
词表大小： 556
“床前明月光” → [169, 65, 237, 253, 45]
```

接着会训练 600 步、打印损失，最后写几首“唐诗”，整个过程约半分钟。看到这些，环境就装好了。

想用 notebook 的话，在 `tinyllm-code` 目录里运行 `jupyter lab`，在浏览器里打开 `notebooks/first-run.ipynb`，从上到下逐格运行即可。

## 数据从哪里来

本课所有实验用同一份语料：**统一唐诗语料** `tang-poems.jsonl`，共 17,439 首五言绝句和五言律诗、约 75 万字，已经处理好放在网站和整包下载里，不需要自己清洗源数据。

| 项目 | 内容 |
| --- | --- |
| 下载 | 整包里的 `data/tang-poems.jsonl`，或<a href="/tinyllm/data/tang-poems.jsonl" download>单独下载</a>（约 4.2 MB） |
| 校验 | SHA-256 `764f0614663c20e95927c6ecb63e454629f6cb0efefe9ac84454e256f7173fb1` |
| 顺序 | 前 39 首是第 1 章的诗，接着 99 首出自《唐诗三百首》，其余来自《全唐诗》并按固定种子打乱；“前 N 首”永远是同一个子集 |
| 划分 | 每首诗都标了 `train`、`val` 或 `test`（约 90% / 5% / 5%，按正文哈希固定），前 39 首都在训练集 |
| 来源与许可 | [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)（MIT 许可证）固定版本，繁体转简体；处理方法见[语料说明](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/data/README.md)和 `scripts/prepare-tinyllm-corpus.py` |

需要语料的章节，脚本开头有一个 `load_poems(n)`：先找环境变量 `TINYLLM_DATA` 指向的文件、当前目录、整包解压后的 `../data/`，都没有就从网站下载一份并核对校验值。所以按上面的方式整包下载后，什么都不用配置。

各章用到的数据：

| 章节 | 数据 |
| --- | --- |
| 第 1、6、7、9 章 | 语料的前 39 首，直接写在脚本里（第 1 章的流水线不依赖下载）；第 7 章另有脚本现场生成的随机符号序列 |
| 第 2～8 章的小例子 | “我 在 学习”等，写在脚本里 |
| 第 4 章 | 训练 BPE 的几段示例文本，写在脚本里 |
| 第 12 章起 | 统一语料的更大子集，按 `split` 字段区分训练集和验证集 |
| 可选路线：GPU 完整训练 | 唐宋诗大语料（约 29.7 万首、1,726 万字、90 MB），在本机用 `scripts/prepare-tinyllm-large-corpus.py` 生成并自动核对校验值，见[该页](./gpu-training.md#corpora) |

为什么前几章只用 39 首？那几章的实验比的是结构（有没有注意力、位置、残差），每个模型只训练几百步。在本站构建用的 2 核 CPU 上，把语料从 39 首换成 600 首，同样 600 步的训练时间只从约 23 秒增加到约 40 秒（主要是词表从 556 个字变成约 2,500 个字）；但几百步对 600 首诗来说太少，模型还只学到常用字的频率，结构之间的差别反而看不出来。语料一大，要多训练很多步才能看出“学会了”，这正是第 12 章开始的完整训练要做的事。

有几章运行完会在当前目录写出一两个 `.json` 文件（例如 `first_run_log.json`），那是网站画图和动画用的记录，可以直接删掉。

## 常见问题

- **pip 下载很慢。** 国内网络可以给 pip 加镜像，例如 `python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`。PyTorch 的 CPU 版本也可以直接 `pip install torch` 从镜像装，但在 Linux 上会顺带下载 CUDA 相关的包，体积大很多。
- **Windows 上 `Activate.ps1` 无法运行。** PowerShell 默认禁止脚本，先执行一次 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，或者改用 `cmd` 里的 `.venv\Scripts\activate.bat`。
- **中文输出是乱码。** 旧版 Windows 控制台的问题，用 Windows Terminal，或者运行前执行 `set PYTHONUTF8=1`（PowerShell 里是 `$env:PYTHONUTF8=1`）。
- **运行带 Plotly 图表的章节时弹出了浏览器。** 这是 Plotly 在命令行里显示图表的方式，看完关掉即可；在 notebook 里图表会直接显示在单元格下面。
- **我的输出和正文差了最后几位。** 不同的 CPU、PyTorch 版本在浮点计算上可能有细微差别，固定随机种子也不能完全消除（[PyTorch 可复现性说明](https://docs.pytorch.org/docs/2.14/notes/randomness.html)）。趋势和结论应当一致；差得很多的话，先核对 PyTorch 版本。

环境准备好了，从[第 1 章：先跑通一个最小 TinyLLM](./first-run.md) 开始。
