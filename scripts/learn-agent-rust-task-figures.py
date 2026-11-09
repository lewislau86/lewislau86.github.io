"""R12 figures derived from independent-process and filesystem evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / 'scripts/data/learn-agent-rust/r12-results.json').read_text())
    source = root / 'docs/public/learn-agent-rust/code/task-system'
    for name, digest in evidence['files_sha256'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('R12 evidence is stale; rerun verify-agent-tasks.py')
    rows = {row['name']: row for row in evidence['scenarios']}

    def successful(name):
        return [step['response'] for step in rows[name]['steps']
                if step['response'].get('status') == 'ok']

    chain = successful('new-process-chain')
    board = next(r for r in chain if len(r['board']['tasks']) == 3)['board']
    tasks = board['tasks']
    assert [t['id'] for t in tasks] == ['readme', 'check', 'guide']
    assert tasks[1]['depends_on'] == ['readme'] and tasks[2]['depends_on'] == ['check']
    body = text(480, 87, '箭头：前置完成后，后继才允许开始', 20, '#475569')
    for index, task in enumerate(tasks):
        x = 45 + index * 310
        body += panel(x, 124, 250, 140, task['id'],
                      ['状态 ' + task['status'], '前置 ' + (', '.join(task['depends_on']) or '无')],
                      '#0f766e' if not task['depends_on'] else '#2563eb')
        if index < 2:
            body += arrow('M{} 194 H{}'.format(x + 250, x + 302))
    views = [next(r for r in chain if r['revision'] == board['revision'])]
    for task in tasks[:-1]:
        views.append(next(r for r in chain if any(t['id'] == task['id'] and t['status'] == 'completed'
                                                 for t in r['board']['tasks'])))
    for index, r in enumerate(views):
        y = 340 + index * 65
        body += text(200, y, 'revision = {}'.format(r['revision']), 22, '#2563eb', True)
        body += text(598, y, 'ready = ' + (', '.join(r['ready']) or '空'), 22, '#0f766e', True)
    final = chain[-1]
    body += text(480, 572, '最终 revision={}：{} 个任务均完成，各尝试一次。'.format(
        final['revision'], len(final['board']['tasks'])), 20, bold=True)
    assert all(t['attempts'] == 1 and t['status'] == 'completed' for t in final['board']['tasks'])
    save('r12-task-dependencies.svg', '任务依赖决定谁先开始',
         '三个任务的依赖、可运行列表和版本来自 new-process-chain 实际响应。', 612, body)

    restart = successful('running-restart')
    running = next(r for r in restart if r['reconcile'])
    failed = next(r for r in restart if r['board']['tasks'] and r['board']['tasks'][0]['status'] == 'failed')
    retry = next(r for r in restart if r['board']['tasks'] and r['board']['tasks'][0]['status'] == 'pending'
                 and r['board']['tasks'][0]['attempts'] > 0)
    final = restart[-1]
    body = panel(70, 84, 820, 115, '新进程读取正式快照',
                 ['revision={} · running · attempts={}'.format(running['revision'], running['board']['tasks'][0]['attempts']),
                  'reconcile=' + ','.join(running['reconcile']) + '；不自动恢复为 Pending'], '#b45309')
    body += arrow('M165 199 V250')
    body += text(480, 230, '可信调用者先核对实际效果', 18, '#b45309')
    stages = [(failed, '显式 fail', '#b91c1c'), (retry, '显式 retry', '#2563eb'), (final, '再次 start', '#0f766e')]
    for index, (r, title, color) in enumerate(stages):
        task = r['board']['tasks'][0]
        x = 35 + index * 315
        body += panel(x, 258, 260, 166, title,
                      ['revision=' + str(r['revision']), task['status'], 'attempts=' + str(task['attempts'])], color)
        if index < 2:
            body += arrow('M{} 343 H{}'.format(x + 260, x + 308))
    limit = rows['retry-budget']['snapshot']['tasks'][0]
    body += text(480, 479, '同一业务 ID 的次数一直保留；Pending 不代表尚未开始过。', 20, bold=True)
    body += text(480, 522, '另一个场景：attempts={} / max_attempts={}，retry 返回 attempt_limit。'.format(
        limit['attempts'], limit['max_attempts']), 18, '#b45309')
    save('r12-restart-state.svg', '重启后保留状态，也保留已用次数',
         'running-restart 与 retry-budget 的实际状态迁移。失败与重试由可信调用者显式提交。', 560, body)

    def reopened(name):
        steps = rows[name]['steps']
        barrier = next(i for i, step in enumerate(steps) if step['label'] == 'kill barrier')
        return next(step['response'] for step in steps[barrier + 1:]
                    if step['label'] == 'show (new process)' and step['response'].get('status') == 'ok')

    old = reopened('crash-before-rename')
    new = reopened('crash-after-commit')
    body = panel(200, 82, 560, 140, '写候选 → sync_all → rename',
                 ['同目录替换 tasks.json', 'Unix 再同步父目录，然后才应答'], '#2563eb')
    body += arrow('M340 222 V260 H245 V294')
    body += arrow('M620 222 V260 H715 V294')
    body += panel(35, 304, 420, 200, '替换前终止并回收',
                  ['正式 revision={}'.format(old['revision']),
                   'readme={}#{}'.format(old['board']['tasks'][0]['status'], old['board']['tasks'][0]['attempts']),
                   '遗留 .tasks.pending', '读旧板；新保存被阻止'], '#b45309')
    body += panel(505, 304, 420, 200, '替换与目录同步后终止',
                  ['正式 revision={}'.format(new['revision']),
                   'readme={}#{}'.format(new['board']['tasks'][0]['status'], new['board']['tasks'][0]['attempts']),
                   '候选路径已被替换', '重启保留 Running，等待核对'], '#0f766e')
    body += text(480, 552, '两个检查点均真实终止子进程，再由新进程检查文件。', 20, bold=True)
    body += text(480, 592, '未模拟物理断电；committed 仅表示已越过 rename 边界。', 18, '#475569')
    save('r12-save-boundary.svg', '保存是否跨过替换边界，决定恢复时看见什么',
         'crash-before-rename 与 crash-after-commit 的独立进程读取结果；没有验证物理断电。', 632, body)
