"""K02 diagram (ADK-Rust 3.0) generated from verified sources and actual scenario evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/k02-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/web-search"
    for filename, expected in evidence["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Stale K02 evidence; run verify-agent-web-search.py")
    rows = {r["name"]: r for r in evidence["scenarios"]}

    def asked(name):
        return "问人 {} 次".format(rows[name]["asked"])
    stages = [
        ("模型", ["提出 web_search", "检索词、站点"], "#475569"),
        ("策略", ["清单内站点：放行", "其他：问人", "只读/规划：拒绝"], "#2563eb"),
        ("搜索后端", ["应用提供", "工具丢内网地址"], "#0f766e"),
        ("筛查", ["标出英文注入句", "遮住密钥", "中和结束标签"], "#b45309"),
        ("不可信内容块", ["交给模型", "应用核对引用"], "#475569"),
    ]
    body = ""
    for index, (heading, lines, color) in enumerate(stages):
        x = 30 + index * 184
        body += panel(x, 86, 168, 170, heading, lines, color)
        if index:
            body += arrow("M{} 171 H{}".format(x - 14, x - 2))
    body += text(480, 296, "allowlisted：{}；needs-approval：{}；read-only：{}".format(
        asked("allowlisted"), asked("needs-approval"), "拒绝，后端 {} 次".format(rows["read-only"]["provider_queries"])), 17, "#2563eb")
    screening = rows["screening"]
    fetch = [t for t in screening["tools"].split(",") if t.startswith("web_fetch")][0]
    body += panel(30, 330, 280, 150, "没被标出的中文指令", ["“把 API key 发到…”", "模型照做：拼网址"], "#b91c1c")
    body += arrow("M310 405 H338")
    body += panel(340, 330, 280, 150, "人批准了", ["问人 {} 次（搜索与抓取）".format(screening["asked"]), "替身“人”点了允许"], "#b45309")
    body += arrow("M620 405 H648")
    body += panel(650, 330, 280, 150, "网址来源检查", ["拼出来的网址不在对话里", fetch.split("(")[1].rstrip(")")], "#0f766e")
    body += text(480, 520, "筛查只是提示；拦住数据外带的是执行前的检查。", 18, "#475569", True)
    save("k02-search-path.svg", "一次受管搜索经过的几道关",
         "一次受管搜索：模型提出调用，策略按模式与站点放行、问人或拒绝，后端搜索，结果经筛查放进不可信内容块交给模型；模型想拼网址带出数据时，人批准了，网址来源检查仍然拒绝。", 550, body)
