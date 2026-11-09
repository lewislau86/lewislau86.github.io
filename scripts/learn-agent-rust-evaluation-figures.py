"""P03 diagrams generated from actual loopback HTTP and independent task grades."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    data = json.loads((root / 'scripts/data/learn-agent-rust/p03-results.json').read_text())
    source = root / 'docs/public/learn-agent-rust/code/model-evaluation'
    for name, digest in data['files_sha256'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('P03 evidence stale: run verify-agent-evaluation.py')
    rows = {r['scenario']:r for r in data['evidence']['protocol']}
    normal, wrong = rows['normal'], rows['wrong-answer']
    assert normal['adapter_ok'] and wrong['adapter_ok'] and not wrong['grade']['task_pass']
    body = panel(32, 90, 270, 138, '① HTTP 与适配契约', ['状态 · 正文 · 身份', '工具形状 · 结束原因'])
    body += arrow('M302 159 H337')
    body += panel(347, 90, 270, 138, '② 宿主边界', ['工具名 · 参数 · 权限', '调用 ID · 配对 · 预算'], '#0f766e')
    body += arrow('M617 159 H652')
    body += panel(662, 90, 266, 138, '③ 独立任务验收', ['标签 · 输出字段', '实际读取是否发生'], '#b45309')
    body += text(480, 284, '同一次任务，三个不同问题。', 23, bold=True)
    for x, label in [(194, '场景'), (450, '适配通过'), (644, '实际读取'), (820, '任务完成')]:
        body += text(x, 344, label, 20, bold=True)
    for i, name in enumerate(['normal', 'wrong-answer', 'false-finish', 'path-escape']):
        r = rows[name]
        y = 402 + i * 64
        body += '<rect x="32" y="{}" width="896" height="46" rx="7" fill="{}"/>'.format(y-30, '#e2e8f0' if i%2==0 else '#fff')
        body += text(194, y, name, 19)
        body += text(450, y, '是' if r['adapter_ok'] else '否', 22, '#2563eb', True)
        body += text(644, y, str(r['state']['reads']), 22, '#0f766e', True)
        body += text(820, y, '是' if r['grade']['task_pass'] else '否', 22, '#b45309', True)
    body += text(480, 674, 'HTTP 200、合法回答与任务完成，分别保留证据。', 20, '#475569')
    save('p03-validation-layers.svg', '协议能接收，任务还要验收',
         '四个实际本地 HTTP 场景区分适配通过、真实读取与独立任务完成。', 720, body)

    wire = normal['wire']
    assert len(wire) == 2
    call = wire[0]['response']['choices'][0]['message']['tool_calls'][0]
    returned = [m for m in wire[1]['request']['messages'] if m['role']=='tool'][0]
    assert call['id'] == returned['tool_call_id']
    body = panel(30, 82, 420, 103, 'Rust 宿主 · 两库循环', ['system 策略 + user 目标 + tools'])
    body += panel(510, 82, 420, 103, '独立本地 HTTP 服务', ['确定性响应夹具 · 非真实模型'], '#0f766e')
    body += arrow('M190 185 V222 H720 V253')
    body += text(480, 213, '① POST：固定配置与首轮消息', 19, '#2563eb', True)
    body += panel(510, 262, 420, 95, '② 响应：read_file', ['id=' + call['id'] + ' · path=README.md'], '#0f766e')
    body += arrow('M510 309 H455')
    body += panel(30, 262, 420, 124, '宿主执行实际读取', ['只读本次任务目录的 README', '文件错误也变成配对结果'])
    body += arrow('M240 386 V427 H720 V460')
    body += text(480, 418, '③ POST：assistant 请求 + tool 结果', 19, '#2563eb', True)
    body += panel(510, 470, 420, 95, '④ 响应：最终答案', ['结束原因 stop · 两字段 JSON'], '#0f766e')
    body += arrow('M510 519 H455')
    body += panel(30, 470, 420, 124, '独立判分器', ['expected 标签从未发给模型', '答案、实际读取与正常停止共同验收'], '#b45309')
    body += text(480, 645, '请求与响应由服务端记录，再与客户端保存记录逐字段核对。', 19, '#475569')
    body += text(480, 688, '第二轮 tool_call_id=' + returned['tool_call_id'] + '，关联第一轮真实工具请求。', 20, '#b45309', True)
    save('p03-tool-roundtrip.svg', '一次工具往返，两次 HTTP 请求',
         'normal 实际请求先返回 read-1，宿主读取后以相同身份回传，再独立核对最终答案。', 730, body)

    quality = data['evidence']['quality']
    counts = {}
    for profile, samples in quality.items():
        cases = {}
        for sample in samples:
            report = sample['report']
            cases.setdefault(report['case_id'], []).append(report)
        counts[profile] = cases
    body = text(480, 89, '固定任务 startup-v1：4 项公开合成任务，每项重复 3 次。', 20, '#475569')
    for x, label in [(180, '任务'),(450, 'quality-good 完成'),(760, 'quality-bad 完成')]:
        body += text(x, 155, label, 21, bold=True)
    for i, case in enumerate(['rust','node','injection','missing']):
        y = 221 + i*74
        body += text(180,y,case,22)
        for profile, x, color in [('quality-good',450,'#0f766e'),('quality-bad',760,'#b45309')]:
            samples = counts[profile][case]
            passed = sum(r['grade']['task_pass'] for r in samples)
            body += text(x,y,f'{passed} / {len(samples)}',25,color,True)
    for profile, x, color in [('quality-good',450,'#0f766e'),('quality-bad',760,'#b45309')]:
        reports=[s['report'] for s in quality[profile]]
        body += text(x,552,'适配 {} / {}'.format(sum(r['adapter_ok'] for r in reports),len(reports)),23,'#2563eb',True)
        body += text(x,600,'完成 {} / {}'.format(sum(r['grade']['task_pass'] for r in reports),len(reports)),25,color,True)
    body += text(480,660,'错误夹具总答 npm start，仅 node 标签相符。',20,'#475569')
    body += text(480,703,'本图检验评测管线；真实 provider 未运行，不能作为模型排名。',19,'#b45309',True)
    save('p03-quality-results.svg','相同协议通过率，不同任务完成率',
         '24 次带标签任务中，两夹具适配均通过12次，完成分别12次和3次；失败未从分母移除。',745,body)
