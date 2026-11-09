"""R15 team diagrams, generated from checked sources and real scenario evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r15-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/agent-teams"
    for filename, expected in evidence["source_sha256"].items():
        if hashlib.sha256((package / filename).read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R15 evidence; run verify-agent-teams.py")
    rows = {r["scenario"]: r for r in evidence["scenarios"]}
    normal, persistent, full, cancelled = [rows[name] for name in ("normal", "persistent", "mailbox-full", "cancel-busy")]

    body = panel(40, 82, 880, 112, "Lead：应用编排", ["创建成员 → 投递工作 → 等待回执 → 关闭团队", "先分别入队，再等待两份报告"])
    body += arrow("M250 194 V236") + arrow("M710 194 V236")
    for x, name, file in [(40, "core", "src/lib.rs"), (500, "config", "config.toml")]:
        member = normal["members"][name]
        body += panel(x, 244, 420, 112, name + " 的独立邮箱", ["容量：{} 条；一个接收者".format(normal["limits"]["mailbox"]), "Work / Note；回执走 oneshot"], "#0f766e")
        body += arrow("M{} 356 V398".format(x + 210))
        body += panel(x, 406, 420, 112, name + " 的私有历史", ["normal：{} 条消息".format(len(member["messages"])), "ModelTurn ↔ ExecuteTools"], "#2563eb")
        body += arrow("M{} 518 V560".format(x + 210))
        body += text(x + 210, 590, file, 22, "#0f766e", True)
    body += '<rect x="40" y="550" width="880" height="78" rx="12" fill="none" stroke="#b45309" stroke-width="2"/>'
    body += text(480, 662, "同一个临时工作区 · 固定读取白名单 · 两位成员都没有写权限", 20, "#b45309", True)
    body += text(480, 704, "历史分别保存，文件视图共享；交流只传递明确的 Note。", 18, "#475569")
    save("r15-team-contexts.svg", "每位队友有自己的历史，共用受限工作区", "真实 normal 场景启动两个成员，各有容量为二的邮箱与五条私有消息，分别读取不同文件。", 734, body)

    body = panel(40, 82, 880, 102, "测试门先暂停 core 的接收循环", ["确定性地填队列，不靠 sleep 猜测时序"], "#64748b")
    body += arrow("M480 184 V226")
    body += panel(40, 234, 420, 132, "容量 {}：one + two".format(full["limits"]["mailbox"]), ["两条 Note 已经成功入队", "模型尝试尚为零"], "#0f766e")
    body += panel(500, 234, 420, 132, "第三条：three", ["try_send → mailbox_full", "未登记 ID，也未增加入队数"], "#b91c1c")
    body += arrow("M250 366 V410") + arrow("M710 366 V410")
    body += panel(40, 418, 880, 132, "打开测试门，消费后重投原来的 three", ["最终成功入队：{}；接收端 notes：{}".format(full["usage"]["accepted"], full["members"]["core"]["notes"]),
                     "三个回执均为 noted；模型尝试：{}".format(full["usage"]["models"])], "#2563eb")
    body += text(480, 596, "这次重投由实验控制器发起；运行时没有隐藏的自动重试。", 18, "#475569")
    save("r15-mailbox-backpressure.svg", "邮箱容量要成为发送方可见的结果", "真实 mailbox-full 场景拒绝第三条消息，释放接收门后用相同 ID 重投，三条消息最终全部消费。", 628, body)

    core = persistent["members"]["core"]
    assert core["events"] == ["idle", "busy", "idle", "note:followup", "busy", "idle", "closing", "closed"]
    phases = [("等待", "idle", "#64748b"), ("第一次审查", "busy", "#2563eb"),
              ("保留历史再等", "idle", "#64748b"), ("消费追问", "note:followup", "#0f766e"),
              ("第二次审查", "busy", "#2563eb"), ("等待新工作", "idle", "#64748b")]
    body = ""
    for i, (heading, state, color) in enumerate(phases):
        x = 40 + (i % 2) * 460
        y = 86 + (i // 2) * 156
        body += panel(x, y, 420, 104, heading, [state], color)
        if i % 2 == 0:
            body += arrow("M460 {} H494".format(y + 52))
        elif i < len(phases) - 1:
            body += arrow("M710 {} V{} H250 V{}".format(y + 104, y + 130, y + 150))
    body += panel(40, 576, 880, 112, "团队退出才结束成员", ["closing → closed；源码实际重读 {} 次".format(core["reads"]),
                   "历史保留 {} 条；config 未收到私有追问".format(len(core["messages"]))], "#b45309")
    body += text(480, 732, "来自 persistent 成员内实际事件序列；框的位置表示先后，不表示时长。", 17, "#475569")
    save("r15-member-lifecycle.svg", "一次工作结束，队友回到等待", "同一 core 成员两次进入 busy，之间保留第一次历史并接收 followup，团队关闭后才退出。", 760, body)

    body = panel(40, 82, 880, 112, "取消通过独立 watch 信号", ["不占用业务邮箱槽位", "模型异步等待可以被取消"], "#b45309")
    body += arrow("M250 194 V236") + arrow("M710 194 V236")
    body += panel(40, 244, 420, 112, "当前 Work", ["core-1 → cancelled", "实际文件读取：{}".format(cancelled["usage"]["reads"])], "#b91c1c")
    body += panel(500, 244, 420, 112, "尚未开始的 Work", ["queued → cancelled_queued", "为已接受消息补齐退出回执"], "#64748b")
    body += arrow("M250 356 V400") + arrow("M710 356 V400")
    body += panel(40, 408, 880, 132, "关闭接收端，等待全部 JoinHandle", ["spawned={} · joined={} · active={}".format(cancelled["usage"]["spawned"], cancelled["usage"]["joined"], cancelled["usage"]["active"]),
                    "强制 abort={}；随后删除自建临时目录".format(cancelled["usage"]["aborted"])], "#0f766e")
    body += text(480, 586, "本例验证单进程资源回收；没有跨进程关闭握手或消息恢复。", 18, "#475569")
    save("r15-shutdown-boundary.svg", "取消、回执和资源回收分别确认", "cancel-busy 场景的当前工作和排队工作分别收到取消状态，两位成员都已 join，活跃任务为零。", 618, body)
