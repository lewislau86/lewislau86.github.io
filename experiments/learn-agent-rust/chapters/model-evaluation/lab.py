"""P03 loopback fixture + fixed evaluation set. Standard library only; no model key needed."""
import argparse
import hashlib
import json
import math
import datetime
import platform
from pathlib import Path
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
# expected adapter result, stop, actual file reads, requests received
PROTOCOL = {
    'normal': (True, 'answered', 1, 2),
    'wrong-answer': (True, 'answered', 1, 2),
    'false-finish': (True, 'answered', 0, 1),
    'missing-usage': (True, 'answered', 1, 2),
    'bad-json': (False, 'invalid_json', 0, 1),
    'http401': (False, 'authentication', 0, 1),
    'http429': (False, 'rate_limited', 0, 1),
    'http500': (False, 'server_error', 0, 1),
    'redirect': (False, 'redirect_refused', 0, 1),
    'timeout': (False, 'timeout', 0, 1),
    'body-timeout': (False, 'timeout', 0, 1),
    'chunked-limit': (False, 'response_limit', 0, 1),
    'oversize': (False, 'response_limit', 0, 1),
    'content-type': (False, 'content_type', 0, 1),
    'empty-choices': (False, 'invalid_choices', 0, 1),
    'wrong-role': (False, 'invalid_message', 0, 1),
    'bad-arguments': (False, 'invalid_arguments', 0, 1),
    'missing-id': (False, 'invalid_call_id', 0, 1),
    'parallel-calls': (False, 'unsupported_finish', 0, 1),
    'truncated': (False, 'generation_incomplete', 0, 1),
    'filtered': (False, 'filtered', 0, 1),
    'model-drift': (False, 'model_mismatch', 0, 1),
    'bad-usage': (False, 'invalid_usage', 0, 1),
    'unknown-tool': (True, 'unknown_tool', 0, 1),
    'path-escape': (True, 'permission_denied', 0, 1),
    'duplicate-id': (True, 'duplicate_call', 1, 2),
    'repeat-read': (True, 'tool_budget', 1, 2),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


# region fixture
class Fixture(ThreadingHTTPServer):
    daemon_threads = False
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.records = []
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass

    def do_POST(self):
        mode = self.path.removeprefix('/fixture/')
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        # Token value is checked in memory, never persisted. The fixture value is public dummy data.
        require(self.headers.get('Authorization') == 'Bearer fixture-secret', 'Fixture authentication missing')
        require(request['model'] == 'fixture-v1' and request['stream'] is False, 'Request configuration')
        require(request['tools'][0]['function']['name'] == 'read_file', 'Tools missing on HTTP wire')
        with self.server.lock:
            record = {'mode': mode, 'request': request, 'status': None, 'response': None}
            self.server.records.append(record)
        status, content_type = 200, 'application/json'
        messages = request['messages']
        results = [m for m in messages if m['role'] == 'tool']
        tool = {'id': 'read-1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"README.md"}'}}
        if not results or mode in ['duplicate-id', 'repeat-read']:
            if mode == 'repeat-read' and results:
                tool['id'] = 'read-2'
            message = {'role': 'assistant', 'content': None, 'tool_calls': [tool]}
            finish = 'tool_calls'
        else:
            data = json.loads(results[-1]['content'])
            command = next((line.removeprefix('Startup: ').strip() for line in data.get('text', '').splitlines() if line.startswith('Startup: ')), None)
            if mode in ['wrong-answer', 'quality-bad']:
                command = 'npm start'
            message = {'role': 'assistant', 'content': json.dumps({'command': command, 'source': 'README.md'})}
            finish = 'stop'
        if mode == 'false-finish':
            message = {'role': 'assistant', 'content': '{"command":"cargo run --release","source":"README.md"}'}
            finish = 'stop'
        value = {'id': 'fixture-response', 'object': 'chat.completion', 'model': 'fixture-v1',
                 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}}
        if mode == 'missing-usage':
            del value['usage']
        if mode in ['http401', 'http429', 'http500']:
            status = int(mode[4:])
            value = {'error': {'message': 'fixed fixture failure'}}
        if mode == 'redirect':
            status = 302
        if mode == 'content-type':
            content_type = 'text/html'
        if mode == 'empty-choices':
            value['choices'] = []
        if mode == 'wrong-role':
            message['role'] = 'user'
        if mode == 'bad-arguments':
            tool['function']['arguments'] = '{bad'
        if mode == 'missing-id':
            tool.pop('id')
        if mode == 'parallel-calls':
            message['tool_calls'].append(dict(tool, id='read-2'))
        if mode == 'unknown-tool':
            tool['function']['name'] = 'run_shell'
        if mode == 'path-escape':
            tool['function']['arguments'] = '{"path":"../../secret.txt"}'
        if mode == 'truncated':
            value['choices'][0]['finish_reason'] = 'length'
        if mode == 'filtered':
            value['choices'][0]['finish_reason'] = 'content_filter'
        if mode == 'model-drift':
            value['model'] = 'fixture-v2'
        if mode == 'bad-usage':
            value['usage']['total_tokens'] = 121
        body = b'{bad' if mode == 'bad-json' else b'x' * 65537 if mode in ['oversize', 'chunked-limit'] else json_bytes(value)
        if mode == 'timeout':
            time.sleep(1.2)  # Client has a real 800 ms request deadline; this is not a performance sample.
        record.update(status=status, response=value if mode not in ['bad-json', 'oversize', 'chunked-limit'] else None,
                      body_sha256=digest(body), body_bytes=len(body))
        try:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            if mode == 'chunked-limit':
                self.send_header('Transfer-Encoding', 'chunked')
            else:
                self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            if status == 302:
                self.send_header('Location', '/must-not-follow')
            self.end_headers()
            if mode == 'body-timeout':
                self.wfile.write(body[:1])
                self.wfile.flush()
                time.sleep(1.2)
                self.wfile.write(body[1:])
            elif mode == 'chunked-limit':
                for offset in range(0, len(body), 4096):
                    chunk = body[offset:offset + 4096]
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.write(b'0\r\n\r\n')
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True
# endregion fixture


