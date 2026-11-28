"""R09 diagrams (ADK-Rust 3.0) generated from verified sources and actual scenario evidence."""
import hashlib
import json
import re


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r09-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/memory"
    for filename, expected in evidence["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R09 evidence; run verify-agent-memory.py")
    rows = {r["name"]: r for r in evidence["scenarios"]}

    first, second = rows["new-process"]["steps"]
    body = panel(40, 86, 390, 150, "进程 1 · 会话 A", ["“请记住：reply_language=中文”", "remember 核对原话后写入", "结果：" + first], "#2563eb")
    body += panel(530, 86, 390, 150, "进程 2 · 会话 B", ["“以后请用什么语言回答？”", "消息历史为空：system,user", "recall_memory 按键取最新"], "#0f766e")
    body += arrow("M235 236 V300") + arrow("M725 300 V240")
    body += panel(40, 306, 880, 120, "SQLite 文件 · SqliteMemoryService", ["app=workspace-assistant · user=user-1 · project=project-a",
                                                                         "reply_language=中文 · 来源 session-A 与原话"], "#b45309")
    body += text(480, 470, "进程 2 的结果：" + second, 18, "#0f766e", True)
    body += text(480, 506, "会话服务在进程内存里，进程退出就没了；留到下一个进程的只有这个文件。", 17, "#475569")
    save("r09-process-recall.svg", "跨过进程边界的是文件，不是会话",
         "进程 1 核对用户原话后把偏好写进 SQLite 文件并退出；进程 2 的消息历史是空的，按键从同一个文件召回中文偏好和来源会话。", 540, body)

    load = rows["naive-load"]["steps"]
    preload = rows["preload"]["steps"]
    found = re.match(r"recall:found (\S+) from (\S+) versions=(\d+)", load[3])
    loaded = re.match(r"load_memory:count=(\d+) first=(\S+)", load[2])
    injected = [re.match(r"preload:injected=(\d+)", step)[1] for step in preload[1:]]
    body = text(480, 80, "同一个文件里有两条 reply_language：先写的中文，后写的 English", 18, "#475569")
    body += panel(40, 106, 280, 220, "应用的 recall_memory", ["检索词：键名", "按时间取最新一条",
                  "共 {} 个版本".format(found[3]), "结果：{}（{}）".format(found[1], found[2])], "#0f766e")
    body += panel(340, 106, 280, 220, "LoadMemoryTool", ["检索词：模型自己写", "相关度相同，按写入顺序",
                  "返回 {} 条".format(loaded[1]), "模型用了第一条：" + loaded[2]], "#b45309")
    body += panel(640, 106, 280, 220, "PreloadMemoryTool", ["检索词：用户原话", "注入系统消息",
                  "自然语言问句：注入 {} 条".format(injected[0]), "含键名的问句：注入 {} 条".format(injected[1])], "#2563eb")
    body += text(480, 372, "naive-load：模型用了第一条，答成中文——过期的偏好", 18, "#b91c1c", True)
    body += text(480, 408, "preload：一串汉字是一个词，问句里没有记录里的词，检索为空", 18, "#475569")
    save("r09-recall-paths.svg", "三种召回方式，检索词从哪里来、谁挑结果",
         "应用的 recall_memory 按键取最新一条；LoadMemoryTool 返回检索到的两条，相关度相同时旧的排在前面，模型用了它；PreloadMemoryTool 用用户原话检索，自然语言问句检索不到。", 440, body)

    forget = rows["forget"]
    erase = rows["erase"]
    checks = dict(c.split("=") for c in erase["checks"].split())
    forget_has = forget["checks"].split("=")[1]
    levels = [
        ("forget：delete_memory", "删掉这个键的每个版本：" + forget["steps"][2].split(":")[1], "文件里还找得到 English（原样或小写）：" + forget_has, "#b45309"),
        ("erase：delete_user", "删掉用户的全部行", "文件里还找得到 English（原样或小写）：" + checks["after_delete_file_has_English"], "#b45309"),
        ("erase --compact", "合并全文索引 + VACUUM", "文件里还找得到 English（原样或小写）：" + checks["after_compact_file_has_English"], "#0f766e"),
    ]
    body = ""
    for index, (heading, what, residue, color) in enumerate(levels):
        y = 86 + index * 132
        body += panel(40, y, 880, 112, heading, [what, residue], color)
    body += text(480, 498, "三种做法之后检索都为空；只有第三种让文件里不再有原文。备份、日志与已发给模型的上下文不在其中。", 17, "#475569")
    save("r09-deletion-levels.svg", "检索不到，不等于文件里没有",
         "forget 和 delete_user 之后检索为空，但 SQLite 文件里仍能找到 English；合并全文索引并 VACUUM 之后，文件里才不再有这段文字。", 530, body)
