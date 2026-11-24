---
title: "第 42 章：DPO：直接偏好优化"
description: "把 RLHF 变简单：DPO 不训练奖励模型、不采样，直接用成对的偏好训练策略。和第 41 章同一份偏好数据，比较两个 β，看隐含奖励的准确率，以及“选中、落选的概率一起下降”这个常见的失败模式和它的补救。"
pageClass: tinyllm-course
---

# 第 42 章：DPO：直接偏好优化

[课程总览](./index.md) · [上一章](./rlhf.md) · [下一章](./grpo.md)

::: tip 本章学习目标
能从“奖励模型 + KL 约束”的目标出发，说清 DPO 为什么可以跳过奖励模型和 PPO；能写出 DPO 的损失，并说清参考模型和 β 各起什么作用；能在和第 41 章同一份偏好数据上训练 DPO，和 PPO 比较效果、KL 和代价；能解释为什么 DPO 训练时“选中”回答的概率也会下降，以及加一项负对数似然为什么能缓解；知道 IPO、KTO、SimPO 这些变体各改了什么。

**前置：** [第 41 章](./rlhf.md)的偏好数据、Bradley–Terry 损失、KL 约束与评审，[第 38 章](./instruction-finetuning.md)的 SFT。

**实践方式：** [preference-alignment.ipynb](/tinyllm/notebooks/preference-alignment)（也可以直接运行 <a href="/tinyllm/code/preference-alignment.py" download>preference-alignment.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="preference-alignment" />

## 问题：RLHF 太重了

第 41 章的 RLHF 要先训练奖励模型，再同时维护策略、参考、奖励、价值四个模型，每一步在线采样、打分、算优势，对 β 和学习率都很敏感。能不能直接拿偏好对训练策略，像 SFT 一样简单？

