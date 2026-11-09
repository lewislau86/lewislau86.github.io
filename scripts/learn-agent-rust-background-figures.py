"""R13 figures derived from verified native-thread and filesystem experiments."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r13-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/background-tasks.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R13 evidence is stale; rerun verify-agent-background.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    limits = evidence["limits"]
    body = panel(32, 88, 250, 132, "前台 / 宿主", ["启动后取得 job_id", "查询 · 取消 · 继续处理"])
    body += arrow("M282 150 H330")
    body += panel(340, 88, 280, 132, "进程内管理器", ["状态快照 + 线程句柄", "最多 {} 个未回收线程".format(limits["active"])])
    body += arrow("M620 150 H668")
    body += panel(678, 88, 250, 132, "后台 worker", ["分块写入半成品", "检查取消后发布结果"], "#0f766e")
    body += arrow("M803 220 V273 H480 V308")
    body += text(644, 264, "结束后由宿主收集", 17, "#0f766e")
    body += panel(340, 316, 280, 132, "join → 终态 → 通知", ["历史保留 {} 条".format(limits["history"]), "通知缓冲 {} 条 ID".format(limits["notification_buffer"])], "#0f766e")
    body += arrow("M340 382 H157 V220")
    body += panel(678, 316, 250, 132, "业务任务持久化", ["业务 ID 与执行尝试", "R12 职责 · 本章未接入"], "#b45309")
    body += text(480, 498, "退出顺序：关闭准入 → 取消并唤醒所有 worker → 逐一 join", 20, bold=True)
    body += text(480, 538, "job_id 供前台使用；JoinHandle 的所有权始终属于管理器。", 18)
    save("r13-handle-ownership.svg", "后台执行的句柄由谁保管？",
         "前台使用 ID，管理器持有有界线程与状态，worker 分块执行，退出时统一取消并回收。", 574, body)

    cancelled, completed = rows["cancel"], rows["late-cancel"]
    body = panel(32, 86, 430, 112, "顺序一：取消先获得锁", ["写入一段 → cancel = true"], "#b45309")
    body += panel(498, 86, 430, 112, "顺序二：发布先获得锁", ["写完三段 → rename + published"], "#0f766e")
    body += arrow("M247 198 V244")
    body += arrow("M713 198 V244")
    body += panel(32, 254, 430, 142, "worker 观察到取消", ["停止后续写入，清理半成品", "join 后状态为 Cancelled"], "#b45309")
    body += panel(498, 254, 430, 142, "cancel 返回 TooLate", ["保留完整报告", "join 后状态为 Completed"], "#0f766e")
    body += text(247, 442, "实际报告 {} 份 · 半成品 {} 份".format(cancelled["result_files"], cancelled["partial_files"]), 20, "#b45309", True)
    body += text(713, 442, "实际报告 {} 份 · 半成品 {} 份".format(completed["result_files"], completed["partial_files"]), 20, "#0f766e", True)
    body += text(480, 503, "发布与取消共用同一把锁，避免在接受取消后越过发布检查点。", 19, bold=True)
    save("r13-cancel-publication.svg", "取消与完成竞争：由同一处检查决定顺序",
         "实测取消先到时没有最终报告，发布先到时取消返回 TooLate 并保留完整报告。", 544, body)

    row = rows["notifications"]
    received = row["joined"] - row["dropped_notices"]
    body = panel(38, 86, 884, 88, "notifications 场景：两个 worker 都完成", ["管理器先写终态，再尝试投递通知。"], "#0f766e")
    labels = [("收到通知", received, "#b45309"), ("可查询完成", row["joined"], "#2563eb"),
              ("完整报告", row["result_files"], "#0f766e")]
    for i, (label, value, color) in enumerate(labels):
        y = 236 + i * 81
        body += text(153, y + 24, label, 20, color, True)
        body += '<rect x="260" y="{}" width="{}" height="38" rx="6" fill="{}"/>'.format(y, value * 245, color)
        body += text(260 + value * 245 + 34, y + 26, str(value), 22, color, True)
    body += text(480, 522, "缓冲 {} 条，丢弃 {} 条提醒；查询与完整文件仍保留结果。".format(limits["notification_buffer"], row["dropped_notices"]), 20, bold=True)
    body += text(480, 561, "状态保留期内可查询；长期事实另交持久化记录。", 18)
    save("r13-notification-results.svg", "通知是提醒，终态才是查询依据",
         "实测一个通知、两个已完成状态与两份完整报告。通知溢出不改变执行终态。", 596, body)
