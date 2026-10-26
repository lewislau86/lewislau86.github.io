# Chapter 17：训练循环与检查点

本章教案与实验尚在规划中。预计覆盖：DataLoader、forward/backward、optimizer/scheduler step、随机种子、保存与恢复。

## 本章主线选择（待实验验证）

主线显式记录随机种子、tokenizer 与模型配置；每次更新按 `zero_grad → forward → backward → clip → optimizer.step → scheduler.step` 执行，并保存模型、优化器、调度器和随机数状态。梯度累积时，多个 micro-batch 共同完成一次更新，学习率调度器只在真正更新后推进。恢复训练要用同一数据位置与配置，否则“接着训”可能改变数据顺序。[PyTorch 检查点教程](https://pytorch.org/tutorials/recipes/recipes/saving_and_loading_a_general_checkpoint.html)

返回 [课程总目录](index.md#课程路线规划)。
