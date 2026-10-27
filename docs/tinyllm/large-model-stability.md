---
title: "第 25 章：大规模训练稳定性"
description: "μP、DeepNorm 与残差缩放：网络变深变宽时怎样保持训练稳定。"
pageClass: tinyllm-course
---

# 第 25 章：大规模训练稳定性

[课程总览](./index.md) · [上一章](./peft-and-sparsity.md) · [下一章](./advanced-topics.md)

::: info 本章状态：规划中
正文与实验尚未完成。计划覆盖 μP、DeepNorm/残差缩放、深度与宽度扩展。下面的 DeepNorm 一节已经成文（从原归一化章节移入）。
:::

<TinyLLMMap active="large-model-stability" />

## 本章主线选择（待实验验证）

小模型继续使用 [Pre-RMSNorm 与残差投影缩放](./initialization-and-residuals.md)，记录激活 RMS、logits 和梯度范数随深度、宽度的变化。出现可复现的扩展问题时，再把 μP 或 DeepNorm 作为**整套参数化与训练配方**比较；只改一个系数、沿用原学习率，不能代表这些方法的效果。[μP 论文](https://arxiv.org/abs/2203.03466) · [DeepNorm 论文](https://arxiv.org/abs/2203.00555)

## DeepNorm：为极深网络改写残差块 {#deepnorm}

[第 4 章](./normalization.md)的 Post-Norm 把相加结果再归一化，直通路径要穿过归一化层；网络一深，训练初期的更新容易过大。DeepNet 论文提出的 DeepNorm 保留 Post-Norm 的位置，同时改两件事：**放大残差直通支、缩小子层权重的初始化**。

$$
x_{\mathrm{next}}=\mathrm{LayerNorm}(\alpha x+F(x))
$$

$\alpha>1$ 让直通路径占更大比重；配套地，子层中指定权重在标准初始化后再乘 $\beta<1$。对 **decoder-only、共 $M$ 层**的模型，论文给出

$$
\alpha=(2M)^{1/4},\qquad \beta=(8M)^{-1/4},
$$

$\beta$ 作用于前馈层权重，以及注意力的 value 投影和 output 投影；query、key 投影不在名单内。编码器或 encoder-decoder 的系数不同，不能套用这组公式。具体见 [DeepNet 论文第 4.3 节](https://arxiv.org/pdf/2203.00555)。

```python
M = 24                                   # 总层数
alpha, beta = (2 * M) ** 0.25, (8 * M) ** -0.25
norm = nn.LayerNorm(d)
y = norm(alpha * x + sublayer(x))        # 只是残差块的前向；初始化还要另做
```

**DeepNorm 是一整套方案**：只给残差乘一个任意的 $\alpha$、不改初始化，不能叫做 DeepNorm；它也不是“把 RMSNorm 换掉”就能得到的收益。论文在最高 1000 层的 Transformer 上验证了它，但 BERT、GPT、LLaMA 的原始架构都没有采用它。

<a href="/tinyllm/notebooks/normalization.ipynb" download>normalization.ipynb</a> 的 DeepNorm 单元格先比较 `alpha=1` 与演示值 `alpha=1.5` 对 LayerNorm 输入的影响，再按论文系数构造一个带因果注意力和前馈层的小 Block，检查形状和梯度。它不验证深层训练效果。

## 参考资料

- [DeepNet: Scaling Transformers to 1,000 Layers，Wang 等，2022](https://arxiv.org/abs/2203.00555)
- [Tensor Programs V：μP，Yang 等，2022](https://arxiv.org/abs/2203.03466)
