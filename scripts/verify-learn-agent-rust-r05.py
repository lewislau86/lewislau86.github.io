"""Verify the independent R05 Cargo package and generate reproducible course artifacts.

python3 scripts/verify-learn-agent-rust-r05.py [--check]
First build needs network for the pinned toolchain and Cargo dependencies.
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
PACKAGE = ROOT / "docs/public/learn-agent-rust/code/todo-planning"
OUTPUT = ROOT / "docs/public/learn-agent-rust/outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r05-results.json"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/todo-planning.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore", "src/main.rs"]
CASES = ["normal", "claims-only", "read-error", "budget-stop", "fresh-session",
         "two-active", "skip-completion", "unknown-status", "duplicate-id",
         "empty-content", "too-many", "remove-item", "changed-content",
         "stale-revision", "reopen-completed", "append-step", "yield-step",
         "permission-denied", "invalid-json", "unknown-field"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, cwd, env):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            item = zipfile.ZipInfo("todo-planning/" + name, (2020, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, (PACKAGE / name).read_bytes())
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env.setdefault("CARGO_TARGET_DIR", str(Path(tempfile.gettempdir()) / "learn-agent-r05-target"))
    packed = archive()
    targets = {ARCHIVE: packed}
    with tempfile.TemporaryDirectory(prefix="learn-agent-r05-") as temp:
        # Exercise exactly the published archive, without sibling checkouts or website files.
        with zipfile.ZipFile(io.BytesIO(packed)) as bundle:
            bundle.extractall(temp)
        cwd = Path(temp) / "todo-planning"
        command(["cargo", "fmt", "--check"], cwd, env)
        command(["cargo", "test", "--locked", "--quiet"], cwd, env)
        command(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], cwd, env)
        summary = command(["cargo", "run", "--locked", "--quiet"], cwd, env)
        targets[OUTPUT / "r05-summary.txt"] = summary.encode()
        reports = []
        for name in CASES:
            output = command(["cargo", "run", "--locked", "--quiet", "--", "--json", name], cwd, env)
            report = json.loads(output)
            if report["scenario"] != name:
                raise ValueError("Invalid scenario report: " + name)
            if "history" in report:
                history = report["history"]
                assert len(history) == report["tool_calls"] * 2
                for index in range(0, len(history), 2):
                    assert history[index]["call"]["call_id"] == history[index + 1]["result"]["call_id"]
            if name == "normal":
                assert report["goal_verified"] and report["all_completed"]
                assert [item["plan"]["revision"] for item in report["inputs"]] == [0, 1, 2, 2, 3, 4, 5]
            if name == "claims-only":
                assert report["all_completed"] and not report["goal_verified"]
            reports.append(report)
            targets[OUTPUT / ("r05-" + name + ".json")] = output.encode()
        rustc = command(["rustc", "--version"], cwd, env).strip()
    evidence = dict(scope="R05 session todo mechanics; scripted model; real temporary README reads; memory only; no framework integration",
                    source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES},
                    archive_sha256=sha(packed), rustc=rustc, scenarios=reports)
    # Preserve the recorded environment when checking from another compatible host.
    if args.check and DATA.exists():
        evidence["rustc"] = json.loads(DATA.read_text())["rustc"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R05 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R05: 20 scenarios, 6 Rust tests, message contracts, fmt and Clippy passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
