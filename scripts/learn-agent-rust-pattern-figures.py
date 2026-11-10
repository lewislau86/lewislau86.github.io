"""Teaching schematic only: no invented measurements or runtime claims."""


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
    chapter_figures(text, panel, arrow, save_figure)


SCHEMES = {'D01': ['choose · 判断资料与步骤', 'read / observe · 补证据', 'generate · 生成产物', 'accept · 验收或停止'], 'D02': ['route · 白名单分类', 'extract · 结构化产物', 'gate · 字段与修订', 'render · 消费已验产物'], 'D03': ['dispatch · 三任务限并发二', 'JoinSet · 全部等待或取消', 'merge · 成员与修订', 'report · 确定顺序'], 'D04': ['plan · 修订与依赖', 'validate · 拒绝环与缺项', 'execute / observe · 账本', '发现成员 → 新版剩余计划'], 'D05': ['decompose · 输入决定成员', 'workers · 独立输入与汇总', 'handoff · 校验接收者', 'return · 明确归还控制'], 'D06': ['generate · 保留 baseline', 'evaluate · 固定规则', 'repair · 反馈绑定修订', '重新检查 → accept / 停止'], 'D07': ['prepare · 待办身份与修订', '澄清 / 编辑 / 审批', 'resume · 再验批准范围', 'finish · 本地完成状态'], 'D08': ['route / plan · 确定成员', 'parallel / merge · 当前证据', 'generate / evaluate / repair', 'approve / publish · 修订绑定']}


def chapter_figures(text, panel, arrow, save_figure):
    for lesson, labels in SCHEMES.items():
        body = text(480, 78, '输入与版本 → 执行 → 验收；失败在当前合同处停止', 18, '#475569')
        positions = [(30, 112), (495, 112), (495, 328), (30, 328)]
        for (x, y), label in zip(positions, labels):
            title, _, detail = label.partition(' · ')
            body += panel(x, y, 435, 156, title, [detail or '检查身份、修订与停止条件'], '#2563eb')
        body += arrow('M465 190 H490')
        body += arrow('M712 270 V320')
        body += arrow('M495 406 H470')
        body += text(480, 534, '示意图不表示耗时；真实轨迹与预算见章节保存输出。', 17, '#475569')
        save_figure(lesson.lower() + '-pattern-flow.svg', lesson + ' · 模式运行与验收',
                    '四组节点展示本章的实际控制结构；循环与拒绝的真实次序见 trace。不是模型性能测量。', 566, body)
