"""Run/check the R08 isolated package, outputs, evidence, and final user download.

python3 scripts/verify-agent-compaction.py [--check]
"""
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
PUBLIC = ROOT / "docs/public/learn-agent-rust"
PACKAGE = PUBLIC / "code/context-compaction"
DATA = ROOT / "scripts/data/learn-agent-rust/r08-results.json"
ARCHIVE = PUBLIC / "context-compaction.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/context-compaction.md"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/compact.rs", "src/tests.rs"]
# summary calls, agent calls, reloads, source reads, artifact reads, stop
CASES = {
    "normal": (1, 3, 1, 1, 0, "completed"),
    "small": (0, 2, 0, 1, 0, "completed"),
    "manual": (1, 3, 1, 1, 0, "completed"),
    "micro-only": (0, 3, 1, 1, 0, "completed"),
    "naive-trim": (0, 1, 0, 0, 0, "missing_evidence"),
    "omit-fact": (1, 0, 0, 0, 0, "summary_facts"),
    "invent-fact": (1, 0, 0, 0, 0, "summary_facts"),
    "bad-json": (1, 0, 0, 0, 0, "summary_schema"),
    "summary-error": (1, 0, 0, 0, 0, "summary_error"),
    "summary-large": (1, 0, 0, 0, 0, "summary_size"),
    "summary-input-budget": (0, 0, 0, 0, 0, "summary_input_budget"),
    "archive-error": (0, 0, 0, 0, 0, "archive_error"),
    "hard-budget": (1, 0, 0, 0, 0, "context_budget"),
    "orphan": (0, 0, 0, 0, 0, "invalid_history"),
    "pending": (0, 0, 0, 0, 0, "pending_tools"),
    "retrieve": (1, 4, 1, 1, 1, "completed"),
    "artifact-tamper": (1, 3, 1, 0, 1, "tool_error"),
}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError(" ".join(args) + "\n" + result.stdout + result.stderr)
    return result.stdout


def pack(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo("context-compaction/" + name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def pairs(items):
    pending, seen = set(), set()
    for item in items:
        m = item["message"]
        if m["message_type"] == "tool":
            if m["id"] not in pending:
                return False
            pending.remove(m["id"])
        else:
            if pending:
                return False
            for call in m.get("tool_calls") or []:
                if not call["id"] or call["id"] in seen:
                    return False
                pending.add(call["id"])
                seen.add(call["id"])
    return not pending


def validate(report, expected):
    state = report["state"]
    actual = (report["summary_calls"], state["model_calls"], state["reloads"], state["reads"], state["retrievals"], state["stop"])
    assert actual == expected, (report["scenario"], actual, expected)
    assert report["source_unchanged"] and report["pinned_unchanged"] and report["original_unchanged_on_failure"]
    assert report["transcript_roundtrip"]
    valid = report["scenario"] not in ("orphan", "pending")
    assert report["pairs_valid"] == valid and pairs(state["items"]) == valid
    assert not state["pending"]
    assert state["model_calls"] <= 5 and state["tool_calls"] <= 4 and report["summary_calls"] <= 2
    assert all(n + report["budget"]["reserve"] <= report["budget"]["hard"] for n in state["model_inputs"])
    assert len(state["model_inputs"]) == state["model_calls"]
    integrity = report["artifact_integrity"]
    assert sum(not ok for ok in integrity.values()) == (1 if report["scenario"] == "artifact-tamper" else 0)
    items = state["items"]
    for item in items:
        m = item["message"]
        if m["content"].startswith('{"kind":"history_summary"') or '"kind":"history_summary"' in m["content"]:
            summary = json.loads(m["content"])
            assert m["message_type"] == "human" and summary["trust"] == "historical_data"
            facts = {f["key"]: f for f in summary["summary"]["facts"]}
            assert len(facts) == 4
            assert facts["target"]["value"] == "src/first.rs"
            assert facts["test_status"]["value"] == "未运行测试"
            assert facts["target"]["source"] == "m4"
            assert summary["transcript"] in integrity
    if state["stop"] == "completed":
        answer = items[-1]["message"]["content"]
        assert "src/first.rs" in answer and "未运行测试" in answer
    if not state["model_calls"]:
        assert report["graph_nodes"] == ["PrepareContext"]
    else:
        expected_nodes = [node for _ in range(state["model_calls"] - 1) for node in ("PrepareContext", "ModelTurn", "ExecuteTools")]
        assert report["graph_nodes"] == expected_nodes + ["PrepareContext", "ModelTurn"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package = {name: (PACKAGE / name).read_bytes() for name in FILES}
    targets, reports = {}, []
    env = os.environ.copy()
    # Same fixed dependencies as R07; reuse compiled dependencies locally.
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-r07-target")
    with tempfile.TemporaryDirectory(prefix="agent-r08-verify-") as directory:
        with zipfile.ZipFile(io.BytesIO(pack(package))) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "context-compaction"
        run(["cargo", "fmt", "--check"], folder, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], folder, env)
        match = re.search(r"test result: ok\. (\d+) passed; 0 failed;", tests)
        assert match, tests
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
        for name, expected in CASES.items():
            report = json.loads(run(["cargo", "run", "--locked", "--quiet", "--", "--json", name], folder, env))
            validate(report, expected)
            output = run(["cargo", "run", "--locked", "--quiet", "--", name], folder, env).encode()
            targets[PUBLIC / "outputs" / ("r08-" + name + ".txt")] = output
            package["outputs/" + name + ".txt"] = output
            report["stdout_sha256"] = sha(output)
            reports.append(report)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], folder, env).encode()
        assert output == targets[PUBLIC / "outputs/r08-normal.txt"]
        invalid = subprocess.run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "invalid"], cwd=folder, env=env, capture_output=True)
        assert invalid.returncode != 0
        rustc = run(["rustc", "--version"], folder, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="R08; pinned langchain-rust LLM trait and actual graph-flow; deterministic agent/summarizer; owned temporary files/archives; byte budget, no HTTP/token billing claims",
                    rustc=rustc, tests_passed=int(match[1]),
                    source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES}, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[DATA] = serialized
    package["evidence.json"] = serialized
    targets[ARCHIVE] = pack(package)
    with tempfile.TemporaryDirectory(prefix="agent-r08-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as archive:
            archive.extractall(directory)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], Path(directory) / "context-compaction", env).encode()
        assert output == targets[PUBLIC / "outputs/r08-normal.txt"]
    chapter = CHAPTER.read_text()
    table = ["| 场景 | 摘要调用 | Agent 调用 | 技能重载 / 源码重读 | 停止原因 |", "| --- | --- | --- | --- | --- |"]
    for r in reports:
        s = r["state"]
        table.append(f'| `{r["scenario"]}` | {r["summary_calls"]} | {s["model_calls"]} | {s["reloads"]} / {s["reads"]} | `{s["stop"]}` |')
    start, end = "<!-- r08-results:start -->", "<!-- r08-results:end -->"
    assert chapter.count(start) == chapter.count(end) == 1, "Missing or duplicate R08 result markers"
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    targets[CHAPTER] = (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/context-compaction/([^#\s]+)#([\w-]+)", chapter):
        source = (PACKAGE / filename).read_text()
        assert source.count("// region " + region + "\n") == source.count("// endregion " + region + "\n") == 1, region
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R08 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f'R08: {len(CASES)} scenarios, {match[1]} Rust tests, Clippy, pairs/facts/budgets/rollback, offline and final download passed; ' + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
