# TinyLLM 各章配套代码

这个目录是 [TinyLLM 教程](https://lewislau86.github.io/tinyllm/) 每一章代码的唯一来源，一章一个文件，文件名就是章节网址的最后一段。

| 章 | 文件 | 教案 |
| --- | --- | --- |
| 第 1 章 先跑通一个最小 TinyLLM | [first-run.py](first-run.py) | [打开](https://lewislau86.github.io/tinyllm/first-run) |
| 第 2 章 张量与自动求导 | [tensors-and-autograd.py](tensors-and-autograd.py) | [打开](https://lewislau86.github.io/tinyllm/tensors-and-autograd) |
| 第 3 章 架构演进 | [architecture-evolution.py](architecture-evolution.py) | [打开](https://lewislau86.github.io/tinyllm/architecture-evolution) |
| 第 4 章 文本与词元化 | [tokenization.py](tokenization.py) | [打开](https://lewislau86.github.io/tinyllm/tokenization) |
| 第 5 章 词嵌入与输出层 | [embeddings-and-output.py](embeddings-and-output.py) | [打开](https://lewislau86.github.io/tinyllm/embeddings-and-output) |
| 第 6 章 自注意力 | [self-attention.py](self-attention.py) | [打开](https://lewislau86.github.io/tinyllm/self-attention) |
| 第 7 章 位置表示 | [position-encoding.py](position-encoding.py) | [打开](https://lewislau86.github.io/tinyllm/position-encoding) |
| 第 8 章 激活函数与门控前馈层 | [activations-and-ffn.py](activations-and-ffn.py) | [打开](https://lewislau86.github.io/tinyllm/activations-and-ffn) |
| 第 9 章 Transformer Block | [transformer-block.py](transformer-block.py) | [打开](https://lewislau86.github.io/tinyllm/transformer-block) |
| 第 10 章 初始化与残差路径 | [initialization-and-residuals.py](initialization-and-residuals.py) | [打开](https://lewislau86.github.io/tinyllm/initialization-and-residuals) |
| 第 11 章 归一化 | [normalization.py](normalization.py) | [打开](https://lewislau86.github.io/tinyllm/normalization) |
| 第 15 章 优化器 | [optimizers.py](optimizers.py) | [打开](https://lewislau86.github.io/tinyllm/optimizers) |
| 第 18 章 数值精度与混合精度 | [precision.py](precision.py) | [打开](https://lewislau86.github.io/tinyllm/precision) |
| 第 25 章 推理效率（KV cache 一节） | [inference-efficiency.py](inference-efficiency.py) | [打开](https://lewislau86.github.io/tinyllm/inference-efficiency) |

## 怎么运行

安装步骤、整包下载和常见问题见 [实验环境：安装与代码下载](https://lewislau86.github.io/tinyllm/setup)。

每个文件自带全部 `import`，下载后直接 `python <文件名>` 从头跑到尾，就能复现教案里引用的所有输出。大多数章节只需要 PyTorch；第 4 章还需要 `tokenizers`，第 4、8、10、15 章的交互图表需要 `plotly`。

## 和网站的关系

- 网站把 `docs/public/` 原样放到网站根目录，所以这里的 `first-run.py` 在网站上的下载地址是 `https://lewislau86.github.io/tinyllm/code/first-run.py`。
- 教案里的代码块不是手抄的，而是用 `# region 名字` / `# endregion 名字` 圈出的片段直接引用；同一个文件还会生成 `../notebooks/` 下的 notebook。改代码后运行 `python scripts/build-tinyllm-code.py <章节>` 重新生成 notebook，再运行 `python scripts/check-tinyllm-outputs.py` 核对。