def run_command(args, cwd, env=None, timeout=180):
    p = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    # Do not echo request bodies or inherited credentials in diagnostics.
    require(p.returncode == 0, f'Command failed ({p.returncode}): {p.stderr[:500]}')
    return p.stdout


def messages_ok(messages):
    pending, seen = set(), set()
    for message in messages:
        if message['role'] == 'tool':
            require(message['tool_call_id'] in pending, 'Tool result identity')
            pending.remove(message['tool_call_id'])
        else:
            require(not pending, 'Incomplete request history')
            for call in message.get('tool_calls', []):
                require(call['id'] not in seen, 'Duplicate request call')
                seen.add(call['id'])
                pending.add(call['id'])
    require(not pending, 'Missing result')


# region independent-grade
def grade_actual(report, case):
    state = report['state']
    try:
        answer = json.loads(state['answer'])
    except (TypeError, json.JSONDecodeError):
        answer = None
    schema = isinstance(answer, dict) and set(answer) == {'command', 'source'} and answer['source'] == 'README.md' and (answer['command'] is None or isinstance(answer['command'], str))
    correct = schema and answer['command'] == case['expected']
    grounded = state['reads'] == 1 and state['read_result'] is not None
    return {'schema_valid': schema, 'answer_correct': correct, 'read_observed': grounded,
            'task_pass': state['stop'] == 'answered' and schema and correct and grounded}
# endregion independent-grade


def normalize(report):
    report = json.loads(json.dumps(report))
    report.pop('elapsed_ms')
    for exchange in report['exchanges']:
        exchange.pop('elapsed_ms')
    return report


