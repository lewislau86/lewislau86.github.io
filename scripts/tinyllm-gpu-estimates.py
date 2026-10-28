"""Estimate parameters, memory and compute for the optional “GPU 完整训练” route.

参数量由真实构建的模型数出来（在 meta 设备上构建，不占内存）；显存和计算量是公式估算，
用来在动手之前判断“我的显卡够不够”。实测时间和显存在第 12 章完成、真正在 GPU 上跑过之后补进页面。

结构与 TinyLLM 主线一致：Pre-Norm RMSNorm、带 RoPE 的因果注意力、SwiGLU（中间宽度 8d/3）、
输入嵌入与输出层共享权重。词表暂用统一唐诗语料的全部字（字符级）；第 12 章换成 BPE 后重新运行。

用法：python scripts/tinyllm-gpu-estimates.py   （需要 torch，几秒钟）
输出：scripts/data/tinyllm-gpu-estimates.json
"""

from pathlib import Path
import json

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/public/tinyllm/data/tang-poems.jsonl"
OUT = ROOT / "scripts/data/tinyllm-gpu-estimates.json"

CONFIGS = [  # 名字, d, 层数, 头数, 上下文长度, 每步序列数
    ("CPU 基线（第 12 章）", 256, 6, 8, 128, 32),
    ("GPU 小", 512, 8, 8, 512, 32),
    ("GPU 中（约 GPT-2 small）", 768, 12, 12, 1024, 16),
]


class Block(nn.Module):
    def __init__(self, d, h):
        super().__init__()
        hidden = 8 * d // 3
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.qkv, self.proj = nn.Linear(d, 3 * d, bias=False), nn.Linear(d, d, bias=False)
        self.gate, self.value, self.down = nn.Linear(d, hidden, bias=False), nn.Linear(d, hidden, bias=False), nn.Linear(hidden, d, bias=False)


class TinyLLM(nn.Module):
    def __init__(self, vocab, d, layers, heads):
        super().__init__()
        self.tok = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList(Block(d, heads) for _ in range(layers))
        self.norm = nn.RMSNorm(d)
        self.head = nn.Linear(d, vocab, bias=False)
        self.head.weight = self.tok.weight          # 共享权重，只算一次


def main() -> None:
    texts = [json.loads(line)["text"] for line in CORPUS.read_text(encoding="utf-8").splitlines()]
    vocab = len(set("".join(texts))) + 1            # +1：换行符
    tokens = sum(len(t) + 1 for t in texts)         # 字符级：每首诗加一个换行
    rows = []
    for name, d, layers, heads, T, batch in CONFIGS:
        with torch.device("meta"):
            params = sum(p.numel() for p in TinyLLM(vocab, d, layers, heads).parameters())
        # 训练状态：FP32 主权重 + FP32 梯度 + AdamW 两个状态，各 4 字节
        state_gb = params * 16 / 1e9
        # 激活（BF16，注意力用 SDPA/FlashAttention、不存 T×T 分数表）：每层约 34·T·d 字节/序列（Korthikanti 等 2022），
        # 外加输出层的 logits 与其梯度（FP32，各 4 字节）
        act_gb = batch * (34 * T * d * layers + 8 * T * vocab) / 1e9
        flops_per_epoch = 6 * params * tokens       # 前向 + 反向 ≈ 每个 token 6N 次运算
        rows.append({"name": name, "d": d, "layers": layers, "heads": heads, "context": T, "batch": batch,
                     "params": params, "train_state_gb": round(state_gb, 2), "activation_gb": round(act_gb, 2),
                     "total_gb": round(state_gb + act_gb, 2), "tokens_per_step": batch * T,
                     "pflops_per_epoch": round(flops_per_epoch / 1e15, 2)})
    data = {"vocab": vocab, "corpus_tokens": tokens, "configs": rows}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['name']:<18} 参数 {r['params'] / 1e6:6.1f}M  训练状态 {r['train_state_gb']:5.2f} GB  "
              f"激活 {r['activation_gb']:5.2f} GB  合计约 {r['total_gb']:5.2f} GB  一轮 {r['pflops_per_epoch']} PFLOP")
    print(f"词表 {vocab}，语料 {tokens:,} 个字符 token")


if __name__ == "__main__":
    main()
