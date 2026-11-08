"""R20 integration diagrams; labels and counts are checked against actual run evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / 'scripts/data/learn-agent-rust/r20-results.json').read_text())
    source = root / 'docs/public/learn-agent-rust/code/integrated-agent'
    for name, digest in evidence['files_sha256'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('R20 evidence stale: run verify-agent-integration.py')
    rows = {r['scenario']: r for r in evidence['scenarios']}
    normal = rows['normal']
    usage = normal['usage']
    events = normal['events']
    assert normal['completed'] and normal['cleanup']['mcp_reaped']
    lead_models = sum(e['kind'] == 'model' and e['actor'] == 'lead' for e in events)
    peer_models = sum(e['kind'] == 'model' and e['actor'] == 'reviewer' for e in events)
    lead_tools = sum(e['kind'] == 'attempt' and e['actor'] == 'lead' for e in events)
    peer_tools = sum(e['kind'] == 'attempt' and e['actor'] == 'reviewer' for e in events)
    body = panel(110, 85, 740, 98, 'SQLite：固定到期身份 → startup-1 → CAS 领取',
                 ['重复触发新增 {} 条；owner=lead · epoch=1'.format(normal['trigger_duplicate_inserted'])])
    body += arrow('M480 183 V208 H160 V229')
    for x, title, line in [(30, 'Prepare', '来源 · 历史 · 当前证据'), (350, 'ModelTurn', 'LLM 消息与动作请求'), (670, 'ExecuteTools', '批准 · 派发 · 配对结果')]:
        body += panel(x, 235, 260, 100, title, [line])
    body += arrow('M290 282 H344') + arrow('M610 282 H664')
    body += arrow('M800 335 V365 H160 V341')
    body += text(480, 392, 'graph-flow 推进会话；langchain-rust 承载消息与脚本 LLM', 20, '#2563eb', True)
    body += arrow('M800 335 V419 H708 V440')
    body += arrow('M800 419 H252 V440')
    body += panel(32, 448, 440, 125, 'MCP：另一个直属进程',
                  ['stdio 握手 → 发现 → read_startup', '实际读取本次 worktree 的 README'], '#0f766e')
    body += panel(500, 448, 428, 125, 'reviewer：私有 Tokio 任务',
                  ['自己的 LLM 历史与只读动作', 'request_id → 来源核对 → 回执'], '#0f766e')
    body += text(480, 608, '两条路径绑定同一 worktree，共用父子预算账本。', 20, '#475569')
    body += panel(110, 638, 740, 125, '写报告 → 独立验收 → 清理资源 → 提交终态与记忆',
                  ['正常：{} 次模型 / {} 次工具尝试；{} 个审查句柄已回收'.format(usage['models'], usage['tools'], usage['joined']),
                   '主检出未改；报告工作区保留；MCP 已回收'], '#b45309')
    save('r20-integration-path.svg', '一条任务贯穿循环与运行资源',
         '固定任务在 SQLite 领取，三节点循环调用真实 MCP 与私有审查，报告经宿主验收后提交终态。', 800, body)

    calls = [e['message'] for e in normal['wire'] if e['message'].get('method') == 'tools/call']
    call_id = normal['history_archive'][0]['tool_calls'][0]['id']
    request_id = normal['state']['review']['request_id']
    body = panel(32, 85, 896, 105, '持久任务：startup-1',
                 ['固定触发身份去重；图会话 startup-1-run-1；归属 lead / epoch=1'])
    body += arrow('M248 190 V232') + arrow('M712 190 V232')
    body += panel(32, 242, 440, 156, '父工具调用：' + call_id,
                  ['{} 次生成，{} 次工具尝试'.format(lead_models, lead_tools),
                   'MCP tools/call 协议 ID = ' + str(calls[0]['id']), '重试保持逻辑 ID，协议请求各自编号'])
    body += panel(500, 242, 428, 156, '审查请求：' + request_id,
                  ['{} 次生成，{} 次工具尝试'.format(peer_models, peer_tools),
                   '私有 read_file → reviewer 回执', '只把核对结果交回父 Agent'], '#0f766e')
    body += arrow('M248 398 V442 H360 V468') + arrow('M712 398 V442 H600 V468')
    body += panel(100, 477, 760, 125, '同一个 Book：先扣款，再调用',
                  ['总计 {} 次模型、{} 次工具尝试'.format(usage['models'], usage['tools']),
                   '运行事件字段：seq · actor · call_id · kind · detail'], '#b45309')
    retry = rows['read-retry']
    body += text(480, 644, 'read-retry：模型 {} 次，工具尝试 {} 次，重试 {} 次。'.format(
        retry['usage']['models'], retry['usage']['tools'], retry['usage']['retries']), 21, '#b45309', True)
    body += text(480, 688, '运行事件结束时导入 SQLite；不是逐事件持久化检查点。', 19, '#475569')
    save('r20-identity-and-budget.svg', '身份分清，预算合并',
         '任务、逻辑工具调用、MCP 协议和审查请求使用各自身份，父子调用在同一账本中累计。', 730, body)

    body = panel(32, 85, 270, 108, '① 文件效果', ['report.txt 实际字节'], '#0f766e')
    body += arrow('M302 138 H339')
    body += panel(347, 85, 270, 108, '② 目标验收', ['读取 + 回执 + 写入 + 归属'])
    body += arrow('M617 138 H654')
    body += panel(662, 85, 266, 108, '③ SQLite 事务', ['终态 + 新记忆 + 终态事件'], '#b45309')
    for x, label in [(210, '场景'), (456, '报告存在'), (632, '目标通过'), (818, '任务状态')]:
        body += text(x, 252, label, 21, bold=True)
    for i, name in enumerate(['normal', 'post-hook', 'write-unknown', 'terminal-save-failed']):
        row = rows[name]
        y = 314 + i * 72
        body += '<rect x="32" y="{}" width="896" height="53" rx="8" fill="{}"/>'.format(y - 33, '#e2e8f0' if i % 2 == 0 else '#fff')
        body += text(210, y, name, 18)
        body += text(456, y, '是' if row['report_exists'] else '否', 23, '#0f766e', True)
        body += text(632, y, '是' if row['goal_verified'] else '否', 23, '#2563eb', True)
        body += text(818, y, row['database']['status'], 20, '#b45309', True)
    body += text(480, 620, '数据库回滚不能撤销文件；写后错误要保留证据并对账。', 21, '#b45309', True)
    body += text(480, 663, '完成 = 目标验收通过，而且 completed 终态提交成功。', 20, '#475569')
    save('r20-effect-and-terminal.svg', '三个时刻，分别验收',
         '实际四个场景显示文件效果、目标验收和数据库终态可能不同步；保存失败留下报告但任务仍运行中。', 705, body)
