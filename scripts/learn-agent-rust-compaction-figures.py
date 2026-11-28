"""R08 diagrams (ADK-Rust 3.0) generated from verified sources and actual scenario evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r08-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/context-compaction"
    for filename, expected in evidence["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R08 evidence; run verify-agent-compaction.py")
    rows = {r["name"]: r for r in evidence["scenarios"]}
    tokens = evidence["est_tokens"]

    body = panel(40, 86, 410, 124, "运行之间：EventsCompactionConfig", ["每完成 N 次运行", "旧事件 → 摘要器 → 压缩事件写进会话"], "#2563eb")
    body += panel(510, 86, 410, 124, "运行之内：IntraCompactionConfig", ["每次请求模型前，估算超过阈值", "这次请求的历史 → 摘要器 → 替换"], "#2563eb")
    body += arrow("M245 210 V250 H480 V280") + arrow("M715 210 V250 H480")
    body += panel(160, 288, 640, 116, "框架：决定切口", ["不分开工具调用与结果，不越过等待审批的调用"], "#475569")
    body += arrow("M480 404 V440")
    body += panel(160, 448, 640, 116, "应用：FactSummarizer", ["摘要模型按事实清单写 JSON，逐项核对值和来源"], "#b45309")
    body += arrow("M320 564 V604") + arrow("M640 564 V604")
    body += panel(40, 612, 410, 104, "通过：用摘要替换", ["摘要不比原文短时框架不用"], "#0f766e")
    body += panel(510, 612, 410, 104, "不通过：返回错误", ["框架保留原历史，继续运行"], "#b91c1c")
    save("r08-compaction-pipeline.svg", "框架决定何时压、切在哪里；应用决定摘要写什么",
         "运行之间与运行之内两种压缩都由框架决定切口，把旧历史交给应用的摘要器；核对通过才替换，不通过就保留原历史。", 760, body)

    normal, intra = tokens["normal"], tokens["intra"]
    values = [
        ("normal：第一次运行最后一次请求", normal[5], "#64748b"),
        ("normal：第二次运行第一次请求", normal[6], "#0f766e"),
        ("intra：读第三份资料前", intra[4], "#64748b"),
        ("intra：压缩后（含第三份资料）", intra[5], "#0f766e"),
    ]
    maximum = max(v for _, v, _ in values)
    body = ""
    for index, (label, value, color) in enumerate(values):
        y = 96 + index * 86
        body += text(205, y + 24, label, 17, color, True)
        width = 440 * value / maximum
        body += '<rect x="420" y="{}" width="{}" height="34" rx="5" fill="{}"/>'.format(y, max(width, 2), color)
        body += text(420 + width + 46, y + 24, str(value), 17, color, True)
    trim = rows["naive-trim"]
    body += panel(40, 452, 880, 104, "naive-trim：只装入最近 2 条事件", ["请求同样很短，但目标文件不在其中：给出结论 = {}".format("是" if trim["conclusion"] else "否"),
                                                                  "数值是框架的估算 token（约 4 个 UTF-8 字节 1 个），不是 tokenizer 计数"], "#b91c1c")
    save("r08-context-bytes.svg", "缩短请求，同时保留继续行动的依据",
         "估算 token 来自实际运行：normal 第二次运行的请求比第一次运行最后一次请求小得多；intra 读完第三份资料后历史超过阈值，压缩后的请求只剩摘要和最后一对调用与结果；naive-trim 的请求同样很短，却丢了目标文件。", 600, body)

    gate = [("omit-fact", "漏写 target"), ("invent-fact", "测试通过"), ("bad-json", "不是 JSON"), ("summary-error", "摘要模型出错")]
    body = panel(40, 86, 880, 96, "摘要器逐项核对事实清单", ["键、值、顺序与清单一致，值能在被压缩的历史里找到"], "#b45309")
    for index, (name, label) in enumerate(gate):
        x = 40 + index * 225
        row = rows[name]
        body += panel(x, 226, 205, 132, name, [label, "压缩事件：{}".format(row["compactions"]), "结论：{}".format("是" if row["conclusion"] else "否")], "#0f766e")
        body += arrow("M{} 182 V218".format(x + 102))
    unchecked = rows["omit-unchecked"]
    body += panel(40, 402, 880, 110, "对照 omit-unchecked：同样漏写 target，但不核对", ["摘要被接受（压缩事件 {}），第二次运行找不到目标：结论 = {}".format(unchecked["compactions"], "是" if unchecked["conclusion"] else "否")], "#b91c1c")
    body += text(480, 560, "核对不通过时框架保留原历史继续运行：代价是请求没变短，而不是任务做错。", 18, "#475569")
    save("r08-summary-gate.svg", "摘要先核对，再进入历史",
         "漏写、虚构、格式错误和摘要模型出错都被拒绝，框架保留原历史，第二次运行照样给出结论；不核对时漏写的摘要被接受，任务无法继续。", 590, body)
