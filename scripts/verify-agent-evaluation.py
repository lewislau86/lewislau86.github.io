"""P03: verify local HTTP contracts and graded task results independently of live providers."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
SOURCE = PUBLIC / 'code/model-evaluation'
DATA = ROOT / 'scripts/data/learn-agent-rust/p03-results.json'
ARCHIVE = PUBLIC / 'model-evaluation-lab.zip'
CHAPTER = ROOT / 'docs/learn-agent-rust/model-evaluation.md'
FILES = ['Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.gitignore', 'README.md', 'cases.json', 'lab.py'] + [
    'src/' + name + '.rs' for name in ['main', 'provider', 'agent', 'tests']]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=300)
    require(result.returncode == 0, '{}\n{}\n{}'.format(args, result.stdout, result.stderr))
    return result.stdout


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_lab(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_measurements(lab, measurements):
    for row in measurements.values():
        values = row['samples_ms']
        require(len(values) == row['attempted_tasks'] == 12 and all(v >= 0 for v in values), 'Latency coverage')
        require(row['latency_ms'] == dict(n=12, min=min(values), max=max(values), p50=lab.percentile(values, 50),
                                        p95=lab.percentile(values, 95)), 'Measured percentile arithmetic')
        require(row['cost_usd'] is None and row['http_requests'] == 24, 'Wrong fixture metrics')
    require(lab.percentile([1, 2, 3, 4], 50) == 2 and lab.percentile([1, 2, 3, 4], 95) == 4, 'Percentile definition')


def package(contents):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        for name, value in sorted(contents.items()):
            info = zipfile.ZipInfo('model-evaluation-lab/' + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, value, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def chapter_bytes(data):
    text = CHAPTER.read_text()
    tables = {}
    table = ['| 场景 | 适配器通过 | 停止原因 | 实际读取 | 任务完成 |', '| --- | --- | --- | --- | --- |']
    for r in data['evidence']['protocol']:
        table.append('| `{}` | {} | `{}` | {} | {} |'.format(r['scenario'], '是' if r['adapter_ok'] else '否',
                     r['state']['stop'], r['state']['reads'], '是' if r['grade']['task_pass'] else '否'))
    tables['protocol'] = table
    table = ['| 夹具策略 | 适配通过 / 尝试任务 | 完成 / 尝试任务 | 实际 HTTP | 费用 |', '| --- | --- | --- | --- | --- |']
    for name, rows in data['evidence']['quality'].items():
        reports = [r['report'] for r in rows]
        table.append('| `{}` | {} / {} | {} / {} | {} | 未知（夹具无真实计费） |'.format(name,
                     sum(r['adapter_ok'] for r in reports), len(rows), sum(r['grade']['task_pass'] for r in reports),
                     len(rows), sum(r['state']['attempts'] for r in reports)))
    tables['quality'] = table
    table = ['| 本地夹具策略 | 任务数 | 最小 ms | p50 ms | p95 ms | 最大 ms |', '| --- | --- | --- | --- | --- | --- |']
    for name, row in data['measured_snapshot'].items():
        m = row['latency_ms']
        table.append('| `{}` | {} | {:.3f} | {:.3f} | {:.3f} | {:.3f} |'.format(name,m['n'],m['min'],m['p50'],m['p95'],m['max']))
    tables['latency'] = table
    for name, table in tables.items():
        start, end = f'<!-- p03-{name}:start -->', f'<!-- p03-{name}:end -->'
        require(text.count(start) == text.count(end) == 1, 'Missing chapter markers: ' + name)
        before, rest = text.split(start)
        _, after = rest.split(end)
        text = before + start + '\n\n' + '\n'.join(table) + '\n\n' + end + after
    return text.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / '.cache/learn-agent-p03-target'))
    # Explicit fixture mode never reads or sends inherited provider credentials.
    env.pop('DEEPSEEK_API_KEY', None)
    env.pop('P03_MODEL', None)
    with tempfile.TemporaryDirectory(prefix='agent-p03-') as directory:
        directory = Path(directory)
        source = directory / 'source'
        for name, value in files.items():
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(value)
        command(['cargo', 'fmt', '--', '--check'], source, env)
        tested = command(['cargo', 'test', '--locked', '--', '--test-threads=1'], source, env)
        tests = re.findall(r'^test tests::(\w+) \.\.\. ok$', tested, re.M)
        require(len(tests) == 10 and '10 passed; 0 failed' in tested, 'Rust tests')
        command(['cargo', 'clippy', '--locked', '--all-targets', '--', '-D', 'warnings'], source, env)
        command(['cargo', 'build', '--locked'], source, env)
        lab = load_lab(source / 'lab.py', 'p03_source_lab')
        evidence, outputs, measurements = lab.suite(Path(env['CARGO_TARGET_DIR']) / 'debug/learn-agent-p03', directory / 'runs')
        validate_measurements(lab, measurements)
        require(len(evidence['protocol']) == 27 and sum(len(v) for v in evidence['quality'].values()) == 24,
                'Coverage changed')
        require(evidence['fixture_closed'] and evidence['received_http'] == 80 and evidence['live_provider']['status'] == 'not_run', 'Service scope')
        environment = dict(rustc=command(['rustc', '--version'], source, env).strip(),
                           host=command(['rustc', '-vV'], source, env).split('host: ')[1].splitlines()[0],
                           python=command(['python3', '--version'], source, env).strip())
        if args.check and DATA.exists():
            previous = json.loads(DATA.read_text())
            environment, measurements = previous['environment'], previous['measured_snapshot']
            validate_measurements(lab, measurements)
        data = dict(scope='P03 real loopback HTTP, pinned two-library loop and files; deterministic fixture responses, not live provider quality',
                    environment=environment, files_sha256={n:digest(v) for n,v in files.items()},
                    regression_tests=tests, evidence=evidence, measured_snapshot=measurements)
        serialized = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
        contents = dict(files)
        contents.update({'outputs/' + n + '.txt':v.encode() for n,v in outputs.items()})
        contents['evidence.json'] = serialized
        archive = package(contents)
        published = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else archive
        extracted = directory / 'download'
        with zipfile.ZipFile(io.BytesIO(published)) as z:
            z.extractall(extracted)
        downloaded = extracted / 'model-evaluation-lab'
        download_env = dict(env, CARGO_TARGET_DIR=str(ROOT / '.cache/learn-agent-p03-download-target'))
        command(['cargo', 'build', '--locked', '--offline'], downloaded, download_env)
        downloaded_lab = load_lab(downloaded / 'lab.py', 'p03_download_lab')
        again, again_outputs, new_measurements = downloaded_lab.suite(Path(download_env['CARGO_TARGET_DIR']) / 'debug/learn-agent-p03', directory / 'repeat')
        validate_measurements(downloaded_lab, new_measurements)
        require(evidence == again and outputs == again_outputs, 'Final downloaded archive differs')
        # Check every output and source, not only the code that happened to execute.
        require(json.loads((downloaded / 'evidence.json').read_text()) == data, 'Embedded evidence differs')
        require(all((downloaded / n).read_bytes() == v for n,v in files.items()), 'Downloaded sources differ')
        require(all((downloaded / 'outputs' / (n + '.txt')).read_text() == v for n,v in outputs.items()), 'Downloaded output differs')
    artifacts = {DATA:serialized, ARCHIVE:archive, CHAPTER:chapter_bytes(data)}
    artifacts.update({PUBLIC / 'outputs' / ('p03-' + name + '.txt'):value.encode() for name,value in outputs.items()})
    chapter = artifacts[CHAPTER].decode()
    snippets = re.findall(r'<<< @/public/learn-agent-rust/code/model-evaluation/([\w/.-]+)#([\w-]+)', chapter)
    require(len(snippets) >= 7, 'Missing code imports')
    for filename, region in snippets:
        content = files[filename].decode()
        prefix = '# ' if filename.endswith('.py') else '// '
        require(content.count(prefix + 'region ' + region + '\n') == content.count(prefix + 'endregion ' + region + '\n') == 1, 'Bad snippet: ' + region)
    for name in re.findall(r'<<< @/public/learn-agent-rust/outputs/p03-([\w-]+).txt', chapter):
        require(name in outputs, 'Unknown output')
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, 'Stale P03 artifact: ' + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print('P03: 27 protocol/host cases + 24 graded tasks, 80 real HTTP requests per round; 10 Rust tests, Clippy, independent grades/wire/files, fixture thread cleanup and extracted final archive offline rerun passed; ' + ('artifacts checked' if args.check else 'artifacts saved') + '; live provider NOT RUN')


if __name__ == '__main__':
    main()