def invoke(binary, folder, case, mode, server=None):
    args = [str(binary), 'fixture', f'http://127.0.0.1:{server.server_port}/fixture/{mode}'] if server else [str(binary), 'live']
    start = len(server.records) if server else 0
    stdout = run_command(args + [str(HERE / 'cases.json'), case['id'], str(folder)], HERE, timeout=110)
    raw = json.loads(stdout)
    require(raw == json.loads((folder / 'run.json').read_text()), 'Saved report differs from stdout')
    require(raw['grade'] == grade_actual(raw, case), 'Independent grader differs')
    require(raw['state']['attempts'] <= 3 and raw['state']['reads'] <= 1, 'Budget exceeded')
    readme = folder / 'README.md'
    require(readme.exists() == (case['readme'] is not None), 'README presence changed')
    if readme.exists():
        require(readme.read_text() == case['readme'], 'Agent changed fixture')
    require(set(p.name for p in folder.iterdir()) <= {'README.md', 'run.json'}, 'Unexpected file effect')
    if raw['state']['reads'] == 1:
        expected_read = {'ok':True, 'text':case['readme']} if case['readme'] is not None else {'ok':False, 'error':'not_found'}
        # Rejected second calls replace read_result with their error; original successful read remains in history.
        actual_reads = [json.loads(m['content']) for m in raw['state']['messages'] if m['message_type']=='tool']
        require(actual_reads[0] == expected_read, 'Actual read result differs from fixture on disk')

    for exchange in raw['exchanges']:
        messages_ok(exchange['request']['messages'])
        require(exchange['request']['messages'][0]['role'] == 'system', 'Missing policy')
        require(exchange['request']['messages'][1] == {'role':'user', 'content':"Inspect this project's README.md and report its startup command."}, 'Label leaked into user message')
        require('Authorization' not in json.dumps(exchange), 'Header leaked')
    records = []
    if server:
        # Timeout handler may still be finishing; it is joined before final publication below.
        records = server.records[start:]
        require(len(records) == raw['state']['attempts'], mode + ': received requests differ')
        for i, record in enumerate(records):
            require(record['request'] == raw['exchanges'][i]['request'], 'Actual wire request differs')
            exchange = raw['exchanges'][i]
            if exchange['response'] is not None:
                require(record['response'] == exchange['response'], 'Actual response differs')
    return raw, records


# region metrics
def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def summary(runs):
    samples = [r['elapsed_ms'] for r in runs]
    known = all(r['usage'] is not None for r in runs)
    return {'attempted_tasks':len(runs), 'adapter_pass':sum(r['adapter_ok'] for r in runs),
            'task_pass':sum(r['grade']['task_pass'] for r in runs),
            'http_requests':sum(r['state']['attempts'] for r in runs),
            'usage':{'prompt_tokens':sum(r['usage']['prompt_tokens'] for r in runs),
                     'completion_tokens':sum(r['usage']['completion_tokens'] for r in runs)} if known else None,
            'samples_ms':samples,
            'latency_ms':{'n':len(samples), 'min':min(samples), 'p50':percentile(samples,50),
                          'p95':percentile(samples,95), 'max':max(samples)},
            'cost_usd':None, 'cost_reason':('No dated price table; local fixture tokens are synthetic' if runs[0]['mode']=='fixture' else 'No dated price table; provider bill not reconciled')}
# endregion metrics


