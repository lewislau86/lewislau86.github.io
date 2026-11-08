"""R19 diagrams derived from real local MCP wire and filesystem evidence."""
import hashlib
import json


def generate(root, text, panel, arrow, save):
    evidence = json.loads((root / 'scripts/data/learn-agent-rust/r19-results.json').read_text())
    source = root / 'docs/public/learn-agent-rust/code/mcp-tools'
    for name, digest in evidence['files_sha256'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('R19 evidence is stale; rerun verify-agent-mcp.py')
    rows = {r['scenario']: r for r in evidence['scenarios']}
    normal = rows['normal']
    wire = normal['wire']
    calls = [e['message'] for e in wire if e.get('message', {}).get('method') == 'tools/call']
    application_id = normal['results'][-1]['tool_call_id']
    body = panel(32, 85, 896, 112, '宿主：固定调用脚本 → 统一工具入口',
                 ['本地 local_status + 远端 mcp_notes__read_note',
                  '先校验参数、权限和次数，再选择处理路径'])
    body += arrow('M270 197 V246') + arrow('M690 197 V246')
    body += panel(32, 255, 420, 130, '本地路径', ['宿主函数直接返回', '不产生 tools/call'], '#2563eb')
    body += panel(508, 255, 420, 130, '远端路径', ['namespace=notes · 原名 read_note',
                   '应用 ID=' + application_id + ' · JSON-RPC ID=' + str(calls[0]['id'])], '#0f766e')
    body += arrow('M718 385 V436')
    body += text(481, 418, '真实 stdio 管道 · JSON-RPC', 18, '#0f766e')
    body += panel(508, 446, 420, 128, '独立子进程：本地 MCP 服务', ['实际读取练习 README.md', '返回 content + structuredContent'], '#0f766e')
    body += text(253, 481, '两种结果都保留应用调用 ID', 21, '#2563eb', True)
    body += text(253, 525, '模型接口与图节点接线在 R20 验收', 17, '#475569')
    body += text(480, 629, 'normal：{} 次远端调用，{} 个直属服务已回收。'.format(normal['dispatched'], normal['reaped']), 20, bold=True)
    save('r19-mcp-routing.svg', '同一注册入口，两种执行位置',
         '本地工具在宿主执行，远端别名映射到 notes 服务的 read_note；两种调用身份分别保留。', 670, body)

    outgoing = [e['message'] for e in wire if e['direction'] == 'client_to_server' and 'message' in e]
    assert [m['method'] for m in outgoing] == ['initialize', 'notifications/initialized', 'tools/list', 'tools/list', 'tools/call']
    labels = ['initialize · 版本与能力', 'notifications/initialized', 'tools/list · 第一页', 'tools/list · cursor=second', 'tools/call · read_note']
    body = text(480, 89, '本章固定 MCP ' + evidence['protocol'] + '，显式使用 initialize 生命周期', 20, '#475569')
    for i, label in enumerate(labels):
        y = 123 + i * 91
        body += panel(120, y, 720, 65, label, [], '#0f766e' if i == 4 else '#2563eb')
        if i < len(labels) - 1:
            body += arrow('M480 {} V{}'.format(y + 65, y + 85))
    body += text(480, 623, '实际发现 {} 页，注册 {} 项（含 1 项本地工具）。'.format(normal['pages'], len(normal['definitions'])), 20, bold=True)
    dual = rows['dual-server']
    body += text(480, 665, '双服务：{} 项；同名工具分别使用 mcp_notes__ 与 mcp_other__。'.format(len(dual['definitions'])), 18, '#475569')
    save('r19-discovery-lifecycle.svg', '发现完成后，再发布统一工具描述',
         '请求顺序来自 normal 实际协议帧；分页、工具总数与双服务命名来自实验输出。', 704, body)

    selected = ['denied-write', 'approved-write', 'approval-mismatch', 'timeout', 'write-timeout', 'server-crash', 'result-limit']
    body = text(480, 89, '调用数由服务日志与 tools/call 帧交叉核对；写入行数直接读文件。', 18, '#475569')
    for x, label in [(175, '场景'), (400, '远端调用'), (546, '写入行数'), (776, '首个结果')]:
        body += text(x, 139, label, 20, bold=True)
    for i, name in enumerate(selected):
        row = rows[name]
        y = 188 + i * 51
        if i % 2 == 0:
            body += '<rect x="25" y="{}" width="910" height="45" rx="6" fill="#e2e8f0"/>'.format(y - 29)
        body += text(175, y, name, 18)
        body += text(400, y, str(row['dispatched']), 22, '#0f766e', True)
        body += text(546, y, str(row['effect_lines']), 22, '#b45309', True)
        body += text(776, y, row['outcome'].split(',')[0], 17)
    body += text(480, 592, 'write-timeout：已写一行，回复未完成；保留效果，停止自动重放。', 19, '#b45309', True)
    body += text(480, 637, '25 个场景共启动并核对回收 {} 个直属子进程。'.format(sum(r['children'] for r in rows.values())), 20, bold=True)
    save('r19-mcp-results.svg', '协议请求结束后，实际效果还需要核对',
         '七个实际场景对照权限拦截、成功写入、超时与断连；超时不代表没有业务效果。', 676, body)
