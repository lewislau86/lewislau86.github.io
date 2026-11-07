"""Verify R13 bounded native workers, actual artifacts, cancellation and extracted package."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/learn-agent-rust"
SOURCE = PUBLIC / "code/background-tasks.rs"
README = PUBLIC / "code/background-tasks-README.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r13-results.json"
ARCHIVE = PUBLIC / "background-tasks-lab.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/background-tasks.md"
# started, joined, peak, active, retained, dropped notices, partial files, published files
CASES = {
    "normal": (1, 1, 1, 0, 1, 0, 0, 1),
    "cancel": (1, 1, 1, 0, 1, 0, 0, 0),
    "cancel-before-work": (1, 1, 1, 0, 1, 0, 0, 0),
    "late-cancel": (1, 1, 1, 0, 1, 0, 0, 1),
    "repeat-cancel": (1, 1, 1, 0, 1, 0, 0, 0),
    "capacity": (3, 3, 2, 0, 3, 2, 0, 1),
    "failure": (1, 1, 1, 0, 1, 0, 0, 0),
    "panic": (1, 1, 1, 0, 1, 0, 0, 0),
    "notifications": (2, 2, 2, 0, 2, 1, 0, 2),
    "unknown": (0, 0, 0, 0, 0, 0, 0, 0),
    "shutdown": (2, 2, 2, 0, 2, 1, 0, 0),
    "drop": None,
    "history": (6, 6, 1, 0, 4, 0, 0, 4),
    "closed": (0, 0, 0, 0, 0, 0, 0, 0),
}
EXPECTED_LINES = {
    "normal": ["start id=1 query=Running", "foreground=can_handle_another_request", "checkpoint progress=1 partial_files=1", "query=Completed notices=[1]"],
    "cancel": ["cancel=Accepted", "query=Cancelled"],
    "cancel-before-work": ["cancel=Accepted", "query=Cancelled"],
    "late-cancel": ["cancel=TooLate query=Completed"],
    "repeat-cancel": ["cancel=Accepted", "repeat=AlreadyRequested_or_TooLate", "query=Cancelled"],
    "capacity": ["simultaneously_ready=2 rejected=capacity", "replacement_id=3"],
    "failure": ["query=Failed notices=[1]"],
    "panic": ["query=Failed notices=[1]"],
    "notifications": ["notices=[1] query_1=Completed query_2=Completed"],
    "unknown": ["query=None cancel=Unknown"],
    "shutdown": ["query_1=Cancelled query_2=Cancelled closed=true"],
    "drop": ["drop_returned=true partial_files=0 result_files=0"],
    "history": ["retained=4 first_query=None latest_query=Completed"],
    "closed": ["start_error=closed"],
}


def run(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True,
                          text=True, timeout=30).stdout


def digest(content):
    return hashlib.sha256(content).hexdigest()


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("background-tasks-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def inspect(name, output, root):
    lines = output.splitlines()
    expected = ["scenario=" + name] + EXPECTED_LINES[name]
    if lines[:len(expected)] != expected:
        raise ValueError("Unexpected lifecycle: " + name)
    keys = ["started", "joined", "peak", "active", "records", "dropped_notices", "partial_files", "result_files"]
    if CASES[name] is not None:
        match = re.fullmatch("stats " + " ".join(k + r"=(\d+)" for k in keys), lines[-1])
        if not match or tuple(map(int, match.groups())) != CASES[name] or len(lines) != len(expected) + 1:
            raise ValueError("Wrong resource counts: " + name)
        counts = dict(zip(keys, map(int, match.groups())))
    else:
        if lines != expected:
            raise ValueError("Unexpected Drop report")
        counts = {}
    expected_ids = {"normal": [1], "late-cancel": [1], "capacity": [1],
                    "notifications": [1, 2], "history": [3, 4, 5, 6]}.get(name, [])
    expected_files = ["job-{}.txt".format(i) for i in expected_ids]
    if sorted(p.name for p in root.iterdir()) != expected_files:
        raise ValueError("Actual files differ: " + name)
    for filename in expected_files:
        if (root / filename).read_bytes() != b"chunk=1\nchunk=2\nchunk=3\n":
            raise ValueError("Published artifact is incomplete: " + name)
    return dict(name=name, **counts, published_ids=expected_ids, stdout_sha256=digest(output.encode()))


def check_chapter():
    chapter = CHAPTER.read_text()
    source = SOURCE.read_text()
    for region in re.findall(r"<<< @/public/learn-agent-rust/code/background-tasks.rs#([\w-]+)", chapter):
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing source region: " + region)
    imported = re.findall(r"<<< @/public/learn-agent-rust/outputs/r13-([\w-]+).txt", chapter)
    if any(name not in CASES for name in imported):
        raise ValueError("Unknown R13 output")
    # Explicit rows are machine-checked so the article cannot overstate results.
    for name, counts in CASES.items():
        if counts is not None:
            row = "| `{}` | {} | {} | {} | {} |".format(name, counts[0], counts[1], counts[5], counts[7])
            if row not in chapter:
                raise ValueError("Missing or stale chapter result row: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package = {"background-tasks.rs": SOURCE.read_bytes(), "README.md": README.read_bytes()}
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="agent-r13-verify-") as folder:
        root = Path(folder)
        binary = str(root / "background")
        tests = str(root / "background-tests")
        run(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", binary], root)
        run(["rustc", "--edition=2024", "-D", "warnings", "--test", str(SOURCE), "-o", tests], root)
        test_output = run([tests, "--test-threads=1"], root)
        names = re.findall(r"^test tests::(\w+) \.\.\. ok$", test_output, re.M)
        if len(names) != 12 or "test result: ok. 12 passed; 0 failed;" not in test_output:
            raise ValueError("Regression tests failed")
        results = []
        for name in CASES:
            workspace = root / name
            output = run([binary, name, str(workspace)], root)
            results.append(inspect(name, output, workspace))
            artifacts[PUBLIC / ("outputs/r13-" + name + ".txt")] = output.encode()
            package["outputs/" + name + ".txt"] = output.encode()
        # Verify default temporary workspace cleanup independently of program counters.
        temp_root = root / "auto"
        temp_root.mkdir()
        env = dict(os.environ, TMPDIR=str(temp_root))
        run([binary, "drop"], root, env)
        if list(temp_root.iterdir()):
            raise ValueError("Default workspace leaked")
        existing = root / "existing"
        existing.mkdir()
        (existing / "keep.txt").write_bytes(b"keep\n")
        rejected = subprocess.run([binary, "normal", str(existing)], capture_output=True, timeout=10)
        if rejected.returncode != 1 or list(existing.iterdir()) != [existing / "keep.txt"] or (existing / "keep.txt").read_bytes() != b"keep\n":
            raise ValueError("Existing workspace was modified")
        invalid = subprocess.run([binary, "unknown-scenario"], capture_output=True, timeout=10)
        if invalid.returncode != 2 or b"usage:" not in invalid.stderr:
            raise ValueError("Invalid scenario must fail")
        environment = dict(rustc=run(["rustc", "--version"], root).strip(), platform=platform.platform())
    check_chapter()
    if args.check and DATA.exists():
        environment = json.loads(DATA.read_text())["environment"]
    evidence = dict(scope="R13 native threads and local file I/O; controlled permits; process-local manager; no model or framework integration",
                    source_sha256=digest(SOURCE.read_bytes()), readme_sha256=digest(README.read_bytes()),
                    environment=environment, limits=dict(active=2, history=4, notification_buffer=1, chunks_per_job=3),
                    regression_tests=names, scenarios=results)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    artifacts[DATA] = serialized
    package["evidence.json"] = serialized
    artifacts[ARCHIVE] = archive_bytes(package)
    content = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else artifacts[ARCHIVE]
    with tempfile.TemporaryDirectory(prefix="agent-r13-download-") as folder:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(folder)
        project = Path(folder) / "background-tasks-lab"
        binary = str(project / "background")
        run(["rustc", "--edition=2024", "-D", "warnings", "background-tasks.rs", "-o", binary], project)
        for name in CASES:
            workspace = Path(folder) / name
            output = run([binary, name, str(workspace)], project)
            inspect(name, output, workspace)
            if output.encode() != package["outputs/" + name + ".txt"]:
                raise ValueError("Extracted package differs: " + name)
    for path, content in artifacts.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R13 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R13: 14 scenarios, 12 Rust tests, actual files and extracted download passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
