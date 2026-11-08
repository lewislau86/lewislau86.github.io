"""Verify R20's real graph/LLM wiring, MCP process, SQLite, Git and integration fault boundaries."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/public/learn-agent-rust/code/integrated-agent'
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
DATA = ROOT / 'scripts/data/learn-agent-rust/r20-results.json'
ARCHIVE = PUBLIC / 'integrated-agent.zip'
CHAPTER = ROOT / 'docs/learn-agent-rust/integrated-agent.md'
FILES = ['Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.gitignore', 'README.md'] + [
    'src/' + n + '.rs' for n in ['main', 'agent', 'runtime', 'store', 'server', 'connection', 'tests']]
# stop, model attempts, tool attempts, reviewer starts, report effect, verified goal, database status
EXPECTED = {
    'normal': ('answered', 7, 5, 1, True, True, 'completed'),
    'read-retry': ('answered', 7, 6, 1, True, True, 'completed'),
    'approval-denied': ('approval_required', 6, 4, 1, False, False, 'failed'),
    'pre-hook': ('pre_hook_blocked', 6, 4, 1, False, False, 'failed'),
    'post-hook': ('post_hook_failed', 6, 5, 1, True, False, 'failed'),
    'write-unknown': ('write_outcome_unknown', 6, 5, 1, True, False, 'failed'),
    'model-budget': ('model_budget', 2, 2, 1, False, False, 'failed'),
    'tool-budget': ('tool_budget', 3, 2, 1, False, False, 'failed'),
    'context-budget': ('context_budget', 0, 0, 0, False, False, 'failed'),
    'source-stale': ('source_stale', 0, 0, 0, False, False, 'failed'),
    'knowledge-injection': ('approval_required', 1, 0, 0, False, False, 'failed'),
    'false-finish': ('answered', 1, 0, 0, False, False, 'failed'),
    'duplicate-call': ('invalid_call_id', 2, 1, 0, False, False, 'failed'),
    'model-error': ('model_error', 1, 0, 0, False, False, 'failed'),
    'review-failed': ('review_failed', 4, 4, 1, False, False, 'failed'),
    'cancel-review': ('cancelled', 3, 3, 1, False, False, 'failed'),
    'stale-owner': ('stale_owner_or_workspace', 6, 4, 1, False, False, 'running'),
    'terminal-save-failed': ('answered', 7, 5, 1, True, True, 'running'),
}
README = 'Project: Rust Agent\nStartup: cargo run --release\n'
REPORT = 'Startup: cargo run --release\nReview: README verified\n'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env=None, timeout=300):
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    require(p.returncode == 0, '{}\n{}\n{}'.format(args, p.stdout, p.stderr))
    return p.stdout


def digest(content):
    return hashlib.sha256(content).hexdigest()


def check_messages(messages):
    pending, seen = set(), set()
    for m in messages:
        if m['message_type'] == 'tool':
            require(m['id'] in pending, 'Orphan/duplicate tool response')
            pending.remove(m['id'])
        else:
            require(not pending, 'Incomplete tool group')
            for c in m['tool_calls'] or []:
                require(c['id'] and c['id'] not in seen, 'Duplicate call identity')
                pending.add(c['id'])
                seen.add(c['id'])
    require(not pending, 'Missing tool response')
    return seen


def verify_scenarios(binary, directory):
    rows, outputs = [], {}
    for name, expected in EXPECTED.items():
        folder = directory / name
        stop, models, tools, spawned, effect, goal, status = expected
        output = command([str(binary), name, str(folder)], directory, timeout=30)
        raw = json.loads((folder / 'run.json').read_text())
        require(raw['scenario'] == name and raw['state']['stop'] == stop, name + ': wrong stop')
        require(raw['goal_verified'] == goal and raw['completed'] == (status == 'completed'), name + ': wrong goal/completion')
        usage = raw['usage']
        require(usage == dict(models=models, tools=tools, spawned=spawned, joined=spawned,
                              retries=int(name == 'read-retry')), name + ': wrong shared ledger')
        require(raw['trigger_duplicate_inserted'] == 0 and raw['reopened_equal'], name + ': storage identity/reopen')
        cleanup = raw['cleanup']
        require(cleanup['mcp_reaped'] and cleanup['active_jobs'] == 0 and cleanup['peer_closed'] == bool(spawned), name + ': cleanup')
        try:
            os.kill(cleanup['mcp_pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError(name + ': MCP child still exists')
        repo, workspace = folder / 'repository', folder / 'workspace'
        require((repo / 'README.md').read_text() == README and cleanup['source_unchanged'], name + ': primary changed')
        require(command(['git', '-C', str(repo), 'status', '--porcelain=v1'], directory) == '', name + ': primary dirty')
        actual_report = (workspace / 'report.txt').read_text() if (workspace / 'report.txt').exists() else None
        require(actual_report == (REPORT if effect else None) and raw['report_exists'] == effect
                and raw['report_text'] == actual_report, name + ': report effects')
        require(not (folder / 'outside.txt').exists() and not (directory / 'outside.txt').exists(), 'Escaped write')
        require(workspace.exists() == effect and cleanup['workspace'] == ('retained' if effect else 'removed'), name + ': worktree disposition')
        registrations = command(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'], directory)
        require(registrations.count('worktree ') == 1 + int(effect), name + ': worktree leak')
        require(('branch refs/heads/codex/r20-startup-a1' in registrations) == effect, name + ': worktree binding')
        with sqlite3.connect(folder / 'tasks.sqlite') as db:
            task = db.execute('SELECT trigger_id,task_id,status,owner,epoch FROM task').fetchall()
            require(task == [('startup@2026-11-08T08:00:00+08:00', 'startup-1', status,
                              'replacement' if name == 'stale-owner' else 'lead', 2 if name == 'stale-owner' else 1)], name + ': actual SQLite task')
            memory = db.execute('SELECT id,value FROM memory').fetchall()
            require(memory == ([('startup-report', 'report.txt verified')] if status == 'completed' else []), name + ': memory promotion')
            events = [dict(zip(['seq', 'call_id', 'kind', 'detail'], row)) for row in db.execute('SELECT seq,call_id,kind,detail FROM event ORDER BY seq')]
            require(events == raw['database']['events'] and raw['database']['status'] == status
                    and raw['database']['memory_records'] == len(memory), name + ': actual SQLite differs')
            require(db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SQLite integrity')
        runtime_events = raw['events']
        require([e['seq'] for e in runtime_events] == list(range(1, len(runtime_events) + 1)), 'Non-monotonic runtime events')
        require(events[0]['kind'] == 'claimed', 'Missing claim event')
        require(events[1:1 + len(runtime_events)] == [dict(seq=e['seq'] + 1, call_id=e['call_id'], kind=e['kind'],
                detail=e['actor'] + ':' + e['detail']) for e in runtime_events], 'Runtime event import differs')
        require(sum(e['kind'] == 'terminal' for e in events) == int(status != 'running'), 'Terminal transaction boundary')
        require(sum(e['kind'] == 'model' for e in runtime_events) == models
                and sum(e['kind'] == 'attempt' for e in runtime_events) == tools, 'Usage/event mismatch')
        require(sum(e['kind'] == 'effect' for e in runtime_events) == int(effect), 'Write replay or missing effect')
        require(len(raw['graph_nodes']) <= 24 and raw['graph_nodes'][0] == 'Prepare', 'Graph bounds')
        require(all(node == ['Prepare', 'ModelTurn', 'ExecuteTools'][i % 3] for i, node in enumerate(raw['graph_nodes'])), 'Graph routing')
        state = raw['state']
        parent_ids = check_messages(state['history'])
        peer_ids = check_messages(raw['review_history'])
        require(not parent_ids.intersection(peer_ids), 'Reviewer call leaked into parent')
        require(all(c['function']['name'] == 'read_file' for m in raw['review_history'] for c in m['tool_calls'] or []), 'Reviewer write permission')
        require(all('reference_data' not in m['content'] and 'archive_receipt' not in m['content'] for m in raw['review_history']), 'Parent context leaked to reviewer')
        for history in state['inputs']:
            check_messages(history)
            require(history[0]['message_type'] == 'system' and sum(m['message_type'] == 'system' for m in history) == 1, 'Policy role')
            require(history[1]['message_type'] == 'human', 'References promoted to policy')
            reference = json.loads(history[1]['content'])
            require(reference['kind'] == 'reference_data' and len(reference['tools']) == 4, 'Model did not receive tool catalog')
            for record in reference['records']:
                filename = 'skill.json' if record['source']['id'] == 'skill/startup' else 'memory.json'
                content = (folder / 'sources' / filename).read_bytes()
                require(record['sha256'] == digest(content) and record['source'] == json.loads(content)
                        and record['authority'] == 'reference_data', 'Reference provenance')
        archive = None
        if state['compacted']:
            content = (folder / 'history-archive.json').read_bytes()
            archive = json.loads(content)
            require(len(archive) == 2 and check_messages(archive) == {'task-1-c1'}, 'Compacted partial group')
            receipt = json.loads(state['history'][1]['content'])
            require(receipt['sha256'] == digest(content) and receipt['kind'] == 'archive_receipt'
                    and state['read_text'] == README, 'Archive receipt/evidence lost')
        else:
            require(not (folder / 'history-archive.json').exists(), 'Unexpected archive')
        stream = [e['message'] for e in raw['wire']]
        requests = [m for m in stream if 'method' in m]
        calls = [m for m in requests if m['method'] == 'tools/call']
        expected_calls = 2 if name == 'read-retry' else 1 if tools else 0
        require(len(calls) == expected_calls, name + ': MCP dispatch count')
        require([m['method'] for m in requests] == ['initialize', 'notifications/initialized', 'tools/list'] + ['tools/call'] * expected_calls, 'MCP lifecycle')
        require(stream[0]['params']['protocolVersion'] == stream[1]['result']['protocolVersion'] == '2025-11-25', 'Protocol pin')
        require(stream[1]['result']['capabilities']['tools'] == {}, 'Missing capability')
        request_ids = {m['id'] for m in requests if 'id' in m}
        responses = [m for m in stream if 'method' not in m]
        require({m['id'] for m in responses} == request_ids and len(responses) == len(request_ids), 'Unpaired wire response')
        require(all(m['params']['name'] == 'read_startup' and m['params']['arguments'] == {'path': 'README.md'} for m in calls), 'Remote alias or arguments changed')
        service_log = folder / 'mcp-calls.jsonl'
        service_calls = [json.loads(line) for line in service_log.read_text().splitlines()] if service_log.exists() else []
        require(service_calls == [dict(attempt=i + 1, path='README.md') for i in range(expected_calls)], 'Wire/service log mismatch')
        if expected_calls:
            require(responses[-1]['result']['structuredContent']['text'] == README, 'MCP result not from actual README')
        if name == 'knowledge-injection':
            require('Ignore permission' in state['inputs'][0][1]['content'] and usage['tools'] == 0, 'Injection fixture did not reach model boundary')
        if name == 'post-hook':
            require(any(e['kind'] == 'post' and e['detail'] == 'post_hook_failed' for e in runtime_events), 'Missing post-hook failure')
        terminal_error = {'stale-owner': 'stale_owner', 'terminal-save-failed': 'injected_before_terminal_commit'}.get(name)
        require(raw['terminal_error'] == terminal_error, 'Wrong transaction error')
        require('model_calls=' + str(models) in output and 'tool_attempts=' + str(tools) in output, 'CLI text differs')
        normalized = copy.deepcopy(raw)
        del normalized['cleanup']['mcp_pid']
        normalized.update(service_calls=service_calls, history_archive=archive, output_sha256=digest(output.encode()))
        rows.append(normalized)
        outputs[name] = output.encode()
    return rows, outputs


def package_bytes(contents):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, value in sorted(contents.items()):
            info = zipfile.ZipInfo('integrated-agent/' + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, value, compress_type=zipfile.ZIP_DEFLATED)
    return result.getvalue()


def chapter_bytes(rows):
    text = CHAPTER.read_text()
    start, end = '<!-- r20-results:start -->', '<!-- r20-results:end -->'
    require(text.count(start) == text.count(end) == 1, 'Missing results markers')
    before, rest = text.split(start)
    _, after = rest.split(end)
    table = ['| 场景 | 停止原因 | 模型 / 工具尝试 | 报告存在 | SQLite 终态 |', '| --- | --- | --- | --- | --- |']
    table += ['| `{}` | `{}` | {} / {} | {} | `{}` |'.format(r['scenario'], r['state']['stop'], r['usage']['models'], r['usage']['tools'],
                '是' if r['report_exists'] else '否', r['database']['status']) for r in rows]
    return (before + start + '\n\n' + '\n'.join(table) + '\n\n' + end + after).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    # A workspace-local cache stays outside public downloads and serves both isolated source builds.
    target = ROOT / '.cache/learn-agent-r20-verify-target'
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    with tempfile.TemporaryDirectory(prefix='agent-r20-') as directory:
        directory = Path(directory)
        source = directory / 'source'
        for name, content in files.items():
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        command(['cargo', 'fmt', '--', '--check'], source, env)
        tested = command(['cargo', 'test', '--locked', '--', '--test-threads=1'], source, env)
        tests = re.findall(r'^test tests::(\w+) \.\.\. ok$', tested, re.M)
        require(len(tests) == 10 and '10 passed; 0 failed' in tested, 'Rust regression tests')
        command(['cargo', 'clippy', '--locked', '--all-targets', '--', '-D', 'warnings'], source, env)
        command(['cargo', 'build', '--locked'], source, env)
        runs = directory / 'runs'
        runs.mkdir()
        rows, outputs = verify_scenarios(target / 'debug/learn-agent-r20', runs)
        environment = dict(rustc=command(['rustc', '--version'], source, env).strip(),
                           host=command(['rustc', '-vV'], source, env).split('host: ')[1].splitlines()[0],
                           git=command(['git', '--version'], source, env).strip())
        if args.check and DATA.exists():
            environment = json.loads(DATA.read_text())['environment']
        evidence = dict(scope='R20 scripted parent/reviewer; real pinned two-library loop, local stdio MCP, SQLite, Git and files; controlled fault exits, no real provider or process recovery',
                        environment=environment, files_sha256={n: digest(v) for n, v in files.items()}, regression_tests=tests, scenarios=rows)
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + '\n').encode()
        contents = dict(files)
        contents.update({'outputs/' + n + '.txt': v for n, v in outputs.items()})
        contents['evidence.json'] = serialized
        archive = package_bytes(contents)
        published = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else archive
        extracted = directory / 'download'
        with zipfile.ZipFile(io.BytesIO(published)) as z:
            z.extractall(extracted)
        download_target = ROOT / '.cache/learn-agent-r20-download-target'
        download_env = dict(env, CARGO_TARGET_DIR=str(download_target))
        command(['cargo', 'build', '--locked', '--offline'], extracted / 'integrated-agent', download_env)
        repeat = directory / 'repeat'
        repeat.mkdir()
        again, again_outputs = verify_scenarios(download_target / 'debug/learn-agent-r20', repeat)
        require(rows == again and outputs == again_outputs, 'Extracted final archive evidence differs')
        # Exercise the JSON CLI too, independently of the summary-producing mode.
        extra = directory / 'json-cli'
        json_report = json.loads(command([str(download_target / 'debug/learn-agent-r20'), '--json', 'normal', str(extra)], directory))
        require(json_report == json.loads((extra / 'run.json').read_text()) and json_report['completed'], 'JSON CLI differs')
    artifacts = {DATA: serialized, ARCHIVE: archive, CHAPTER: chapter_bytes(rows)}
    artifacts.update({PUBLIC / 'outputs' / ('r20-' + name + '.txt'): content for name, content in outputs.items()})
    chapter = artifacts[CHAPTER].decode()
    snippets = re.findall(r'<<< @/public/learn-agent-rust/code/integrated-agent/(src/[\w.]+)#([\w-]+)', chapter)
    require(len(snippets) >= 8, 'Missing integration code snippets')
    for filename, region in snippets:
        source = files[filename].decode()
        require(source.count('// region ' + region + '\n') == source.count('// endregion ' + region + '\n') == 1, 'Bad Rust snippet')
    for name in re.findall(r'<<< @/public/learn-agent-rust/outputs/r20-([\w-]+).txt', chapter):
        require(name in outputs, 'Unknown output snippet')
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, 'Stale R20 artifact: ' + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print('R20: 18 scenarios, 10 Rust tests, Clippy, actual SQLite/Git/files/messages/MCP/PID checks, extracted final archive offline rerun and JSON CLI passed; ' + ('artifacts checked' if args.check else 'artifacts saved'))


if __name__ == '__main__':
    main()
