"""P01 application checkpoints from verified PostgreSQL experiments."""
import hashlib
import json


def generate(root,text,panel,arrow,save):
    evidence=json.loads((root/"scripts/data/learn-agent-rust/p01-results.json").read_text())
    source=root/"docs/public/learn-agent-rust/code/postgres-checkpoints"
    for name,digest in evidence["files_sha256"].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:
            raise ValueError("P01 evidence stale; run verify-agent-checkpoints.py")
    rows={r["scenario"]:r for r in evidence["scenarios"]}
    normal=rows["normal"]["metrics"]
    body=panel(40,100,400,130,"旧进程 · 运行中的应用",["消息与调用 ID · cursor · phase","模型和工具对象 · 数据库连接"])
    body+=arrow("M440 165 H510")
    body+=panel(520,100,400,130,"PostgreSQL · 可序列化快照",["状态格式 + 工作流版本 + 修订","当前状态与历史，在同一事务保存"],"#0f766e")
    body+=arrow("M720 230 V276")
    body+=panel(40,284,880,140,"新进程 · 从快照重建",["连接与工具对象重新创建；从保存的推进位置继续","完成态实测：{} 次模型 / {} 次工具 / {} 条消息".format(normal["model_turns"],normal["tool_dispatches"],normal["messages"])],"#0f766e")
    body+=text(480,474,"保存数据，而非旧进程的栈、句柄或线程。",19,"#475569")
    save("p01-state-boundary.svg","检查点保留继续执行需要的数据","旧进程将消息、位置与预算写入 PostgreSQL，新进程重新创建运行对象并恢复状态。",515,body)

    a=rows["tool-granularity"]["metrics"]
    b=rows["batch-granularity"]["metrics"]
    body=text(480,90,"同样的两条读取：read-1 → read-2",21,"#475569")
    body+=panel(40,120,400,120,"batch · 一次结果提交",["先执行 read-1，再执行 read-2","执行中断：批次 in-flight"],"#b45309")
    body+=arrow("M440 180 H510")
    body+=panel(520,120,400,120,"一次工具步骤后",["已保存 {} 条结果".format(b["tool_results"]),"cursor = {}".format(b["after_tool_step_cursor"])],"#b45309")
    body+=panel(40,300,400,120,"tool · 每条结果提交",["执行 read-1 → 保存结果与游标","下次进程执行 read-2"],"#0f766e")
    body+=arrow("M440 360 H510")
    body+=panel(520,300,400,120,"一次工具步骤后",["已保存 {} 条结果".format(a["tool_results"]),"cursor = {}".format(a["after_tool_step_cursor"])],"#0f766e")
    body+=text(480,474,"两种模式都先预留额度；保存边界决定可恢复的位置。",19,"#475569")
    save("p01-checkpoint-granularity.svg","检查点位置决定从哪个工具继续","相同两次读取在整批模式合并保存，逐工具模式保留第一条独立结果与游标。",515,body)

    m=rows["external-effect-window"]["metrics"]
    body=panel(40,95,880,105,"① 动作前 · 数据库已提交",["tool_in_flight · 预留工具次数 = {}".format(m["reserved_dispatches"])])
    body+=arrow("M480 200 V238")
    body+=panel(40,246,400,130,"② 真实文件追加成功",["audit.log = {} 行".format(m["external_log_lines"]),"随后进程以 75 退出"],"#b45309")
    body+=panel(520,246,400,130,"结果事务还未保存",["已保存 read 结果 = {}".format(m["saved_tool_results"]),"已保存 append 结果 = {}".format(m["saved_append_results"])],"#b91c1c")
    body+=arrow("M240 376 V414 H480 V432")
    body+=arrow("M720 376 V414 H480")
    body+=panel(40,440,880,105,"③ 新进程恢复 · reconcile",["额度保留，停止自动推进；再次 step 仍不追加日志"],"#0f766e")
    body+=text(480,592,"相同标记也可能来自动作前退出；结果需要外部核对。",18,"#475569")
    save("p01-uncertain-action.svg","业务成功与快照成功之间存在窗口","实测日志已经追加一行，数据库没有追加结果；恢复保留累计预算并进入对账。",630,body)

    body=""
    for x,name,title,color in [(40,"exit-before-commit","提交前退出","#b45309"),(520,"exit-after-commit","提交后确认丢失","#0f766e")]:
        m=rows[name]["metrics"]
        body+=panel(x,95,400,105,title,["process exit = {}".format(m["exit_code"])],color)
        body+=arrow("M{} 200 V238".format(x+200))
        body+=panel(x,246,400,105,"新进程读取",["当前 revision = {}".format(m["revision_after_exit"])],color)
        body+=arrow("M{} 351 V389".format(x+200))
        body+=panel(x,397,400,130,"原 save_id 重试",["replayed = {}".format(str(m["retry_replayed"]).lower()),"最终历史快照 = {} 份".format(m["final_checkpoints"])],"#0f766e")
    body+=text(480,577,"保存身份确认原提交；当前状态与历史在同一事务更新。",18,"#475569")
    save("p01-commit-recovery.svg","提交发生在哪里，决定重启看到什么","提交前退出回滚，提交后确认丢失可按原保存身份获得回执，两种路径最终均只有两份快照。",615,body)
