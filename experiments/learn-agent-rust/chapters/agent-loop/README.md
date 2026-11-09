# R01 最小 Agent 循环

教程：https://lewislau86.github.io/learn-agent-rust/agent-loop

本章只有 Rust 标准库依赖。
从代码库根目录运行 `python3 run.py run R01`，或在本目录运行：

```sh
rustc --edition=2024 -D warnings agent-loop.rs -o lab
./lab
```

全部输出见 outputs/，验证口径见 evidence.json。模型使用固定脚本，文件读取实际发生。
