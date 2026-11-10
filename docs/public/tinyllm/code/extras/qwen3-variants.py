# %% [markdown]
# # 可选实验：同一个问题，问 base 模型和对话模型
#
# 配套教案：https://lewislau86.github.io/tinyllm/quickstart#base-and-chat
#
# 这是“30 分钟快速体验”的附加实验，不在快速体验的一分钟脚本里，CI 也不运行它：
# 它要额外安装 transformers，并从 Hugging Face 下载两个模型（约 1.2GB 和 1.5GB）。
#
#     python -m pip install "transformers>=4.51" "jinja2>=3.1"
#     python qwen3-variants.py
#
# 两个模型的版本固定到具体提交，生成一律用贪心解码，同一台机器上每次运行结果相同。
# CPU、bfloat16、2 核约 70 秒（不含下载），需要约 3GB 内存。

# %%
# region setup
import gc

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = ("Qwen/Qwen3-0.6B-Base", "da87bfb608c14b7cf20ba1ce41287e8de496c0cd")
CHAT = ("Qwen/Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca")

def load(name_and_revision):
    name, revision = name_and_revision
    tok = AutoTokenizer.from_pretrained(name, revision=revision)
    model = AutoModelForCausalLM.from_pretrained(name, revision=revision, dtype=torch.bfloat16)
    model.eval()
    return tok, model

def continue_text(tok, model, text, max_new_tokens=48):
    """把 text 原样编码，贪心地往后接 max_new_tokens 个 token，只返回新接上的部分。"""
    ids = tok(text, return_tensors="pt").input_ids
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
    return tok.decode(out[0, ids.shape[1]:], skip_special_tokens=False)

def top_next(tok, model, text, k=5):
    """text 后面第一个 token 的前 k 个候选和概率：两个模型做的都是这件事。"""
    ids = tok(text, return_tensors="pt").input_ids
    with torch.no_grad():
        probs = model(ids).logits[0, -1].float().softmax(-1)
    p, idx = probs.topk(k)
    return [(tok.decode([i]), round(v, 3)) for i, v in zip(idx.tolist(), p.tolist())]

def chat_prompt(tok, question):
    """把一条用户消息套进对话模板；关掉思考模式，让回答直接开始。"""
    messages = [{"role": "user", "content": question}]
    return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False)
# endregion setup

print("torch", torch.__version__)
QUESTION = "床前明月光的下一句是什么？"
# 写这一节时试过的全部提示，结果一个不删地打印出来
PROMPTS = [
    QUESTION,
    "李白是谁？",
    "写一首关于秋天的五言绝句。",
    "把“床前明月光”翻译成英文。",
    "用一句话解释什么是语言模型。",
]
answers = {}

# %% [markdown]
# ## 1. base 模型：把问题当成一段文字往下接

# %%
# region base
tok, model = load(BASE)
print("下一个 token 的前 5 名，base（原文）：  ", top_next(tok, model, QUESTION))
answers["base"] = [continue_text(tok, model, p) for p in PROMPTS]
# endregion base

# %% [markdown]
# ## 2. base 模型：把提示写成“问答文档”的样子

# %%
# region base-fewshot
FEW_SHOT = (
    "问：白日依山尽的下一句是什么？\n答：黄河入海流。\n"
    "问：春眠不觉晓的下一句是什么？\n答：处处闻啼鸟。\n"
    f"问：{QUESTION}\n答："
)
print("往下接：", repr(continue_text(tok, model, FEW_SHOT, max_new_tokens=16)))
# endregion base-fewshot

del model
gc.collect()

# %% [markdown]
# ## 3. 对话模型：同一个问题先套上对话模板

# %%
# region chat
tok, model = load(CHAT)
print("模型真正看到的文字：")
print(chat_prompt(tok, QUESTION))
print("下一个 token 的前 5 名，对话（套模板）：", top_next(tok, model, chat_prompt(tok, QUESTION)))
answers["chat"] = [continue_text(tok, model, chat_prompt(tok, p)) for p in PROMPTS]
# endregion chat

# %% [markdown]
# ## 4. 对话模型：不套模板，直接给裸文字

# %%
# region chat-raw
print("往下接：", repr(continue_text(tok, model, QUESTION)))
# endregion chat-raw

# %% [markdown]
# ## 5. 并排看：同一个提示，两个模型各写了什么

# %%
# region side-by-side
for p, a, b in zip(PROMPTS, answers["base"], answers["chat"]):
    print(f"【提示】{p}")
    print(f"  base：{a!r}")
    print(f"  对话：{b!r}")
# endregion side-by-side