def suite(binary, destination):
    destination.mkdir()  # Refuse existing results.
    cases = json.loads((HERE / 'cases.json').read_text())['cases']
    protocol, quality, outputs, measurements = [], {}, {}, {}
    server = Fixture()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        for mode, (ok, stop, reads, requests) in PROTOCOL.items():
            raw, wire = invoke(binary, destination / ('protocol-' + mode), cases[0], mode, server)
            require((raw['adapter_ok'], raw['state']['stop'], raw['state']['reads'], len(wire)) == (ok, stop, reads, requests), mode + ': outcome differs')
            expected_task = mode in ['normal', 'missing-usage']
            require(raw['grade']['task_pass'] == expected_task, mode + ': wrong grade')
            require((raw['usage'] is None) == (mode == 'missing-usage' or not ok), mode + ': usage coverage')
            row = normalize(raw)
            row.update(scenario=mode, wire=wire)
            protocol.append(row)
            outputs['protocol-' + mode] = '\n'.join([
                f'scenario={mode} adapter_ok={str(ok).lower()} stop={stop}',
                f'model_attempts={raw["state"]["attempts"]} file_reads={reads} received_http={len(wire)}',
                f'answer_correct={str(raw["grade"]["answer_correct"]).lower()} task_pass={str(raw["grade"]["task_pass"]).lower()}',
                'usage=' + ('unknown' if raw['usage'] is None else json.dumps(raw['usage'], sort_keys=True, separators=(',', ':'))),
                'cost_usd=unknown live_provider=not_run']) + '\n'
        for profile in ['quality-good', 'quality-bad']:
            runs, rows = [], []
            # Same ordered tasks and three repeats for both profiles. Repeats measure harness reproducibility.
            for repeat in range(1, 4):
                for case in cases:
                    raw, wire = invoke(binary, destination / f'{profile}-{repeat}-{case["id"]}', case, profile, server)
                    require(raw['adapter_ok'], 'Quality run protocol failure')
                    expected = profile == 'quality-good' or case['id'] == 'node'
                    require(raw['grade']['task_pass'] == expected, 'Quality fixture grade')
                    runs.append(raw)
                    rows.append(dict(repeat=repeat, report=normalize(raw), wire=wire))
            measured = summary(runs)
            quality[profile] = rows
            measurements[profile] = measured
            outputs[profile] = '\n'.join([
                f'profile={profile} tasks={len(runs)} distinct_tasks={len(cases)} repeats=3',
                f'adapter_pass={measured["adapter_pass"]}/{len(runs)} task_pass={measured["task_pass"]}/{len(runs)}',
                f'http_requests={measured["http_requests"]} file_reads={sum(r["state"]["reads"] for r in runs)}',
                'usage_origin=fixture_synthetic prompt_tokens=' + str(measured['usage']['prompt_tokens']) + ' completion_tokens=' + str(measured['usage']['completion_tokens']),
                'cost_usd=unknown latency_scope=local_loopback live_provider=not_run']) + '\n'
    finally:
        server.shutdown()
        server.server_close()  # Wait for outstanding timeout handler too.
        thread.join()
    # All handler records now have a finished status/body hash. JSON-copy severs mutable references.
    evidence = json.loads(json.dumps({'protocol':protocol, 'quality':quality, 'fixture_closed':not thread.is_alive(),
        'received_http':len(server.records), 'live_provider':{'status':'not_run', 'reason':'No external requests in fixture validation'}}))
    return evidence, outputs, measurements


def live_manifest(runs):
    return {'recorded_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'python': platform.python_version(), 'platform': platform.platform(),
            'cases_sha256': digest((HERE / 'cases.json').read_bytes()),
            'source_sha256': {str(p.relative_to(HERE)): digest(p.read_bytes()) for p in [HERE/'Cargo.toml', HERE/'Cargo.lock', HERE/'lab.py', *sorted((HERE/'src').glob('*.rs'))]},
            'requested_models': sorted({r['requested_model'] for r in runs}),
            'response_models': sorted({e['response_model'] for r in runs for e in r['exchanges'] if e['response_model']}),
            'transport': 'HTTPS, fixed api.deepseek.com endpoint, direct connection, no redirects',
            'prompt_sha256': sorted({digest(json_bytes(e['request']['messages'][:2])) for r in runs for e in r['exchanges']})}


def live(binary, destination):
    destination.mkdir()
    cases = json.loads((HERE / 'cases.json').read_text())['cases']
    runs = []
    for repeat in range(1, 4):
        for case in cases:
            report, _ = invoke(binary, destination / f'live-{repeat}-{case["id"]}', case, 'live')
            runs.append(report)
            # Authentication, rate limiting or identity drift stop the batch, preserving attempted denominator.
            if report['state']['stop'] in ['authentication', 'rate_limited', 'model_mismatch']:
                result = {'status':'stopped', 'planned_tasks':12, 'summary':summary(runs), 'manifest':live_manifest(runs), 'runs':runs}
                (destination / 'live-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
                return result
    result = {'status':'executed', 'planned_tasks':12, 'summary':summary(runs), 'manifest':live_manifest(runs), 'runs':runs}
    (destination / 'live-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['fixture', 'live'])
    parser.add_argument('binary', type=Path)
    parser.add_argument('new_directory', type=Path)
    args = parser.parse_args()
    if args.mode == 'live':
        result = live(args.binary.resolve(), args.new_directory.resolve())
    else:
        evidence, outputs, measurements = suite(args.binary.resolve(), args.new_directory.resolve())
        for name, output in outputs.items():
            (args.new_directory / (name + '.txt')).write_text(output)
        result = dict(evidence=evidence, measurements=measurements)
        (args.new_directory / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
