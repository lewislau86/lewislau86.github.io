"""Verify the independent R02 Cargo package and generate reproducible course artifacts.

python3 scripts/verify-learn-agent-rust-r02.py [--check]
First build needs network for the pinned Git revisions and Cargo dependencies.
"""
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
PACKAGE = ROOT / "docs/public/learn-agent-rust/code/tools-and-graph"
OUTPUT = ROOT / "docs/public/learn-agent-rust/outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r02-results.json"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/tools-and-graph.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore", "src/main.rs"]
CASES = ["normal", "batch", "unknown-tool", "invalid-json", "invalid-args",
         "missing-file", "duplicate-id", "zero-budget", "turn-limit"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, cwd, env):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            item = zipfile.ZipInfo("tools-and-graph/" + name, (2020, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, (PACKAGE / name).read_bytes())
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env.setdefault("CARGO_TARGET_DIR", str(ROOT / ".cache/learn-agent-r02-target"))
    packed = archive()
    targets = {ARCHIVE: packed}
    with tempfile.TemporaryDirectory(prefix="learn-agent-r02-") as temp:
        # Exercise exactly the published archive, without sibling checkouts or website files.
        with zipfile.ZipFile(io.BytesIO(packed)) as bundle:
            bundle.extractall(temp)
        cwd = Path(temp) / "tools-and-graph"
        command(["cargo", "fmt", "--check"], cwd, env)
        command(["cargo", "test", "--locked", "--quiet"], cwd, env)
        command(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], cwd, env)
        summary = command(["cargo", "run", "--locked", "--quiet"], cwd, env)
        targets[OUTPUT / "r02-summary.txt"] = summary.encode()
        reports = []
        for name in CASES:
            output = command(["cargo", "run", "--locked", "--quiet", "--", "--json", name], cwd, env)
            report = json.loads(output)
            if report["scenario"] != name or report["equal"] is not True:
                raise ValueError("Invalid scenario report: " + name)
            reports.append(report)
            targets[OUTPUT / ("r02-" + name + ".json")] = output.encode()
        rustc = command(["rustc", "--version"], cwd, env).strip()
    evidence = dict(scope="R02 pinned two-library integration; scripted LLM; real temporary filesystem; memory only",
                    source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES},
                    archive_sha256=sha(packed), rustc=rustc, scenarios=reports)
    # Preserve the recorded environment when checking from another compatible host.
    if args.check and DATA.exists():
        evidence["rustc"] = json.loads(DATA.read_text())["rustc"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R02 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R02: 9 scenario pairs, message contracts, fmt, tests and Clippy passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
