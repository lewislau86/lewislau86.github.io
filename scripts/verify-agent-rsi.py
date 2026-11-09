"""Verify bounded policy search, trusted gates, release pointers and the actual archive."""
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
SOURCE = ROOT / 'docs/public/learn-agent-rust/code/agent-rsi'
OUTPUT = ROOT / 'docs/public/learn-agent-rust/outputs'
EVIDENCE = ROOT / 'scripts/data/learn-agent-rust/p06-results.json'
ARCHIVE = ROOT / 'docs/public/learn-agent-rust/agent-rsi-lab.zip'
SCENARIOS = ['normal', 'overfit', 'evaluator-tamper', 'permission-escalation', 'budget', 'stale-parent', 'rollback']
EXPECTED = {
    'normal': ('Robust', 6, 3, 24),
    'overfit': ('Baseline', 2, 1, 8),
    'evaluator-tamper': ('Baseline', 2, 0, 0),
    'permission-escalation': ('Baseline', 2, 0, 0),
    'budget': ('Baseline', 2, 0, 0),
    'stale-parent': ('Trim', 3, 1, 8),
    'rollback': ('Baseline', 2, 1, 8),
}


def run(command, source, env):
    return subprocess.run(command, cwd=source, env=env, text=True, capture_output=True, check=True).stdout


def verify(source, workspace):
    env = dict(os.environ, RUSTUP_TOOLCHAIN='1.99.1', CARGO_TARGET_DIR=str(workspace / 'target'))
    run(['cargo', 'fmt', '--check'], source, env)
    run(['cargo', 'test', '--locked', '--offline'], source, env)
    run(['cargo', 'clippy', '--locked', '--offline', '--', '-D', 'warnings'], source, env)
    run(['cargo', 'build', '--locked', '--offline'], source, env)
    binary = workspace / 'target/debug/agent-rsi-lab'
    outputs, rows = {}, []
    for scenario, seed in [(s, 1) for s in SCENARIOS] + [('normal', 2), ('normal', 3)]:
        root = workspace / ('run-' + scenario + str(seed))
        result = run([str(binary), scenario, str(root), str(seed)], source, env)
        deployed, score, attempts, evaluations = EXPECTED[scenario]
        assert f'baseline_test=2/6 selected_test={score}/6 deployed={deployed}' in result, result
        assert f'search_attempts={attempts} candidate_case_evaluations={evaluations}' in result
        assert 'baseline_preserved=true pointer_matches_policy=true' in result
        assert 'workspace_removed=true' in result and not root.exists()
        reason = {'overfit': 'no_validated_gain', 'evaluator-tamper': 'evaluator_changed',
                  'permission-escalation': 'permission_expanded', 'budget': 'search_budget',
                  'stale-parent': 'stale_parent'}.get(scenario)
        if reason:
            assert 'decision=reject reason=' + reason in result
        if scenario == 'rollback':
            assert 'runtime_alarm=true rollback_to=revision-0' in result
        candidates = [dict(policy=p, dev=int(d), validation=int(v)) for p, d, v in
                      re.findall(r'candidate=(\w+) dev=(\d)/4 validation=(\d)/4', result)]
        if scenario == 'normal':
            observed = {r['policy']: (r['dev'], r['validation']) for r in candidates}
            assert observed == {'Trim': (3, 2), 'Memorize': (4, 1), 'Robust': (4, 4)}
        name = 'p06-' + scenario + (f'-order-{seed}' if seed != 1 else '') + '.txt'
        outputs[name] = result
        rows.append(dict(scenario=scenario, order_seed=seed, candidates=candidates,
                         deployed=deployed, baseline_test=2, selected_test=score,
                         test_cases=6, search_attempts=attempts,
                         candidate_case_evaluations=evaluations))
    # Existing directories must survive a refused invocation unchanged.
    existing = workspace / 'existing'
    existing.mkdir()
    (existing / 'keep.txt').write_text('keep\n')
    refusal = subprocess.run([str(binary), 'normal', str(existing), '1'], capture_output=True)
    assert refusal.returncode != 0 and (existing / 'keep.txt').read_text() == 'keep\n'
    invalid = subprocess.run([str(binary), 'unknown', str(existing), '1'], capture_output=True)
    assert invalid.returncode == 2
    return outputs, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    names = ['.gitignore', 'Cargo.lock', 'Cargo.toml', 'README.md', 'rust-toolchain.toml', 'src/main.rs']
    files = {name: (SOURCE / name).read_bytes() for name in names}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo('agent-rsi/' + name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value)
    content = buffer.getvalue()
    if args.check:
        assert ARCHIVE.read_bytes() == content, 'Archive stale'
        content = ARCHIVE.read_bytes()
    with tempfile.TemporaryDirectory(prefix='agent-rsi-') as directory:
        workspace = Path(directory)
        outputs, rows = verify(SOURCE, workspace / 'source-run')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert set(archive.namelist()) == {'agent-rsi/' + n for n in names}
            archive.extractall(workspace / 'extracted')
        extracted_outputs, extracted_rows = verify(workspace / 'extracted/agent-rsi', workspace / 'archive-run')
        assert outputs == extracted_outputs and rows == extracted_rows
    evidence = dict(schema_version=1, rust='1.99.1', model='deterministic finite policy fixture',
                    scope='bounded policy search; no recursive meta-improvement or external model',
                    development_cases=4, validation_cases=4, test_cases=6,
                    order_seeds=[1, 2, 3], unique_candidate_orders=2, rust_tests=4,
                    archive_replayed=True, cli_refusals=2,
                    files_sha256={n: hashlib.sha256(b).hexdigest() for n, b in files.items()},
                    outputs_sha256={n: hashlib.sha256(v.encode()).hexdigest() for n, v in outputs.items()},
                    scenarios=rows)
    targets = {OUTPUT / n: s.encode() for n, s in outputs.items()}
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + '\n').encode()
    targets[ARCHIVE] = content
    for path, expected in targets.items():
        if args.check:
            assert path.read_bytes() == expected, 'Stale: ' + str(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    print('P06 verified: 4 Rust tests, 9 runs + 2 CLI refusals, source and extracted archive; outputs and hashes match')


if __name__ == '__main__':
    main()
