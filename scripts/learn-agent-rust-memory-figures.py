"""R09 figures from separate-process verification evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    data = json.loads((root / "scripts/data/learn-agent-rust/r09-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/memory/src/main.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != data["source_sha256"]:
        raise ValueError("R09 evidence stale; run verify-agent-memory.py")
    rows = {row["name"]: row for row in data["scenarios"]}
    recalled = rows["new-process"]["steps"][-1]
    fact = recalled["fact"]
    value = fact["action"]["value"]
    body = panel(40, 90, 390, 140, "会话 A · 写入进程", ["显式要求：reply_language=" + value,
                 "来源：" + fact["source"]["session"]])
    body += panel(530, 90, 390, 140, "会话 B · 新进程", ["输入只有目录、作用域、键", "召回值：" + value], "#0f766e")
    body += arrow("M235 230 V314") + arrow("M725 318 V234")
    body += panel(40, 322, 880, 130, "磁盘 · memory.json", ["schema=1 · revision=" + str(recalled["revision"]),
                  "scope=" + fact["scope"] + " · key=" + fact["key"]], "#b45309")
    body += text(480, 280, "写入退出后，才启动读取", 19, "#64748b", True)
    body += text(480, 505, "new-process 实测：{} 次独立 CLI 调用，来源随事实一起恢复。".format(rows["new-process"]["processes"]), 19, "#0f766e", True)
    body += text(480, 545, "两个进程不共享 Rust 对象；未恢复消息、审批或任务检查点。", 18, "#475569")
    save("r09-process-recall.svg", "事实跨过进程边界，靠的是磁盘", "写入进程保存来源和事实，退出后新进程从同一存储召回，消息历史未传递。", 580, body)

    observed = [step for step in rows["forget"]["steps"] if step["label"].startswith("recall")]
    body = text(255, 88, "持久事件 · 原记录继续保留", 21, "#2563eb", True)
    body += text(720, 88, "当前召回视图", 21, "#0f766e", True)
    for index, step in enumerate(observed):
        y = 118 + index * 178
        fact = step["fact"]
        rev = step["revision"]
        if fact:
            lines = ["set：" + fact["action"]["value"], "来源：" + fact["source"]["session"]]
            current = ["值：" + fact["action"]["value"], "事实 revision=" + str(fact["revision"])]
        else:
            lines = ["forget：reply_language", "来源：session-D"]
            current = [step["status"] + "：停止召回", "历史原话仍存在"]
        body += panel(40, y, 430, 130, "事件 revision=" + str(rev), lines)
        body += arrow("M470 {} H526".format(y + 65))
        body += panel(530, y, 390, 130, "存储 revision=" + str(rev), current, "#0f766e" if fact else "#b45309")
        if index < len(observed) - 1:
            body += arrow("M255 {} V{}".format(y + 130, y + 173))
    body += text(480, 640, "forget 实测：{} 次独立进程；3 个事件，最终当前事实为空。".format(rows["forget"]["processes"]), 19, "#b45309", True)
    save("r09-revision-history.svg", "同一个事实更新，旧来源仍可追溯", "设置、更新、遗忘依次成为三个事件；当前视图变化，遗忘后历史仍保留原话。", 680, body)

    failure = rows["save-failure"]["steps"]
    before_error = next(step["error"] for step in failure if step["error"])
    body = panel(40, 88, 880, 92, "持有写者锁，读取并校验当前版本", ["过期版本 → revision_conflict；已有锁 → store_busy"])
    body += arrow("M480 180 V214")
    body += panel(40, 222, 420, 126, "写同目录临时文件", ["write_all → sync_all → close", "此时正式文件仍是旧字节"])
    body += arrow("M460 285 H526")
    body += panel(530, 222, 390, 126, "替换前故障", [before_error.replace("injected_", ""), "清理本次锁与临时文件"], "#b45309")
    body += arrow("M250 348 V382")
    body += panel(40, 390, 420, 126, "rename 替换正式文件", ["Unix 再同步目录项", "此后报错须重新读盘确认"], "#0f766e")
    body += arrow("M725 348 V382")
    body += panel(530, 390, 390, 126, "新进程再读旧文件", ["status=" + failure[-1]["status"],
                  "值：" + failure[-1]["fact"]["action"]["value"]], "#0f766e")
    body += text(480, 562, "已验证：替换前故障保持旧字节；损坏记录拒读、拒写且保留原文件。", 18, "#475569")
    body += text(480, 602, "未演练：断电恢复、强制终止、高并发压力与网络盘。", 18, "#475569")
    save("r09-storage-boundaries.svg", "把保存失败放在准确的提交位置", "写临时文件并同步后替换正式文件；替换前故障保留旧文件，替换后错误需重新确认状态。", 640, body)
