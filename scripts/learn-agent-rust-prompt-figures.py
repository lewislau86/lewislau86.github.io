"""R10 assembly diagrams and actual input/cache evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r10-results.json").read_text())
    package = root / "docs/public/learn-agent-rust/code/system-prompts"
    for name, expected in evidence["source_sha256"].items():
        if hashlib.sha256((package / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Stale R10 evidence; run verify-agent-prompts.py")
    rows = {row["scenario"]: row for row in evidence["scenarios"]}
    body = panel(40, 85, 400, 142, "应用选择的控制信息", ["policy/core · 版本与摘要", "工具注册表 · 环境白名单"], "#2563eb")
    body += panel(520, 85, 400, 142, "本次选择的参考数据", ["skill/startup-guide", "memory/project · 版本与摘要"], "#b45309")
    body += arrow("M240 227 V275") + arrow("M720 227 V275")
    body += panel(40, 285, 400, 116, "system 消息", ["策略 + 工具目录 + 环境", "组装器固定，历史中禁止混入 system"], "#2563eb")
    body += panel(520, 285, 400, 116, "human / reference_data", ["用 JSON 保留资料原文和来源", "资料内容不会创建新的消息角色"], "#b45309")
    body += arrow("M240 401 V460") + arrow("M720 401 V460")
    body += panel(40, 470, 880, 108, "再追加原始对话历史 → 完整模型输入", ["保留 user / assistant / tool 顺序与调用 ID；组装结果不追加回历史。"], "#0f766e")
    body += text(480, 620, "示意图：角色与来源由应用确定；文字包装本身不能保证模型遵循策略。", 17, "#475569")
    save("r10-input-sources.svg", "一次模型输入，分别保留控制信息与参考来源", "策略、注册表和环境进入 system，选中的知识进入独立参考数据消息，再接入原始历史。", 652, body)

    normal = rows["normal"]
    inputs = normal["state"]["inputs"]
    body = ""
    for i, item in enumerate(inputs):
        x = 40 if i == 0 else 520
        role_names = {"system": "system", "human": "human", "ai": "assistant", "tool": "tool"}
        roles = [role_names[m["message_type"]] for m in item["messages"]]
        body += panel(x, 90, 400, 132, "第 {} 次真实模型调用".format(i + 1), [
            "{} 条消息 · {} 字节".format(len(roles), item["serialized_bytes"]),
            "本地前缀缓存：" + ("命中" if item["cache_hit"] else "未命中"),
        ], "#2563eb" if i == 0 else "#0f766e")
        for j, role in enumerate(roles):
            y = 252 + j * 46
            body += '<rect x="{}" y="{}" width="400" height="36" rx="8" fill="#fff" stroke="#cbd5e1"/>'.format(x, y)
            suffix = " · 策略/目录/环境" if j == 0 else " · 参考资料" if j == 1 else " · 用户任务" if j == 2 else " · read-1"
            body += text(x + 200, y + 25, role + suffix, 18, "#475569")
    body += text(480, 530, "前缀摘要相同；工具往返后历史增长，完整输入摘要发生变化。", 19, "#0f766e")
    body += text(480, 569, "数据：normal 的实际 inputs；字节指序列化 Message 列表的 UTF-8 长度。", 17, "#475569")
    save("r10-two-turn-inputs.svg", "第二轮重用前缀，同时看到新的工具结果", "两轮的消息数量、字节数和缓存状态来自真实图执行记录。", 602, body)

    body = text(480, 95, "同一 Assembler 中组装前后输入的确定性对照", 20, "#475569")
    for i, (name, label) in enumerate([("repeat", "相同来源，仅调换选择顺序"), ("memory-update", "发布新版记忆并更新 pin"),
                                       ("environment-change", "切换环境语言"), ("tool-change", "关闭读取工具")]):
        probe = rows[name]["probe"]
        y = 125 + i * 78
        body += panel(40, y, 880, 68, label, [], "#0f766e" if probe["cache_hit"] else "#b45309")
        body += text(480, y + 56, "完整输入相同：{} · 前缀缓存命中：{}".format(str(probe["same_input"]).lower(), str(probe["cache_hit"]).lower()), 17, "#475569")
    denied = rows["knowledge-injection"]["state"]
    body += panel(40, 465, 880, 112, "知识要求写入时，执行器仍检查权限", [
        "写入请求 {} 次 · 实际产生摘要文件：{}".format(denied["write_attempts"], "是" if rows["knowledge-injection"]["summary_exists"] else "否"),
        "脚本模型故意提出越权动作，应用返回 permission_denied。"], "#b91c1c")
    body += text(480, 619, "缓存用于本进程的组装前缀；这不是 provider 缓存，也不是模型抗注入评估。", 17, "#475569")
    save("r10-change-and-permission.svg", "输入变化使前缀失效，执行权限单独核对", "四次前后组装对照与越权写入场景均来自实际运行记录。", 650, body)
