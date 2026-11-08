"""Verify actual lexical retrieval, evidence boundaries and the independently extracted zip."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/public/learn-agent-rust/code/retrieval-augmented-generation'
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
ARCHIVE = PUBLIC / 'retrieval-augmented-generation.zip'
EVIDENCE = ROOT / 'scripts/data/learn-agent-rust/k01-results.json'
NAMES = ['.gitignore', 'Cargo.toml', 'Cargo.lock', 'README.md', 'rust-toolchain.toml',
         'src/main.rs', 'corpus/release.md', 'corpus/operations.md',
         'corpus/untrusted.md', 'corpus/private.md']


def run(command, source, env):
    result = subprocess.run(command, cwd=source, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def verify(source, workspace):
    env = dict(os.environ, RUSTUP_TOOLCHAIN='1.99.1', CARGO_TARGET_DIR=str(workspace / 'target'))
    for command in [['cargo', 'fmt', '--check'], ['cargo', 'test', '--locked', '--offline'],
                    ['cargo', 'clippy', '--locked', '--offline', '--', '-D', 'warnings'],
                    ['cargo', 'build', '--locked', '--offline']]:
        run(command, source, env)
    binary = workspace / 'target/debug/rag-lab'
    corpus = workspace / 'case'
    output = run([str(binary), 'suite', str(corpus)], source, env)
    checks = ['scenario=normal\nquote=Upgrade v2 requires Rust 1.99.1.',
              'scenario=no-hit\nabstain=no_evidence',
              'scenario=scope visible_hits=1 private_leak=false',
              'scenario=budget\nabstain=no_evidence',
              'scenario=injection quoted_as_data=true generator=fixture actions=0',
              'unsupported_quote_rejected=true unknown_id_rejected=true',
              'recall_at_2=3/4 mrr_at_2=0.750',
              'scenario=lexical-gap\nabstain=no_evidence',
              'scenario=stale rejected=stale_index',
              'scenario=updated\nquote=Upgrade v2 requires Rust 2.00.0.',
              'scenario=deleted rejected=source_missing rebuilt_hits=0']
    for expected in checks:
        assert expected in output, expected
    assert output.count('scenario=') == 11
    assert not (corpus / 'release.md').exists()
    assert (corpus / 'private.md').read_bytes() == (source / 'corpus/private.md').read_bytes()
    assert (corpus / 'operations.md').read_bytes() == (source / 'corpus/operations.md').read_bytes()
    normal = run([str(binary), 'query', str(source / 'corpus'), 'A', 'upgrade Rust'], source, env)
    assert 'quote=' + (source / 'corpus/release.md').read_text().splitlines()[2] in normal
    assert 'citation=A/release.md:L3-L3@' in normal
    gap = run([str(binary), 'query', str(source / 'corpus'), 'A', 'revert disaster'], source, env)
    assert gap == 'abstain=no_evidence\n'
    # Independently label/rank the four public queries by invoking the CLI.
    top1 = []
    for query, file, prefix in [('upgrade Rust', 'release.md', 'Upgrade'),
                                ('database backup', 'operations.md', 'Backup'),
                                ('rollback', 'release.md', 'Rollback'),
                                ('revert disaster', 'release.md', 'Rollback')]:
        result = run([str(binary), 'query', str(source / 'corpus'), 'A', query], source, env)
        top1.append(('citation=A/' + file + ':') in result and ('quote=' + prefix) in result)
    assert top1 == [True, True, True, False]
    unknown = run([str(binary), 'query', str(source / 'corpus'), 'unknown', 'upgrade'], source, env)
    assert unknown == 'abstain=no_evidence\n'
    # Refusing an existing destination must preserve its complete file set/bytes.
    before = {p.name: p.read_bytes() for p in corpus.iterdir()}
    refused = subprocess.run([str(binary), 'suite', str(corpus)], capture_output=True)
    assert refused.returncode == 2
    assert before == {p.name: p.read_bytes() for p in corpus.iterdir()}
    invalid = subprocess.run([str(binary), 'unknown'], capture_output=True)
    assert invalid.returncode == 2
    return {'k01-suite.txt': output, 'k01-query.txt': normal, 'k01-lexical-gap.txt': gap}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in NAMES}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo('retrieval-augmented-generation/' + name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value)
    content = buffer.getvalue()
    if args.check:
        assert ARCHIVE.read_bytes() == content, 'Archive stale'
        content = ARCHIVE.read_bytes()
    with tempfile.TemporaryDirectory(prefix='agent-rag-') as temp:
        work = Path(temp)
        outputs = verify(SOURCE, work / 'source')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert set(archive.namelist()) == {'retrieval-augmented-generation/' + n for n in NAMES}
            archive.extractall(work / 'extracted')
        replay = verify(work / 'extracted/retrieval-augmented-generation', work / 'archive')
        assert outputs == replay
    evidence = dict(schema_version=1, rust='1.99.1', rust_tests=8,
                    scope='actual lexical retrieval; deterministic extractive generation fixture',
                    model='no neural model', scenarios=11, labeled_queries=4,
                    recall_at_2=0.75, mrr_at_2=0.75, held_out=False,
                    archive_replayed=True, cli_refusals=2,
                    files_sha256={n: hashlib.sha256(v).hexdigest() for n, v in files.items()},
                    outputs_sha256={n: hashlib.sha256(v.encode()).hexdigest() for n, v in outputs.items()})
    targets = {PUBLIC / 'outputs' / n: v.encode() for n, v in outputs.items()}
    targets[ARCHIVE] = content
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + '\n').encode()
    for path, expected in targets.items():
        if args.check:
            assert path.read_bytes() == expected, 'Stale: ' + str(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    print('K01 verified: 8 Rust tests, 11 scenarios, 4 labeled queries, source and extracted archive; outputs and hashes match')


if __name__ == '__main__':
    main()