[DPO](https://arxiv.org/abs/2305.18290)（direct preference optimization）的回答是可以。RLHF 的目标是“奖励尽量高，同时和参考模型的 KL 不要太大”：

$$
\max_\pi\ \mathbb{E}_{y\sim\pi}\big[r(x,y)\big] - \beta\,\mathrm{KL}\big(\pi(\cdot|x)\,\|\,\pi_\text{ref}(\cdot|x)\big)
$$

这个问题有闭式解：$\pi^*(y|x) \propto \pi_\text{ref}(y|x)\exp(r(x,y)/\beta)$。反过来写，奖励可以用策略表示：$r(x,y) = \beta\log\frac{\pi^*(y|x)}{\pi_\text{ref}(y|x)} + \text{常数}$。把它代进第 41 章奖励模型的 Bradley–Terry 损失，常数消掉，就得到只含策略的损失：

$$
\mathcal{L}_\text{DPO} = -\log\sigma\Big(\beta\Big[\log\frac{\pi(y_w|x)}{\pi_\text{ref}(y_w|x)} - \log\frac{\pi(y_l|x)}{\pi_\text{ref}(y_l|x)}\Big]\Big)
$$

$\beta\log\frac{\pi}{\pi_\text{ref}}$ 就是 DPO **隐含的奖励**。训练策略的同时，也就训练了一个奖励模型，这就是论文标题说的“你的语言模型其实是一个奖励模型”。

![DPO 与 RLHF 的对比：RLHF 需要奖励模型、在线采样和四个模型；DPO 只要策略和冻住的参考模型，把偏好对直接放进损失](/tinyllm/figures/dpo-vs-rlhf.svg)

怎么读这张图：左边是第 41 章的流程，右边是 DPO；下面是 DPO 的损失。注意 DPO 不采样：它只在偏好数据里已有的回答上算对数概率。

这一章用和第 41 章**完全相同**的 SFT 模型、评审和偏好数据（同样的随机种子），把 PPO 换成 DPO。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/preference-alignment.py" download>preference-alignment.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/preference-alignment.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python preference-alignment.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/preference-alignment)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/preference-alignment.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3；以“[计时，本机]”开头的输出和机器有关，正文只引用它们的大致数值。
:::

## 1. 同一个起点、同一份偏好数据

SFT 模型、评审、偏好数据的代码都和[第 41 章](./rlhf.md)相同：

```text
[计时，本机] 预训练 2000 步 + SFT 1500 步（第 38 章种子 0），共 39.8 秒
[计时，本机] 15.2 秒；得到 1434 对（训练 1147、留出 287），其中 132 对标反了
```

## 2. DPO 的实现

<<< @/public/tinyllm/code/preference-alignment.py#dpo

和 SFT 几乎一样：每步取 16 对，对策略和参考模型各算两次对数概率（选中、落选），套进损失。参考模型冻住，它的对数概率在训练前一次算好存起来也可以（TRL 就提供这个选项），那样训练时只需要一个模型。没有采样，没有奖励模型，没有价值模型。

评估用和第 41 章同一套指标：

<<< @/public/tinyllm/code/preference-alignment.py#alignment-eval

## 3. 两个 β

学习率 1e-3、300 步，比较 β=0.1（DPO 论文和 TRL 的默认值）和 β=1；β=0.1 那次另在第 100、200 步各存一份。

<<< @/public/tinyllm/code/preference-alignment.py#dpo-runs

```text
[计时，本机] 两次 DPO 各 300 步，共 13.7 秒
SFT            评审 1.67  意象字 0.86  堆砌 2%  首字对 0.42  KL   0.0
DPO β=0.1 第 100 步 评审 1.64  意象字 4.78  堆砌 45%  首字对 0.05  KL  26.5
DPO β=0.1 第 200 步 评审 1.09  意象字 5.34  堆砌 78%  首字对 0.05  KL  35.6
DPO β=0.1      评审 0.00  意象字 4.52  堆砌 70%  首字对 0.00  KL  61.8
DPO β=1        评审 2.64  意象字 4.45  堆砌 44%  首字对 0.08  KL  17.4
DPO β=0.1 的隐含奖励：留出的 287 对上和标签一致 66%，和评审的真实判断一致 68%
DPO β=1 的隐含奖励：留出的 287 对上和标签一致 61%，和评审的真实判断一致 62%
DPO β=0.1：写一首五言绝句，用“桂”字开头。 → 叶下云云外，滋冷飘。春风月下，春水间，此远林秋。
DPO β=0.1：写一首五言绝句。 → 春山山外间，青海出云时。春春去去，夜月题然。
```

![DPO 的结果：左图是各个模型的评审分和堆砌比例，β=0.1 训到 300 步时评审分为 0，β=1 是 2.64，加 NLL 是 1.94；右图是选中、落选回答的对数概率，两者一起下降](/tinyllm/figures/dpo-results.svg)

怎么读这张图：左图实心柱是评审分，斜线柱是堆砌比例乘 4，最右边是第 41 章的 PPO（同一套评估）作对照；右图横轴是 DPO 的步数，纵轴是留出对子上的对数概率减去 SFT 的，星号是第 4 节加了 NLL 的结果。

- **β=1：和 PPO 差不多，而且便宜得多。** 评审 2.64，第 41 章的 PPO（β=0.05）是 2.53，两者都只有一个种子、64 条指令，这点差别在噪声以内；KL 只有 17.4（PPO 是 29.4，口径同第 41 章：评估时采样的回答上对数概率差的总和）。13.7 秒训了两次 DPO，PPO 一次就要约 27 秒，还要先训奖励模型。毛病也和 PPO 一样：44% 的回答堆砌，首字对掉到 0.08。偏好数据就是这么教的，换一种优化方法改变不了。
- **β=0.1：越训越坏。** 第 100 步评审 1.64，第 200 步 1.09，第 300 步变成 0，回答的句子长短都乱了（“叶下云云外，滋冷飘。”）。KL 涨到 61.8。β 小，KL 的约束就弱（DPO 的 β 和 PPO 的 β 是同一个意思），模型很容易被推离 SFT。
- **隐含奖励和第 41 章的奖励模型差不多准。** β=0.1 的隐含奖励在留出数据上和评审一致 68%，第 41 章专门训练的奖励模型是 65%。DPO 确实“顺便”学出了一个奖励模型。但要注意，隐含奖励最准的恰恰是评审 0 分的 β=0.1 模型，β=1 只有 62%：隐含奖励判断对子准不准，和策略自己生成的回答好不好是两回事。

β=0.1 是 DPO 论文的默认值，为什么在这里坏得这么快？这一章的学习率（1e-3）比大模型上 DPO 常用的（1e-7～1e-6 量级）大得多，每步走得远；偏好数据只有一千多对，300 步每对看了四遍多。β 和学习率、步数是一起起作用的。

## 4. 选中和落选的概率一起往下掉

DPO 的损失只要求“选中比落选的对数概率比值大”，并不要求选中的概率变高。看看留出对子上，两者的对数概率（减去 SFT 的）怎样变化；再试一个常见的补救：损失里加上“选中”回答的负对数似然（按 token 平均，系数 1）：

<<< @/public/tinyllm/code/preference-alignment.py#logprob-drift

```text
[计时，本机] 6.9 秒
β=0.1 第 100 步     ：选中  -21.28  落选  -25.89  差  +4.61
β=0.1 第 200 步     ：选中  -41.04  落选  -47.57  差  +6.52
β=0.1 第 300 步     ：选中  -48.77  落选  -57.20  差  +8.44
β=0.1 加 NLL，第 300 步：选中   -8.01  落选   -9.78  差  +1.76
DPO β=0.1 + NLL 评审 1.94  意象字 1.61  堆砌 3%  首字对 0.24  KL  11.1
```

- **两边都在降，只是落选的降得更多。** 300 步后，选中回答的对数概率比 SFT 低了 48.8（一首绝句二三十个 token，平均每个 token 低约 2），落选的低了 57.2，差从 0 拉开到 8.4，损失确实在下降。可是“选中”的回答在模型看来也越来越不可能了：概率被挪到了偏好数据里根本没有的回答上，第 3 节那些句子长短错乱的回答就是从这里来的。[Smaug（DPO-Positive）](https://arxiv.org/abs/2402.13228)从理论上说明了标准 DPO 会降低选中回答的概率，并发现选中、落选两个回答越相近，这种现象越严重。
- **加上 NLL：拴住选中回答的概率。** 选中只降了 8.0，落选降了 9.8，评审分 1.94，几乎不堆砌（3%），首字对 0.24，KL 11.1。它比 β=1 保守：评审分没有 β=1 高，但其他能力保住得多。[Iterative RPO](https://arxiv.org/abs/2404.19733)在推理任务上用的就是“DPO + NLL”，作者说这一项是关键；TRL 里写成 `loss_type=["sigmoid", "sft"]`。

## 5. 常见变体

| 方法 | 改了什么 | 解决什么 |
| --- | --- | --- |
| [IPO](https://arxiv.org/abs/2310.12036) | 记 $\Delta$ 为选中、落选两边“策略对数概率减参考对数概率”之差（不乘 β），把 $-\log\sigma(\beta\Delta)$ 换成 $(\Delta - \frac{1}{2\tau})^2$，让差值停在一个目标上 | 偏好几乎确定时，DPO 会把差值推向无穷大，过拟合 |
| [KTO](https://arxiv.org/abs/2402.01306) | 不需要成对，只需要每个回答“好”或“不好”的标签 | 成对的偏好数据难收集 |
| [SimPO](https://arxiv.org/abs/2405.14734) | 用按长度平均的对数概率当奖励，去掉参考模型，加一个间隔 | 省掉参考模型，减少长度偏好 |
| DPO + NLL | 加上选中回答的负对数似然 | 选中回答的概率一起下降（第 4 节） |

## 动手实验

1. **更小的学习率。** β=0.1，学习率换成 1e-4，训 300 步。还会越训越坏吗？评审分最高能到多少？
2. **IPO。** 把损失换成 $(\Delta - \frac{1}{2\tau})^2$（$\Delta$ 是不乘 β 的对数概率比之差），τ=0.1。选中的对数概率还会一路往下掉吗？
3. **在线 DPO。** 每训 100 步，用当前模型重新采样、让评审重新配对，再接着训（第 41 章的 `pairs` 一节）。和一直用同一份偏好数据比怎样？这是 PPO 能在线探索、DPO 不能的那部分。
4. **干净的标签。** 把 10% 的标反去掉，重做 β=1。评审分能提高多少？这说明了偏好数据的质量有多重要。

<!-- real-model:start -->

## 在真实模型里

TRL 的 `DPOTrainer` 实现了本章的 DPO 和十几种变体，用 `loss_type` 选择，可以组合。下表的链接都指向 Hugging Face trl 的固定版本 `v1.18.2`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| β 与损失类型 | [`DPOConfig`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/dpo_config.py#L23-L390) | `beta` 默认 0.1；`loss_type` 默认 `["sigmoid"]`（标准 DPO），还有 `ipo`、`hinge`、`robust` 等；写成 `["sigmoid", "sft"]` 并配上 `loss_weights`，就是本章第 4 节在损失里加“选中”回答的负对数似然 |
| 标准 DPO 的损失 | [`dpo_trainer.py 第 1468 行`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/dpo_trainer.py#L1468) | `-F.logsigmoid(self.beta * delta_score)`：默认设置下 `delta_score` 是选中、落选两边“策略对数概率减参考模型对数概率”之差，和本章的 `dpo` 一样 |
| 加上 NLL | [`dpo_trainer.py 第 1576 行`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/dpo_trainer.py#L1576) | `-chosen_per_token_logps[chosen_mask].mean()`：“选中”回答每个 token 的负对数似然取平均，和 DPO 损失按 `loss_weights` 加权相加 |
| 参考模型的对数概率 | [`DPOTrainer._precompute_ref_logps`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/dpo_trainer.py#L1249-L1322) | 参考模型冻住，它对每个对子的对数概率可以在训练前一次算好存进数据集，训练时就不用再加载参考模型 |

想在本机看源码，可以先 `pip install trl`，再用 `python -m inspect trl.trainer.dpo_config:DPOConfig` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 做偏好对齐用<strong>DPO</strong>：从 SFT 模型出发，参考模型就是 SFT 模型（冻住），用成对的偏好数据训练；β 和学习率要一起调，在本章的设定（学习率 1e-3）下 β 取 1；在损失里加上选中回答的负对数似然，防止选中回答的概率一起下降（本章只在 β=0.1 上试过 NLL，β=1 加 NLL 的组合没有跑，用之前要先验证）；训练过程中定期用独立的评审（真实场景里是人工评估或更强的模型）检查，同时看奖励没覆盖到的能力，提前停在评审分最高的地方。

为什么：在和第 41 章同一份偏好数据上，DPO β=1 的评审分 2.64、KL 17.4，PPO（β=0.05）是 2.53、29.4；DPO 两次训练共 13.7 秒，不需要奖励模型和采样。β=0.1 时评审分从 1.64 一路掉到 0，选中回答的对数概率降了 48.8；加上 NLL 后只降 8.0，评审分 1.94，几乎不堆砌，首字对 0.24（SFT 是 0.42，β=0.1 不加 NLL 是 0）。DPO 的隐含奖励在留出数据上和评审一致 62%～68%，和单独训练的奖励模型（65%）相当，但它的高低和策略本身的好坏无关。

实验边界：偏好来自一个程序评审，偏好数据只有 1147 对，学习率比大模型上的常见值大几个数量级，所以 β=0.1 坏得特别快；每组只有一个种子，64 条评估指令，DPO β=1 和 PPO 的评审分差别在噪声以内；DPO 只用了离线的偏好数据，没有试在线 DPO；变体只列了表，没有跑。什么情况下要换：需要在线探索、偏好数据会随模型变化时，用在线 DPO 或第 41 章的 RL；只有“好/不好”的单个标签时，用 KTO；奖励能由程序判定时，用第 43 章的 GRPO。

::: warning 常见误区
- **DPO 不需要参考模型。** 标准 DPO 的损失里就有参考模型的对数概率，它起 KL 约束的作用；不要参考模型的是 SimPO 这类变体。
- **DPO 的损失降了，选中回答的概率就升了。** 损失只看差值；本章选中回答的对数概率降了 48.8，模型照样被训坏。
- **β 取默认值 0.1 就行。** β 和学习率、步数、数据量一起决定模型偏离多远；本章同样 0.1，训到 300 步评审分变成 0。
- **DPO 一定比 PPO 好（或差）。** 同一份偏好数据下两者的结果接近，毛病也一样（堆砌、首字退化）；偏好数据教了什么，比用哪种算法更重要。
- **DPO 不需要评估。** 它没有显式的奖励模型可看，更需要独立的评审来决定什么时候停。
:::

## 检查理解

1. 推导 DPO 时用到了 $r(x,y) = \beta\log\frac{\pi^*(y|x)}{\pi_\text{ref}(y|x)} + \beta\log Z(x)$。为什么代进 Bradley–Terry 损失后 $Z(x)$ 会消掉？

   <details><summary>参考答案</summary>

   Bradley–Terry 损失只用到同一个提示 $x$ 下两个回答的奖励之差 $r(x,y_w) - r(x,y_l)$。$\beta\log Z(x)$ 只和提示有关、和回答无关，两边相同，相减就消掉了。$Z(x)$ 是对所有可能回答求和的归一化常数，本来根本算不出来，正是因为它消掉了，DPO 才能只用两个回答的对数概率训练。

   </details>

2. 本章 DPO β=0.1 第 300 步时，选中回答的对数概率比 SFT 低了 48.8，损失却一直在降。概率去了哪里？为什么这会让格式坏掉？

   <details><summary>参考答案</summary>

   概率的总和是 1，选中和落选的回答都变得不可能，概率就挪到了偏好数据之外的回答上。DPO 的梯度只作用于数据里的这两个回答，对其他回答没有任何约束；离 SFT 越远，这些“别的回答”越可能是格式错乱、长短不一的句子。模型采样时正好抽到它们，所以评审分掉到 0。加 NLL 直接要求选中回答的概率不能降，就把概率留在了合理的回答附近。

   </details>

3. DPO 和 PPO 用同一份偏好数据，DPO 不采样、只看数据里已有的回答。这在什么情况下会是一个劣势？

   <details><summary>参考答案</summary>

   当最好的回答不在偏好数据里时。偏好数据来自 SFT 模型的采样，DPO 只能在这些回答之间调整概率；PPO 在训练中用当前的策略采样，能生成并评估数据里没有的新回答，在奖励模型可靠的前提下可以走得更远。反过来，奖励模型不可靠时，PPO 的在线探索也更容易钻空子（第 41 章）。在线 DPO（定期用当前模型重新采样、重新标注）是两者之间的折中。

   </details>

4. DPO 的隐含奖励只有 68% 和评审一致，为什么 β=1 的 DPO 仍然能把评审分从 1.67 提高到 2.64？

   <details><summary>参考答案</summary>

   68% 是在单个对子上判断哪个更好的准确率，可训练是在一千多对上平均的：大多数对子的方向是对的，平均下来的梯度仍然把模型推向评审喜欢的方向（意象字更多）。准确率不高带来的是噪声和偏差，比如它没学会“堆砌要扣分”，所以模型一边变好、一边开始堆砌。这和第 41 章奖励模型 65% 也能带来提升是一个道理。

   </details>

## 参考资料

- [Direct Preference Optimization: Your Language Model is Secretly a Reward Model，Rafailov 等，2023](https://arxiv.org/abs/2305.18290)
- [A General Theoretical Paradigm to Understand Learning from Human Preferences（IPO），Azar 等，2023](https://arxiv.org/abs/2310.12036) · [KTO，Ethayarajh 等，2024](https://arxiv.org/abs/2402.01306) · [SimPO，Meng 等，2024](https://arxiv.org/abs/2405.14734)
- [Smaug: Fixing Failure Modes of Preference Optimisation with DPO-Positive，Pal 等，2024](https://arxiv.org/abs/2402.13228)
- [Iterative Reasoning Preference Optimization，Pang 等，2024](https://arxiv.org/abs/2404.19733)
- [TRL 文档：DPO Trainer](https://github.com/huggingface/trl/blob/v1.18.2/docs/source/dpo_trainer.md)

偏好对齐的信号来自人的判断，噪声大、容易被钻空子。有些任务的对错可以由程序直接判定：答案对不对、代码能不能跑、诗押不押韵。下一章用这种奖励做强化学习。[第 43 章：GRPO 与可验证奖励](./grpo.md)。
