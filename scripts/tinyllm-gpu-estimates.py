"""Estimate parameters, memory and compute for chapter 13 “TinyLLM 在 GPU 上完整实现”.

参数量由真实构建的模型数出来（在 meta 设备上构建，不占内存）；显存和计算量是公式估算，
用来在动手之前判断“我的显卡够不够”。实测时间和显存在第 12 章完成、真正在 GPU 上跑过之后补进页面。

GPU 两档分别按统一唐诗语料和唐宋诗大语料（字符级词表）计算。
结构与 TinyLLM 主线一致：Pre-Norm RMSNorm、带 RoPE 的因果注意力、SwiGLU（中间宽度 8d/3）、
输入嵌入与输出层共享权重。词表暂按字符级计算；第 12 章换成 BPE 后重新运行。

用法：python scripts/tinyllm-gpu-estimates.py   （需要 torch，几秒钟）
输出：scripts/data/tinyllm-gpu-estimates.json
"""

from pathlib import Path
import json

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/public/tinyllm/data/tang-poems.jsonl"
LARGE = ROOT / "docs/public/tinyllm/data/manifest-large.json"     # 大语料只需要 manifest 里的统计，不必真的下载
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


def estimate(name, vocab, d, layers, heads, T, batch, corpus_tokens):
    with torch.device("meta"):
        params = sum(p.numel() for p in TinyLLM(vocab, d, layers, heads).parameters())
    # 训练状态：FP32 主权重 + FP32 梯度 + AdamW 两个状态，各 4 字节
    state_gb = params * 16 / 1e9
    # 激活（BF16，注意力用 SDPA/FlashAttention、不存 T×T 分数表）：每层约 34·T·d 字节/序列（Korthikanti 等 2022），
    # 外加输出层的 logits 与其梯度（FP32，各 4 字节）
    act_gb = batch * (34 * T * d * layers + 8 * T * vocab) / 1e9
    return {"name": name, "vocab": vocab, "d": d, "layers": layers, "heads": heads, "context": T, "batch": batch,
            "params": params, "train_state_gb": round(state_gb, 2), "activation_gb": round(act_gb, 2),
            "total_gb": round(state_gb + act_gb, 2), "tokens_per_step": batch * T,
            "corpus_tokens": corpus_tokens, "tokens_per_param": round(corpus_tokens / params, 2),
            "pflops_per_epoch": round(6 * params * corpus_tokens / 1e15, 2)}   # 前向 + 反向 ≈ 每个 token 6N


def main() -> None:
    texts = [json.loads(line)["text"] for line in CORPUS.read_text(encoding="utf-8").splitlines()]
    small = {"vocab": len(set("".join(texts))) + 1, "tokens": sum(len(t) + 1 for t in texts)}   # +1：换行符
    large_manifest = json.loads(LARGE.read_text(encoding="utf-8"))
    large = {"vocab": large_manifest["vocab"] + 1, "tokens": large_manifest["chars"] + large_manifest["poems"]}
    rows = []
    for name, d, layers, heads, T, batch in CONFIGS:
        for corpus_name, c in (("统一唐诗语料", small), ("唐宋诗大语料", large)):
            if name.startswith("CPU") and corpus_name != "统一唐诗语料":
                continue
            r = estimate(name, c["vocab"], d, layers, heads, T, batch, c["tokens"])
            r["corpus"] = corpus_name
            rows.append(r)
    data = {"corpora": {"统一唐诗语料": small, "唐宋诗大语料": large}, "configs": rows}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['name']:<18} {r['corpus']:<8} 参数 {r['params'] / 1e6:6.1f}M  训练状态 {r['train_state_gb']:5.2f} GB  "
              f"激活 {r['activation_gb']:5.2f} GB  合计约 {r['total_gb']:5.2f} GB  每参数 {r['tokens_per_param']} token  一轮 {r['pflops_per_epoch']} PFLOP")
    print("语料", data["corpora"])

if __name__ == "__main__":
    main()
