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
| 第 12 章 完整 TinyLLM | [tinyllm-model.py](tinyllm-model.py) | [打开](https://lewislau86.github.io/tinyllm/tinyllm-model) |
| 第 13 章 TinyLLM 在 GPU 上完整实现 | [gpu-training.py](gpu-training.py) | [打开](https://lewislau86.github.io/tinyllm/gpu-training) |
| 第 14 章 语料与数据管线 | [data-pipeline.py](data-pipeline.py) | [打开](https://lewislau86.github.io/tinyllm/data-pipeline) |
| 第 15 章 语言模型目标函数 | [language-model-loss.py](language-model-loss.py) | [打开](https://lewislau86.github.io/tinyllm/language-model-loss) |
| 第 16 章 优化器 | [optimizers.py](optimizers.py) | [打开](https://lewislau86.github.io/tinyllm/optimizers) |
| 第 17 章 学习率策略 | [learning-rate.py](learning-rate.py) | [打开](https://lewislau86.github.io/tinyllm/learning-rate) |
| 第 18 章 正则化与泛化 | [regularization.py](regularization.py) | [打开](https://lewislau86.github.io/tinyllm/regularization) |
| 第 19 章 数值精度与混合精度 | [precision.py](precision.py) | [打开](https://lewislau86.github.io/tinyllm/precision) |
| 第 20 章 梯度稳定与累积 | [gradient-stability.py](gradient-stability.py) | [打开](https://lewislau86.github.io/tinyllm/gradient-stability) |
| 第 21 章 训练循环与检查点 | [training-loop.py](training-loop.py) | [打开](https://lewislau86.github.io/tinyllm/training-loop) |
| 第 22 章 训练诊断与评估 | [training-evaluation.py](training-evaluation.py) | [打开](https://lewislau86.github.io/tinyllm/training-evaluation) |
| 第 23 章 超参数与自动化调参 | [hyperparameter-tuning.py](hyperparameter-tuning.py) | [打开](https://lewislau86.github.io/tinyllm/hyperparameter-tuning) |
| 第 24 章 缩放定律与算力预算 | [scaling-laws.py](scaling-laws.py) | [打开](https://lewislau86.github.io/tinyllm/scaling-laws) |
| 第 25 章 大规模训练稳定性 | [large-model-stability.py](large-model-stability.py) | [打开](https://lewislau86.github.io/tinyllm/large-model-stability) |
| 第 26 章 稀疏专家（MoE） | [mixture-of-experts.py](mixture-of-experts.py) | [打开](https://lewislau86.github.io/tinyllm/mixture-of-experts) |
| 第 27 章 自回归生成 | [generation.py](generation.py) | [打开](https://lewislau86.github.io/tinyllm/generation) |
| 第 28 章 推理效率 | [inference-efficiency.py](inference-efficiency.py) | [打开](https://lewislau86.github.io/tinyllm/inference-efficiency) |
| 第 29 章 注意力内核与算子融合 | [attention-kernels.py](attention-kernels.py) | [打开](https://lewislau86.github.io/tinyllm/attention-kernels) |
| 第 30 章 量化 | [quantization.py](quantization.py) | [打开](https://lewislau86.github.io/tinyllm/quantization) |
| 第 31 章 投机解码 | [speculative-decoding.py](speculative-decoding.py) | [打开](https://lewislau86.github.io/tinyllm/speculative-decoding) |
| 第 32 章 批处理与调度 | [batching.py](batching.py) | [打开](https://lewislau86.github.io/tinyllm/batching) |
| 第 33 章 KV 显存管理：分页与前缀缓存 | [kv-memory.py](kv-memory.py) | [打开](https://lewislau86.github.io/tinyllm/kv-memory) |
| 第 34 章 推理优化：逐项对照与推理服务 | [inference-optimization.py](inference-optimization.py) | [打开](https://lewislau86.github.io/tinyllm/inference-optimization) |

## 怎么运行

安装步骤、整包下载和常见问题见 [实验环境：安装与代码下载](https://lewislau86.github.io/tinyllm/setup)。

每个文件自带全部 `import`，下载后直接 `python <文件名>` 从头跑到尾，就能复现教案里引用的所有输出。大多数章节只需要 PyTorch；第 4、10、12～30 章还需要 `tokenizers`，第 4、8、10、16 章的交互图表需要 `plotly`；第 29 章最后一节的 `torch.compile` 还需要一个 C++ 编译器，没有时那一节会跳过。

## 可选实验：`extras/`

`extras/` 下的脚本不属于任何一章，也不打包进整包下载、不生成 notebook、CI 不运行，因为它们要下载外部模型：

- `extras/qwen3-variants.py`：同一组问题分别问 Qwen3-0.6B-Base 和 Qwen3-0.6B，对比 base 模型和对话模型（[30 分钟快速体验](https://lewislau86.github.io/tinyllm/quickstart#base-and-chat)）。需要 `pip install "transformers>=4.51" "jinja2>=3.1"`，首次运行下载约 2.7GB。

## 和网站的关系

- 网站把 `docs/public/` 原样放到网站根目录，所以这里的 `first-run.py` 在网站上的下载地址是 `https://lewislau86.github.io/tinyllm/code/first-run.py`。
- 教案里的代码块不是手抄的，而是用 `# region 名字` / `# endregion 名字` 圈出的片段直接引用；同一个文件还会生成 `../notebooks/` 下的 notebook。改代码后运行 `python scripts/build-tinyllm-code.py <章节>` 重新生成 notebook，再运行 `python scripts/check-tinyllm-outputs.py` 核对。
