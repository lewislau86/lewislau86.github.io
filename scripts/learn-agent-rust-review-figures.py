"""Generate teaching schematics and P06 data figures; upstream images stay unchanged."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / 'scripts/data/learn-agent-rust/p06-results.json').read_text())
    for name, expected in evidence['files_sha256'].items():
        path = root / 'docs/public/learn-agent-rust/code/agent-rsi' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('P06 source stale: run verify-agent-rsi.py')
    for name, expected in evidence['outputs_sha256'].items():
        path = root / 'docs/public/learn-agent-rust/outputs' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('P06 outputs stale: run verify-agent-rsi.py')
    rows = {r['scenario']: r for r in evidence['scenarios'] if r['order_seed'] == 1}

    body = panel(45, 90, 870, 120, '外层：修改产生改进的方法（研究概念）', ['候选如何生成 · 失败如何诊断 · 搜索额度如何分配'], '#b45309')
    body += arrow('M480 210 V257')
    body += panel(95, 265, 770, 150, '内层：选择更好的任务策略（本章已运行）', ['有限候选 → 开发 / 验证评分 → 接受或拒绝', '固定门控、固定预算，保留版本谱系'], '#0f766e')
    body += arrow('M865 340 H910 V470 H480 V490')
    body += panel(95, 500, 770, 110, '宿主边界：独立验收与发布', ['评分合同与权限不由本轮候选改写'])
    body += text(480, 655, '图为概念分层；本实验没有运行外层元改进。', 19, '#475569')
    save('p06-improvement-levels.svg', '任务变好，与更会寻找改进，是两个层次', '外层修改改进方法，内层修改任务策略，宿主维护独立验收与发布。', 695, body)

    body = text(480, 95, '候选实际评分；开发与验证各四题，最终测试未参与选择', 19, '#475569')
    for i, row in enumerate(rows['normal']['candidates']):
        y = 130 + i * 138
        color = '#b45309' if row['policy'] == 'Memorize' else '#0f766e'
        body += panel(45, y, 220, 104, row['policy'], ['仅看左列会误判' if row['policy'] == 'Memorize' else '以验证增益决定'], color)
        for x, key, label, fill in [(300, 'dev', '开发', '#2563eb'), (615, 'validation', '验证', color)]:
            body += text(x + 130, y + 28, f'{label} {row[key]}/4', 21, fill, True)
            body += f'<rect x="{x}" y="{y+50}" width="260" height="26" rx="5" fill="#e2e8f0"/>'
            body += f'<rect x="{x}" y="{y+50}" width="{row[key]*65}" height="26" rx="5" fill="{fill}"/>'
    body += text(480, 590, 'Memorize：开发满分，验证仍为 1/4，门控拒绝。', 20, '#b45309')
    save('p06-candidate-scores.svg', '用实际反例揭开“开发满分”的假象', '实际正常场景中 Trim 开发三验证二，Memorize 开发四验证一，Robust 两区均四。', 635, body)

    body = panel(45, 90, 870, 104, '候选提案', ['策略 · 父修订 · 评分器标志 · 权限标志 · 固定成本'])
    body += arrow('M480 194 V240')
    body += panel(45, 248, 405, 170, '评估前检查', ['父修订一致 · 评分器未变', '权限不扩大 · 成本合法', '搜索额度足够'], '#b45309')
    body += arrow('M450 330 H505')
    body += panel(520, 248, 395, 170, '扣额度，再评分', ['开发不退步', '验证严格提高', '没有增益也计一次尝试'], '#0f766e')
    body += arrow('M718 418 V460 H480 V482')
    body += panel(95, 490, 770, 110, '通过后发布；失败保留当前版本', ['最终测试只在选择结束后审计一次'])
    body += text(480, 645, '有限策略与结构化标志的测试，不是恶意代码检测器。', 19, '#475569')
    save('p06-promotion-gates.svg', '先检查边界，再判断候选是否有增益', '宿主先检查修订与能力，再按固定额度运行开发和验证评分，符合门控才发布。', 685, body)

    normal, rollback = rows['normal'], rows['rollback']
    panels = [
        (45, 'revision-0', ['已知基线 Baseline', f'最终测试 {normal["baseline_test"]}/{normal["test_cases"]}']),
        (350, 'revision-1', ['rollback 发布 Robust', f'候选验证 {rollback["candidates"][0]["validation"]}/4']),
        (655, '告警后回退', ['rollback 指回基线', f'最终测试 {rollback["selected_test"]}/{rollback["test_cases"]}']),
    ]
    body = ''
    for i, (x, heading, lines) in enumerate(panels):
        body += panel(x, 115, 260, 155, heading, lines, '#b45309' if i == 2 else '#0f766e')
        if i < 2:
            body += arrow(f'M{x+260} 195 H{x+295}')
    body += panel(45, 325, 870, 140, '读取 CURRENT 后，按实际版本重新验收', ['修订文件保持不变；回退替换的是发布指针', '恢复旧版本不会撤销已经发生的外部业务效果'])
    body += text(480, 515, '同一次 rollback：发布 Robust，注入告警，最后审计 Baseline。', 18, '#475569')
    save('p06-release-rollback.svg', '回滚动作与回滚后的能力分别记录', '回滚场景先发布验证四题均通过的 Robust，再注入告警，指针回到 Baseline，最终审计为六题通过二题。', 560, body)

    body = ''
    levels = [
        ('受控输入', '脚本模型 / 故障夹具：核对控制规则', '#2563eb'),
        ('真实边界', '文件 / 线程 / stdio / 数据库：核对实际效果', '#0f766e'),
        ('恢复与重放', '在指定故障窗口重启，核对身份与累计状态', '#0f766e'),
        ('跨机制集成', '沿同一用户任务，核对模块之间的接缝', '#b45309'),
        ('真实模型与生产', '独立任务验收、成本、长期负载与事故恢复', '#b45309'),
    ]
    for i, (heading, line, color) in enumerate(levels):
        y = 85 + i * 125
        body += panel(45, y, 870, 95, heading, [line], color)
        if i < len(levels)-1:
            body += arrow(f'M480 {y+95} V{y+117}')
    body += text(480, 750, '概念检查图：上层证据不自动推出下一层通过，也不构成难度排名。', 18, '#475569')
    save('review-evidence-layers.svg', '每项成功，都要指出它跨过了哪条真实边界', '受控输入、真实效果、恢复、集成和生产分别需要证据，不以一项通过替代其他项。', 795, body)

    body = ''
    steps = [('先预测', '写下会发生什么'), ('再运行', '核对轨迹与产物'), ('造反例', '只破坏一个条件'), ('说边界', '结论到哪里为止'), ('做迁移', '换业务后如何判断')]
    for i, (heading, line) in enumerate(steps):
        y = 88 + i * 116
        body += panel(95, y, 770, 90, heading, [line], '#0f766e' if i in (1, 4) else '#2563eb')
        if i < len(steps)-1:
            body += arrow(f'M480 {y+90} V{y+109}')
    body += text(480, 735, '“理解”表现为能解释反例、设计验证，并在新问题中作出有依据的选择。', 18, '#475569')
    save('review-learning-chain.svg', '让章节成为一次可迁移的推理练习', '先预测，再实验，改变单一条件构造反例，界定边界，再把机制迁移到新的业务问题。', 780, body)

    body = panel(45, 100, 260, 150, '一手资料', ['日期与版本', '影响哪些章节'])
    body += arrow('M305 176 H343')
    body += panel(350, 100, 260, 150, '迁移假设', ['哪个旧合同会失效？', '保留基线和反例'], '#b45309')
    body += arrow('M610 176 H648')
    body += panel(655, 100, 260, 150, '隔离验收', ['相同任务与额度', '正常 + 故障路径'], '#0f766e')
    body += arrow('M785 250 V315 H480 V348')
    body += panel(95, 356, 770, 135, '进入课程基线', ['代码、锁文件、输出、配图、文档与学习包共同更新', '没有运行的迁移，明确标为未验收'])
    body += text(480, 548, '追踪技术的目标：更新判断依据，并保留可复现的旧证据。', 19, '#475569')
    save('review-technology-migration.svg', '新技术经过对照实验，再成为可教学的实现', '查阅资料，提出迁移假设，在隔离实验中验证，然后统一更新课程基线。', 590, body)
