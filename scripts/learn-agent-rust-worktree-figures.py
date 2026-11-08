"""Generate R18 diagrams from verified real Git worktree experiments."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / "scripts/data/learn-agent-rust/r18-results.json").read_text())
    source = root / "docs/public/learn-agent-rust/code/worktree-isolation.rs"
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("R18 evidence is stale; rerun verify-agent-worktrees.py")
    rows = {row["name"]: row for row in evidence["scenarios"]}
    parallel = rows["parallel"]
    body = panel(30, 86, 900, 92, "宿主保管任务绑定", ["task + attempt + owner / epoch + base + branch + path"])
    body += arrow("M252 178 V223")
    body += arrow("M708 178 V223")
    body += panel(30, 232, 442, 150, "alpha-a1", ["README：startup=alpha", "独立 HEAD · 独立索引", "分支：codex/r18-alpha-a1"], "#2563eb")
    body += panel(488, 232, 442, 150, "beta-a1", ["README：startup=beta", "独立 HEAD · 独立索引", "分支：codex/r18-beta-a1"], "#0f766e")
    body += arrow("M251 382 V424 H480 V450")
    body += arrow("M709 382 V424 H480")
    body += panel(122, 460, 716, 106, "共享：repository/.git", ["对象库 · 普通分支引用 · worktree 登记", "主工作区 README 仍为 startup=cargo run"], "#b45309")
    body += text(480, 614, "实测：{} 个关联 worktree，{} 个因修改而保留的绑定。".format(parallel["linked"], parallel["retained"]), 20, bold=True)
    body += text(480, 651, "目录和索引隔离；进程、网络与文件访问权限仍由宿主控制。", 18)
    save("r18-workspace-binding.svg", "工作区隔离：分开文件与索引，保留共同历史",
         "两个任务各自使用目录与分支，共享 Git 对象库；并行修改不改变练习主目录。", 688, body)

    body = panel(160, 84, 640, 82, "核对任务、owner / epoch 与实际仓库", ["身份或路径不符 → 拒绝操作，保留现场"])
    gates = [
        ("写线程已经 join？", "未 join → busy", "#2563eb"),
        ("文件与索引没有额外内容？", "包括未跟踪与忽略文件 → changes", "#0f766e"),
        ("目标干净，HEAD 从 base 派生并进入 main？", "冲突 / 历史改变 / 未合入 → 保留", "#b45309"),
    ]
    for index, (heading, detail, color) in enumerate(gates):
        y = 208 + index * 136
        body += arrow("M480 {} V{}".format(y - 42, y - 8))
        body += panel(90, y, 780, 94, heading, [detail], color)
    body += arrow("M480 574 V612")
    body += panel(160, 622, 640, 96, "请求 Git 移除目录，不加 --force", ["成功 → Removed；Git 拒绝 → git_refused", "分支引用保留，回收方法不执行合并"], "#0f766e")
    body += text(480, 764, "clean：回收 {} 个；unmerged：保留 {} 个；locked：保留 {} 个。".format(
        rows["clean"]["removed"], rows["unmerged"]["retained"], rows["locked"]["retained"]), 20, bold=True)
    save("r18-retirement-gates.svg", "回收顺序：先证明可以删除，再交给 Git 检查",
         "回收依次检查身份、线程、文件和提交关系，只移除满足条件的目录。", 802, body)

    conflict = rows["conflict"]
    body = panel(34, 85, 430, 128, "执行阶段：alpha", ["独立目录写入 startup=alpha", "提交保留在 alpha 分支"], "#2563eb")
    body += panel(496, 85, 430, 128, "执行阶段：beta", ["独立目录写入 startup=beta", "提交保留在 beta 分支"], "#0f766e")
    body += arrow("M249 213 V257 H480 V291")
    body += arrow("M711 213 V257 H480")
    body += panel(142, 300, 676, 104, "集成阶段：先接收 alpha，再合并 beta", ["同一行出现逻辑冲突，主索引为 UU README.md"], "#b91c1c")
    body += arrow("M480 404 V446")
    body += panel(142, 456, 676, 106, "保留冲突与两份成果供评审", ["关联 worktree：{} · 明确保留：{} · 回收：{}".format(
        conflict["linked"], conflict["retained"], conflict["removed"]), "不自动选择一方，不删除分支或目录"], "#b45309")
    body += text(480, 610, "隔离解决修改归属；最终内容仍由集成与评审确定。", 21, bold=True)
    save("r18-isolation-and-integration.svg", "执行可以并行，成果仍需集成",
         "真实 Git 实验中，两个独立提交在合并时产生冲突，主索引和两个工作区全部保留。", 650, body)
