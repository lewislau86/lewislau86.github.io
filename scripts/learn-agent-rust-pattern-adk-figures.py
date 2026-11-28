"""Part five (design patterns) diagrams for chapters migrated to ADK-Rust 3.0, generated from verified evidence."""
import hashlib
import json

SLUGS = {"D01": "pattern-selection", "D02": "prompt-chaining-routing", "D03": "parallel-decomposition", "D04": "plan-execute-replan",
         "D05": "orchestrator-workers-handoffs",
         "D06": "evaluator-reflection",
         "D07": "human-in-the-loop",
         "D08": "pattern-composition"}


def evidence(root, lesson):
    data = json.loads((root / f"scripts/data/learn-agent-rust/{lesson.lower()}-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code" / SLUGS[lesson]
    for filename, expected in data["source_sha256"].items():
        source = package / filename if (package / filename).exists() else root / "scripts" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Stale {lesson} evidence; run verify-agent-patterns-adk.py --lesson {lesson}")
    return {r["name"]: r for r in data["scenarios"]}


def d01(root, text, panel, arrow, save):
    rows = evidence(root, "D01")
    columns = [
        ("单次调用", "一个 LlmAgent，无工具", ["single", "single-partial"], "#2563eb"),
        ("固定工作流", "SequentialAgent：读 → 读 → 写", ["workflow", "workflow-new-member", "workflow-missing", "workflow-silent"], "#0f766e"),
        ("自主循环", "LlmAgent + read_file", ["adaptive", "forbidden", "budget"], "#b45309"),
    ]
    body = ""
    for index, (title, how, names, color) in enumerate(columns):
        x = 30 + index * 310
        body += panel(x, 80, 290, 96, title, [how], color)
        for row_index, name in enumerate(names):
            row = rows[name]
            y = 196 + row_index * 112
            verdict = row["verdict"].replace("rejected:", "未通过：").replace("accepted", "通过")
            body += panel(x, y, 290, 104, name, ["模型调用 {} 次，读 {} 个文件".format(
                row["model_calls"], len([r for r in row["reads"].strip("[]").split(",") if r])), verdict], color)
    body += text(480, 660, "验收看报告是否引用了根 README 列出的每个成员；调用次数来自替身模型。", 17, "#475569")
    save("d01-pattern-flow.svg", "同一个任务，三种结构",
         "同一个任务的三种结构：单次调用一次请求、资料由用户给全；固定工作流按代码写好的步骤读文件，多出的成员读不到；自主循环由模型按读到的内容补读，路径检查和调用上限由宿主守住。", 690, body)


def d02(root, text, panel, arrow, save):
    rows = evidence(root, "D02")
    routers = [
        ("LlmConditionalAgent", ["模型回标签，按包含匹配", "substring-trap → " + rows["substring-trap"]["route"]], "#2563eb"),
        ("ConditionalAgent", ["代码按文件名判断（嵌套两层）", "路由不调用模型"], "#0f766e"),
        ("DecisionAgent", ["选项 + 置信度门槛 0.6", "low-confidence → " + rows["low-confidence"]["route"]], "#b45309"),
    ]
    body = ""
    for index, (title, lines, color) in enumerate(routers):
        x = 30 + index * 310
        body += panel(x, 80, 290, 130, title, lines, color)
        body += arrow("M{} 210 L175 252".format(x + 145))
    steps = [
        ("抽取（output_schema）", ["missing-field、substring-trap", "重试用完，以错误结束"], "#475569"),
        ("质量门（CustomAgent）", ["文件、修订、类别都对？", "stale：" + rows["stale"]["gate"]], "#b91c1c"),
        ("写报告", ["读 {artifact}", "readme / cargo：写出报告"], "#0f766e"),
    ]
    for index, (title, lines, color) in enumerate(steps):
        x = 30 + index * 310
        body += panel(x, 260, 290, 130, title, lines, color)
        if index:
            body += arrow("M{} 325 H{}".format(x - 20, x - 2))
    body += text(480, 430, "SequentialAgent 串起一条处理链；escalate 或错误都会让链停在那一步。unknown、low-confidence、rule-router-other 进兜底。", 16, "#475569")
    save("d02-pattern-flow.svg", "路由进入处理链，每一步只消费检查过的产物",
         "文件先经路由进入对应的处理链：模型标签按包含匹配、代码按文件名、类型化决定带置信度门槛；链里抽取受 schema 约束，质量门比对修订号，通过才写报告。", 460, body)


def d03(root, text, panel, arrow, save):
    rows = evidence(root, "D03")
    body = ""
    for index, member in enumerate(["config", "deps", "docs"]):
        x = 200 + index * 200
        body += panel(x, 84, 180, 106, member + "_checker", ["写 check_" + member], "#2563eb")
        body += arrow("M{} 190 V256".format(x + 90))
    body += text(480, 70, "ParallelAgent：同时运行，peak_concurrent = " + rows["normal"]["peak_concurrent"], 16, "#2563eb", True)
    body += panel(20, 80, 160, 110, "分支出错", ["兄弟分支做完", "再整体报错"], "#b91c1c")
    body += panel(780, 80, 160, 110, "分支上报", ["立刻停下", "其他分支"], "#b45309")
    body += panel(200, 264, 560, 176, "merge（CustomAgent）", ["按成员顺序读三个键，核对成员与修订",
                  "stale：" + rows["stale"]["outcome"], "missing：" + rows["missing"]["outcome"],
                  "key-collision：" + rows["key-collision"]["outcome"]], "#0f766e")
    body += text(480, 470, "normal 与 reverse 完成顺序相反，报告指纹相同：" + rows["normal"]["report_sha"], 16, "#475569")
    save("d03-pattern-flow.svg", "同时检查，按成员归并",
         "三个检查者由 ParallelAgent 同时运行，各写自己的状态键；分支出错时等兄弟分支做完再报错，分支上报时立刻停下其他分支；归并逐个核对成员与修订，按成员顺序写报告。", 500, body)


def d04(root, text, panel, arrow, save):
    rows = evidence(root, "D04")
    left = [
        ("规划者（LlmAgent）", ["提出完整的新计划", "write_plan / exit_loop"], "#2563eb"),
        ("应用检查", ["修订号 = 当前 + 1", "已完成步骤一个不少"], "#b45309"),
        ("执行者（CustomAgent）", ["执行下一个待办步骤", "结果记进账本"], "#0f766e"),
    ]
    body = text(240, 72, "LoopAgent：规划—执行—重规划", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(left):
        y = 90 + index * 128
        body += panel(30, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M240 {} V{}".format(y - 18, y - 2))
    body += text(240, 488, "discover：修订 " + rows["discover"]["revisions"].strip("[]") + "，账本 3 条", 15, "#475569")
    body += text(240, 512, "missing-file → " + rows["missing-file"]["stop"] + "；stuck → " + rows["stuck"]["stop"], 15, "#475569")
    right = [
        ("计划模式", ["只读调查；改文件被拒绝"], "#2563eb"),
        ("exit_plan_mode", ["先问人（每次都问）", "再检查步骤 id 与依赖"], "#b45309"),
        ("下一轮对话：询问模式", ["默认进询问模式", "改文件时再问一次人"], "#0f766e"),
    ]
    body += text(720, 72, "adk-harness：计划模式（Beta）", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(right):
        y = 90 + index * 128
        body += panel(510, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M720 {} V{}".format(y - 18, y - 2))
    body += text(720, 488, "plan-mode-approved：写出文件 = " + rows["plan-mode-approved"]["file_written"], 15, "#475569")
    body += text(720, 512, "rejected / invalid：模式不变，写出文件 = no", 15, "#475569")
    save("d04-pattern-flow.svg", "计划由谁提出、检查、批准、执行",
         "左边是规划—执行循环：规划者提出计划、应用检查、执行者执行并记账，读到新文件就重规划；右边是计划模式：只读调查、提交计划、人批准、步骤检查通过后，下一轮对话切到询问模式，改文件时再问一次人。", 540, body)


def d05(root, text, panel, arrow, save):
    rows = evidence(root, "D05")
    left = [
        ("lead（协调者）", ["按成员清单派出工作者", "拿回结果，接着汇总"], "#2563eb"),
        ("member_check × 成员数", ["每个成员一次委派（AgentTool）", "同时最多 2 个；isolated 时看不到 lead 的状态"], "#0f766e"),
        ("执行回执", ["每次委派一条记录", "失败、预算、中断都留在这里"], "#475569"),
    ]
    body = text(240, 72, "委派（Delegate）：结果交回", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(left):
        y = 90 + index * 128
        body += panel(30, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M240 {} V{}".format(y - 18, y - 2))
    three = rows["three"]
    body += text(240, 488, "three：工作者 " + three["workers"].strip("[]") + "，同时进行 " + three["peak"], 15, "#475569")
    body += text(240, 512, "budget → " + rows["budget"]["stop"].split(":", 1)[1], 15, "#475569")
    right = [
        ("lead 发现许可证问题", ["先写交接说明（会话状态）", "再 transfer_to_agent → license"], "#2563eb"),
        ("license（专员）", ["只看用户的话和交接说明", "下一轮用户消息也由它回答"], "#b45309"),
        ("不能“交回” lead", ["license → lead 会让关系成环", "编译时就被拒绝"], "#475569"),
    ]
    body += text(720, 72, "交接（Handoff）：控制权转移", 18, "#b45309", True)
    for index, (title, lines, color) in enumerate(right):
        y = 90 + index * 128
        body += panel(510, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M720 {} V{}".format(y - 18, y - 2))
    handoff = rows["handoff"]
    body += text(720, 488, "handoff：第一轮 " + handoff["turn1"] + "，第二轮 " + handoff["turn2"], 15, "#475569")
    body += text(720, 512, "cycle → " + rows["cycle"]["stop"].split(":", 1)[1], 15, "#475569")
    save("d05-pattern-flow.svg", "委派交回结果，交接转移控制权",
         "左边是委派：lead 按清单派出工作者，结果交回 lead 汇总，每次委派记进执行回执；右边是交接：lead 先把交接说明写进会话状态，再把控制权交给 license，下一轮也由 license 回答，license 不能再交回 lead。", 540, body)


def d06(root, text, panel, arrow, save):
    rows = evidence(root, "D06")
    left = [
        ("写作者（LlmAgent）", ["按反馈里没通过的规则改稿", "output_key → draft"], "#2563eb"),
        ("评估者（固定规则）", ["正文非空、有来源、来源在允许列表", "不看写作者的“已自查”"], "#b45309"),
        ("通过 / 无进展 → 上报", ["没通过：回到写作者再改一轮", "最多 3 轮；第一稿留作基线"], "#0f766e"),
    ]
    body = text(240, 72, "LoopAgent：生成—评估—修复", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(left):
        y = 90 + index * 128
        body += panel(30, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M240 {} V{}".format(y - 18, y - 2))
    body += text(240, 488, "new-error：" + rows["new-error"]["checks"].strip("[]").replace(",", " → "), 15, "#475569")
    body += text(240, 512, "no-progress → " + rows["no-progress"]["stop"] + "；never-good → " + rows["never-good"]["stop"], 15, "#475569")
    right = [
        ("工具失败", ["read_file 路径写错"], "#2563eb"),
        ("反思提示替换结果", ["同一参数最多 2 次", "整次运行最多 3 次"], "#b45309"),
        ("超过上限", ["原始错误交给模型"], "#475569"),
    ]
    body += text(720, 72, "adk-retry-reflect：工具失败后的反思", 18, "#b45309", True)
    for index, (title, lines, color) in enumerate(right):
        y = 90 + index * 128
        body += panel(510, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M720 {} V{}".format(y - 18, y - 2))
    body += text(720, 488, "tool-retry → " + rows["tool-retry"]["outcome"] + "；exhausted → " + rows["tool-retry-exhausted"]["outcome"], 15, "#475569")
    body += text(720, 512, "wandering：第 4 次失败不再有提示", 15, "#475569")
    save("d06-pattern-flow.svg", "评估修复循环与工具失败的反思",
         "左边是 LoopAgent 里的生成—评估—修复：写作者写稿，评估者按固定规则检查，通过或没有进展就上报，最多 3 轮；右边是 adk-retry-reflect：工具失败时用反思提示替换结果，同一参数最多 2 次、整次运行最多 3 次，超过后原始错误交给模型。", 540, body)


def d07(root, text, panel, arrow, save):
    rows = evidence(root, "D07")
    left = [
        ("步骤 1：运行到发布", ["writer → version_check → publisher", "发布调用被挂起，运行结束"], "#2563eb"),
        ("步骤 2：审批人决定", ["从 SQLite 读出等待中的请求", "批准 / 拒绝 / 改参数批准"], "#b45309"),
        ("步骤 3：恢复", ["从 publisher 这一步继续", "writer 不再运行"], "#0f766e"),
    ]
    body = text(240, 72, "挂起—决定—恢复（每步可以是独立进程）", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(left):
        y = 90 + index * 128
        body += panel(30, y, 420, 108, title, lines, color)
        if index:
            body += arrow("M240 {} V{}".format(y - 18, y - 2))
    body += text(240, 488, "approve：写作者运行 " + rows["approve"]["writer_runs"] + " 次，发布 " + rows["approve"]["published"].strip("[]"), 15, "#475569")
    body += text(240, 512, "clarify：问人以后从头再来，写作者运行 " + rows["clarify"]["writer_runs"] + " 次", 15, "#475569")
    right = [
        ("批准以后，需求变了", ["用户：“改成 3.1 再发”"], "#2563eb"),
        ("不撤回：旧批准被用掉", ["恢复挂起的调用，发布旧内容"], "#b91c1c"),
        ("先撤回：改成拒绝", ["了结挂起的一步，再写 3.1、再批准"], "#0f766e"),
    ]
    body += text(720, 72, "批准绑定调用，不绑定意图", 18, "#b45309", True)
    for index, (title, lines, color) in enumerate(right):
        y = 90 + index * 128
        body += panel(510, y, 420, 108, title, lines, color)
        if index == 1:
            body += arrow("M720 {} V{}".format(y - 18, y - 2))
    # 两种做法都从“需求变了”分出来
    body += arrow("M930 145 H950 V401 H934")
    body += text(720, 488, "changed-mind → 发布 " + rows["changed-mind"]["published"].strip("[]"), 15, "#475569")
    body += text(720, 512, "changed-mind-revoked → 发布 " + rows["changed-mind-revoked"]["published"].strip("[]"), 15, "#475569")
    save("d07-pattern-flow.svg", "挂起、决定、恢复，以及撤回旧批准",
         "左边是三个进程：第一个运行到发布并挂起，第二个读出等待中的请求并记下决定，第三个从发布这一步恢复，写作者不再运行；右边是批准以后需求变了：不撤回时旧批准被用掉、发布旧内容，先撤回再重新请求才发布新内容。", 540, body)


def d08(root, text, panel, arrow, save):
    rows = evidence(root, "D08")
    stages = [
        ("checks（ParallelAgent）", ["deps、docs 两个检查者同时运行"], "#2563eb"),
        ("merge（CustomAgent）", ["成员、修订对得上才写证据", "否则上报，整个流程停下"], "#b45309"),
        ("refine（LoopAgent）+ 接缝适配", ["写作者 ↔ 评估者，最多 3 轮", "收住内层 escalate，只交出结果"], "#0f766e"),
        ("publisher（需人批准）", ["挂起 → 批准 → 恢复 → 发布"], "#7c3aed"),
    ]
    body = text(480, 64, "SequentialAgent：每次运行一个预算", 18, "#2563eb", True)
    for index, (title, lines, color) in enumerate(stages):
        y = 82 + index * 160
        body += panel(30, y, 540, 128, title, lines, color)
        if index:
            body += arrow("M300 {} V{}".format(y - 30, y - 2))
    notes = [
        ("naive", "不加适配"),
        ("normal", "加适配，批准后发布"),
        ("stale-branch", "归并发现旧修订"),
        ("never-accepted", "3 轮没有合格稿"),
        ("branch-failed", "依赖检查出错"),
        ("budget", "预算只够 4 次调用"),
    ]
    for index, (name, label) in enumerate(notes):
        y = 82 + index * 108
        row = rows[name]
        body += panel(600, y, 330, 100, name, [label + "：" + row["stop"]], "#475569")
    save("d08-pattern-flow.svg", "组合发布流程与它的接缝",
         "左边是组合起来的发布流程：并行检查、归并、带接缝适配的修复循环、需批准的发布，每次运行共用一个预算；右边是主要场景停在哪里，不加适配时评估者的上报让整个流程在发布前结束。", 740, body)


def generate(root, text, panel, arrow, save, lesson=None):
    for name, draw in {"D01": d01, "D02": d02, "D03": d03, "D04": d04, "D05": d05, "D06": d06, "D07": d07, "D08": d08}.items():
        if lesson in (None, name):
            draw(root, text, panel, arrow, save)
