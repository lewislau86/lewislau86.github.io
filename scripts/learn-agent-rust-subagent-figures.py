"""R06 figures, called by generate-learn-agent-rust-figures.py --lesson R06."""

import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r06-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/subagents.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R06 evidence is stale; run verify-agent-subagents.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    normal, limited, cancelled = (rows[name] for name in ("normal", "parent-answer-budget", "cancel"))

    body = text(240, 85, "父模型上下文", 22, "#2563eb", True)
    body += text(720, 85, "子模型上下文", 22, "#0f766e", True)
    parent = [(112, "system", "PARENT_ONLY_NOTE"), (210, "user", "读取项目启动命令"),
              (308, "assistant：委派请求", "parent/delegate-1"),
              (602, "tool：子任务报告", "状态 + 启动命令 + 用量"),
              (700, "assistant：用户回答", "项目启动命令：cargo run")]
    child = [(112, "system", "子工具规则与返回要求"), (210, "user", "本次子任务说明"),
             (308, "assistant：文件读取", "child-1/read-1"),
             (406, "tool：文件原文", "含 CHILD_RAW_ONLY 标记"),
             (504, "assistant：提取结果", "启动命令：cargo run")]
    for y, title, line in parent:
        body += panel(40, y, 400, 82, title, [line], "#2563eb")
    for y, title, line in child:
        body += panel(520, y, 400, 82, title, [line], "#0f766e")
    for start, end in [(194, 210), (292, 308), (684, 700)]:
        body += arrow("M240 {} V{}".format(start, end - 4))
    body += arrow("M240 390 V420 H64 V560 H240 V598")
    for y in [194, 292, 390, 488]:
        body += arrow("M720 {} V{}".format(y, y + 12))
    body += arrow("M440 349 H478 V251 H516")
    body += arrow("M520 545 H486 V643 H444")
    body += text(246, 474, "完整子历史留在宿主诊断中", 18, "#475569")
    body += text(480, 834, "正常运行：父 {} 条 / 子 {} 条消息；两份历史独立追加。".format(normal["parent_messages"], normal["child_messages"]), 20, "#0f766e", True)
    body += text(480, 872, "标记仅检查本实验的数据流；共享工作区仍由工具策略限制。", 17, "#475569")
    save("r06-context-boundary.svg", "只把任务交出去，只把报告带回来", "父历史包含委派和报告，子历史从自己的规则和任务开始，文件原文仅保留在子诊断历史中。", 900, body)

    parent_models = normal["total_models"] - normal["child_models"]
    parent_tools = normal["total_tools"] - normal["child_tools"]
    body = panel(40, 90, 540, 110, "正常路径：共享总用量", ["模型 {} 轮 / 工具 {} 次".format(normal["total_models"], normal["total_tools"])])
    body += arrow("M200 200 V240") + arrow("M560 200 H600 V382 H310 V396")
    body += panel(40, 248, 540, 112, "父侧分项", ["模型 {} 轮：委派、最终回答".format(parent_models), "工具 {} 次：delegate".format(parent_tools)])
    body += panel(40, 400, 540, 112, "子侧分项与局部额度", ["模型 {} 轮 / 工具 {} 次".format(normal["child_models"], normal["child_tools"]), "实际文件读取 {} 次".format(normal["reads"])], "#0f766e")
    body += panel(620, 90, 300, 144, "总模型额度只有 3", ["先用父侧 1 轮", "再用子侧 2 轮"], "#b45309")
    body += arrow("M770 234 V274")
    body += panel(620, 282, 300, 112, "子任务已完成", [limited["child_stop"]], "#0f766e")
    body += arrow("M770 394 V434")
    body += panel(620, 442, 300, 112, "父最终回答被拦截", [limited["parent_stop"]], "#b45309")
    body += text(480, 612, "实际运行：总模型 {} / 总工具 {}；子完成，练习目标仍为 false。".format(limited["total_models"], limited["total_tools"]), 19, "#b45309", True)
    body += text(480, 650, "次数在调用前扣除；局部或总账拒绝的动作不执行、不增加用量。", 17, "#475569")
    save("r06-shared-budget.svg", "每个子任务有限额，父子总账也有限额", "正常路径父子累计四轮模型和两次工具尝试，总模型额度为三时，子任务完成后父回答无法开始。", 682, body)

    body = text(240, 86, "父侧：句柄所有者", 22, "#2563eb", True)
    body += text(720, 86, "子侧：协作退出", 22, "#0f766e", True)
    body += panel(520, 112, 400, 90, "请求文件读取，发送 ready", ["随后在放行通道等待"], "#0f766e")
    body += arrow("M520 158 H444")
    body += panel(40, 112, 400, 90, "收到控制点通知", ["子模型已调用 {} 轮".format(cancelled["child_models"])])
    body += arrow("M240 202 V238")
    body += panel(40, 246, 400, 90, "设置取消标记，再唤醒", ["或关闭发送端解除等待"])
    body += arrow("M440 291 H516")
    body += panel(520, 246, 400, 90, "观察取消或通道断开", ["补上取消结果，不读取文件"], "#0f766e")
    body += arrow("M720 336 V372")
    body += panel(520, 380, 400, 90, "离开子资源作用域", ["Drop 清理 scratch，返回报告"], "#0f766e")
    body += arrow("M520 425 H444")
    body += panel(40, 380, 400, 90, "join 等到线程结束", ["确认没有继续运行的子线程"])
    body += arrow("M240 470 V506")
    body += panel(40, 514, 880, 90, "再检查目录并清理父工作区", ["实际检查子目录与根工作区均不存在"], "#b45309")
    body += text(480, 652, "cancel 实测：读取 {} 次，剩余资源计数 {}，子目录删除 {}。".format(cancelled["reads"], cancelled["active_workers"], str(cancelled["scratch_removed"]).lower()), 19, "#0f766e", True)
    body += text(480, 690, "本图验证读取前取消；已经开始的阻塞调用需要自己的中断协议。", 17, "#475569")
    save("r06-cancel-lifecycle.svg", "取消是请求，join 才确认执行者退出", "读取前通过通道确定取消顺序，子作用域释放资源，父侧等待退出后再删除工作区。", 722, body)
