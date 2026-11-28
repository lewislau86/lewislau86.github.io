"""Part five overview schematic (agent-pattern-selection.svg); the per-chapter D01–D08 figures come from
learn-agent-rust-pattern-adk-figures.py. Teaching schematic only: no invented measurements or runtime claims."""


def generate(root, text, panel, arrow, save_figure):
    cards = [
        ('先建立最小基线', ['一次调用够用吗？步骤已知吗？', '单次调用 / 固定工作流 / 有界循环'], '#2563eb'),
        ('已知步骤与输入类别', ['提示链：抽取 → 校验 → 生成', '路由：分类 → 专门处理 / 兜底'], '#2563eb'),
        ('独立子问题：并行归并', ['同一修订 → 独立检查 → 汇总', '约束成员、失败策略与结果冲突'], '#0f766e'),
        ('新观察：规划与重规划', ['计划 → 执行 → 观察 → 修订', '保留已确认效果与累计预算'], '#0f766e'),
        ('动态分工与控制权', ['协调者分派 → 工作者返回', '交接：明确下一轮由谁主导'], '#7c3aed'),
        ('明确反馈：评估与修复', ['生成 → 检查 → 有限修复', '候选版本、固定准则与停止上限'], '#7c3aed'),
        ('缺信息或授权：人工介入', ['澄清 / 编辑 / 审批 → 校验恢复', '批准绑定展示过的动作与修订'], '#b45309'),
        ('按需求组合，再验证接缝', ['选择必要模式，统一全局账本', '分别验收流程、效果与模型质量'], '#b45309'),
    ]
    body = text(480, 78, '先确定控制权、输入输出与停止条件，再增加结构', 18, '#475569')
    for i, (heading, lines, color) in enumerate(cards):
        x, y = 30 + (i % 2) * 465, 108 + (i // 2) * 180
        body += panel(x, y, 435, 156, heading, lines, color)
    body += text(480, 862, '控制结构示意 · 各章附独立 Rust 工程与故障复验', 18, '#475569')
    save_figure('agent-pattern-selection.svg', '从任务结构选择 Agent 设计模式',
                '八组任务结构的教学示意，包含基线、提示链路由、并行、规划、协调交接、评估修复、人工介入与组合。不是性能实验。',
                892, body)
