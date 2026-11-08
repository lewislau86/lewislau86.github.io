"""Verify R19 against real local MCP child services and extracted published archive."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/public/learn-agent-rust/code/mcp-tools'
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
DATA = ROOT / 'scripts/data/learn-agent-rust/r19-results.json'
ARCHIVE = PUBLIC / 'mcp-tools-lab.zip'
CHAPTER = ROOT / 'docs/learn-agent-rust/mcp-tools.md'
FILES = ['Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.gitignore', 'README.md'] + [
    'src/' + name + '.rs' for name in ['main', 'server', 'adapter', 'connection', 'schema', 'lab', 'tests']]
SCENARIOS = ['normal', 'dual-server', 'denied-write', 'approved-write', 'approval-mismatch',
             'invalid-arguments', 'unknown-tool', 'duplicate-call', 'tool-error', 'protocol-error',
             'timeout', 'write-timeout', 'server-crash', 'discovery-duplicate', 'discovery-schema',
             'discovery-name', 'cursor-loop', 'missing-capability', 'startup-exit', 'startup-timeout',
             'dirty-stdout', 'list-timeout', 'result-limit', 'closed-registry', 'call-budget']
EXPECTED = {
    'normal': ['ok', 'ok'], 'dual-server': ['ok', 'ok'], 'denied-write': ['approval_required'],
    'approved-write': ['ok'], 'approval-mismatch': ['approval_required'], 'invalid-arguments': ['invalid_arguments'],
    'unknown-tool': ['unknown_tool'], 'duplicate-call': ['ok', 'duplicate_call'], 'tool-error': ['tool_error'],
    'protocol-error': ['protocol_error'], 'timeout': ['timeout', 'connection_unavailable'],
    'write-timeout': ['outcome_unknown', 'connection_unavailable'],
    'server-crash': ['transport_error', 'connection_unavailable'],
    'result-limit': ['result_limit'], 'closed-registry': ['unknown_tool'], 'call-budget': ['ok'] * 8 + ['call_budget'],
}
DISCOVERY = {'discovery-duplicate': 'duplicate_alias', 'discovery-schema': 'unsupported_schema',
             'discovery-name': 'unsupported_name', 'cursor-loop': 'cursor_loop',
             'missing-capability': 'connection_unavailable', 'startup-exit': 'connection_unavailable',
             'startup-timeout': 'connection_unavailable', 'dirty-stdout': 'connection_unavailable',
             'list-timeout': 'discovery_failed'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env=None, timeout=180):
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    require(p.returncode == 0, '{}\n{}\n{}'.format(args, p.stdout, p.stderr))
    return p.stdout


def digest(content):
    return hashlib.sha256(content).hexdigest()


def verify_scenarios(binary, directory):
    rows, outputs = [], {}
    for name in SCENARIOS:
        folder = directory / name
        raw = json.loads(command([str(binary), name, str(folder)], directory, timeout=20))
        require(raw['scenario'] == name, 'Scenario mismatch')
        servers = ['notes', 'other'] if name == 'dual-server' else ['notes']
        events, effects = {}, {}
        for server in servers:
            child = raw['cleanup'][server]
            require(child['reaped'], 'Child not reaped')
            try:
                os.kill(child['pid'], 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('Child PID still exists')
            path = folder / server
            require('diagnostic on stderr' in (path / 'stderr.txt').read_text(), 'Missing stderr diagnostic')
            log = path / 'events.jsonl'
            actual = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            # Cancellation delivery is optional; it does not prove effect rollback.
            events[server] = [e for e in actual if e['event'] != 'cancelled']
            effect = path / 'notes.txt'
            effects[server] = effect.read_text() if effect.exists() else ''
        calls = sum(e['event'] == 'call' for events_ in events.values() for e in events_)
        effect_lines = sum(len(text.splitlines()) for text in effects.values())
        expected_calls = 2 if name == 'dual-server' else 8 if name == 'call-budget' else 0 if name in DISCOVERY or name in [
            'denied-write', 'approval-mismatch', 'invalid-arguments', 'unknown-tool', 'closed-registry'] else 1
        require(calls == raw['dispatched'] == expected_calls, name + ': wrong actual dispatch count')
        require(effect_lines == (1 if name in ['approved-write', 'write-timeout'] else 0), name + ': wrong effects')
        if effect_lines:
            require(effects['notes'] == 'one line\n', 'Unexpected note contents')
        require(raw['remaining_tools'] == ['local_status'], 'Stale entries survived close')
        outcome = [r['content'].get('error', 'ok' if r['content']['ok'] else 'tool_error') for r in raw['results']]
        require(outcome == EXPECTED.get(name, []), name + ': wrong caller result ' + str(outcome))
        require(raw['discovery']['notes'] == DISCOVERY.get(name, 'ok'), name + ': wrong discovery result')
        if name in DISCOVERY:
            require(len(raw['definitions']) == 1 and calls == 0, 'Partial discovery published')
        else:
            require(len(raw['definitions']) == 1 + 7 * len(servers), 'Discovery count differs')
        # Preserve the raw deterministic protocol exchange; omit optional shutdown cancellation messages.
        wire = [e for e in raw['wire'] if e.get('message', {}).get('method') != 'notifications/cancelled']
        protocol_calls = [e for e in wire if e.get('message', {}).get('method') == 'tools/call']
        require(len(protocol_calls) == calls, 'Wire calls disagree with service file log')
        for server in servers:
            stream = [e['message'] for e in wire if e['server'] == server and 'message' in e]
            requests = {m['id']: m for m in stream if 'method' in m and 'id' in m}
            for m in stream:
                if 'id' in m and 'method' not in m:
                    require(m['id'] in requests and m['jsonrpc'] == '2.0', 'Unpaired protocol response')
            if raw['startup'][server] == 'ready':
                require(stream[0]['method'] == 'initialize', 'Handshake not first')
                require(stream[0]['params']['protocolVersion'] == '2025-11-25', 'Wrong requested version')
                require(stream[1]['result']['protocolVersion'] == '2025-11-25', 'Wrong negotiated version')
                require(stream[2]['method'] == 'notifications/initialized', 'Missing initialized')
                require(stream[1]['result']['capabilities']['tools'] == {}, 'Missing tools capability')
        if name not in DISCOVERY:
            remote_tools = {(e['server'], tool['name']): tool for e in wire
                            for tool in e.get('message', {}).get('result', {}).get('tools', [])}
            for definition in raw['definitions']:
                function = definition['function']
                if function['name'] == 'local_status':
                    continue
                matched = [(server, tool) for (server, remote), tool in remote_tools.items()
                           if function['name'] == 'mcp_' + server + '__' + remote]
                require(len(matched) == 1 and function['parameters'] == matched[0][1]['inputSchema'], 'Schema mapping changed')
            for call in protocol_calls:
                require(not call['message']['params']['name'].startswith('mcp_'), 'Alias leaked to server')
        if name in ['normal', 'dual-server']:
            reads = [r for r in raw['results'] if 'structuredContent' in r['content'].get('data', {})]
            require(len(reads) == len(servers), 'Structured result lost')
            for server, result in zip(servers, reads):
                require(result['content']['data']['structuredContent']['text'] == (folder / server / 'README.md').read_text(), 'Read result differs from actual file')
        if name in ['denied-write', 'approved-write', 'approval-mismatch']:
            hints = [tool['annotations']['readOnlyHint'] for e in wire
                     for tool in e.get('message', {}).get('result', {}).get('tools', [])
                     if tool['name'] == 'append_note']
            require(hints == [True], 'Misleading hint fixture missing')
        if name == 'startup-timeout':
            require(raw['startup']['notes'] == 'startup_timeout', 'Init timeout missing')
        if name == 'dirty-stdout':
            require(any(e.get('invalid_frame') for e in wire), 'Non-protocol stdout not rejected')
        # OS-specific signals/PIDs are checked live, not made reproducibility requirements.
        normalized = dict(scenario=name, startup=raw['startup'], discovery=raw['discovery'],
                          definitions=raw['definitions'], results=raw['results'], wire=wire,
                          dispatched=calls, service_events=events, effects=effects, effect_lines=effect_lines,
                          children=len(servers), reaped=len(servers), remaining_tools=raw['remaining_tools'])
        pages = sum(e['event'] == 'list' for ev in events.values() for e in ev)
        outcome_text = ','.join(outcome) if outcome else raw['startup']['notes'] if raw['startup']['notes'] != 'ready' else raw['discovery']['notes']
        lines = [f'scenario={name}', 'protocol=2025-11-25 sdk=rmcp-3.9.0',
                 f'pages={pages} registered={len(raw["definitions"])}',
                 f'remote_calls={calls} note_lines={effect_lines}', 'caller_results=' + outcome_text,
                 f'children={len(servers)} reaped={len(servers)} remaining=local_status']
        if name == 'normal':
            lines += ['read_text=' + json.dumps(normalized['results'][1]['content']['data']['structuredContent']['text'], ensure_ascii=False),
                      'application_call_id=call-1; wire_call_id=' + str(protocol_calls[0]['message']['id'])]
        if effect_lines:
            lines += ['notes.txt=' + json.dumps(effects['notes'], ensure_ascii=False)]
        output = ('\n'.join(lines) + '\n').encode()
        normalized.update(pages=pages, outcome=outcome_text, output_sha256=digest(output))
        rows.append(normalized)
        outputs[name] = output
    return rows, outputs


def package_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo('mcp-tools-lab/' + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def chapter_bytes(rows):
    text = CHAPTER.read_text()
    start, end = '<!-- r19-results:start -->', '<!-- r19-results:end -->'
    require(text.count(start) == text.count(end) == 1, 'Missing R19 results markers')
    before, rest = text.split(start)
    _, after = rest.split(end)
    table = ['| 场景 | 远端调用 | 写入行数 | 验证结果 |', '| --- | --- | --- | --- |']
    table += ['| `{}` | {} | {} | `{}` |'.format(r['scenario'], r['dispatched'], r['effect_lines'], r['outcome']) for r in rows]
    return (before + start + '\n\n' + '\n'.join(table) + '\n\n' + end + after).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    with tempfile.TemporaryDirectory(prefix='agent-r19-') as directory:
        directory = Path(directory)
        source = directory / 'source'
        for name, content in files.items():
            p = source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(directory / 'target'), RUSTFLAGS='-D warnings')
        command(['cargo', 'fmt', '--', '--check'], source, env)
        tested = command(['cargo', 'test', '--locked', '--', '--test-threads=1'], source, env)
        tests = re.findall(r'^test tests::(\w+) \.\.\. ok$', tested, re.M)
        require(len(tests) == 8 and '8 passed; 0 failed' in tested, 'Rust tests failed')
        command(['cargo', 'clippy', '--locked', '--all-targets', '--', '-D', 'warnings'], source, env)
        command(['cargo', 'build', '--locked'], source, env)
        runs = directory / 'runs'
        runs.mkdir()
        rows, outputs = verify_scenarios(directory / 'target/debug/learn-agent-r19', runs)
        environment = dict(rustc=command(['rustc', '--version'], source, env).strip(),
                           host=command(['rustc', '-vV'], source, env).split('host: ')[1].splitlines()[0])
        if args.check and DATA.exists():
            environment = json.loads(DATA.read_text())['environment']
        evidence = dict(scope='R19 real local stdio MCP, fixed caller, trusted fixture services; no real model, frameworks, HTTP or arbitrary service sandbox',
                        protocol='2025-11-25', sdk='rmcp 3.9.0', environment=environment,
                        files_sha256={name:digest(content) for name, content in files.items()},
                        regression_tests=tests, scenarios=rows)
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + '\n').encode()
        contents = dict(files)
        contents.update({'outputs/' + name + '.txt': content for name, content in outputs.items()})
        contents['evidence.json'] = serialized
        archive = package_bytes(contents)
        published = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else archive
        extracted = directory / 'download'
        with zipfile.ZipFile(io.BytesIO(published)) as z:
            z.extractall(extracted)
        download_env = dict(env, CARGO_TARGET_DIR=str(directory / 'download-target'))
        command(['cargo', 'build', '--locked', '--offline'], extracted / 'mcp-tools-lab', download_env)
        repeat = directory / 'repeat'
        repeat.mkdir()
        again, again_outputs = verify_scenarios(directory / 'download-target/debug/learn-agent-r19', repeat)
        require(rows == again and outputs == again_outputs, 'Extracted archive evidence differs')
    artifacts = {DATA:serialized, ARCHIVE:archive, CHAPTER:chapter_bytes(rows)}
    artifacts.update({PUBLIC / 'outputs' / ('r19-' + name + '.txt'):content for name, content in outputs.items()})
    chapter = artifacts[CHAPTER].decode()
    for filename, region in re.findall(r'<<< @/public/learn-agent-rust/code/mcp-tools/(src/[\w.]+)#([\w-]+)', chapter):
        source = files[filename].decode()
        require(source.count('// region ' + region + '\n') == 1 and source.count('// endregion ' + region + '\n') == 1, 'Bad Rust snippet')
    for name in re.findall(r'<<< @/public/learn-agent-rust/outputs/r19-([\w-]+).txt', chapter):
        require(name in outputs, 'Unknown output snippet')
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, 'Stale R19 artifact: ' + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print('R19: 25 scenarios / {} real child servers, 8 Rust tests, Clippy, wire/file/PID checks and extracted archive rerun passed; {}'.format(
        sum(r['children'] for r in rows), 'artifacts checked' if args.check else 'artifacts saved'))


if __name__ == '__main__':
    main()
