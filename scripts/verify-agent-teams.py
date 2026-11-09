"""Run/check the R15 isolated package, outputs, evidence, and final user download.

python3 scripts/verify-agent-teams.py [--check]
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
PACKAGE = PUBLIC / "code/agent-teams"
DATA = ROOT / "scripts/data/learn-agent-rust/r15-results.json"
ARCHIVE = PUBLIC / "agent-teams.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/agent-teams.md"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/team.rs", "src/worker.rs", "src/tests.rs"]
# accepted, model attempts, tool attempts, actual reads, rejected operation
CASES = {
    "normal": (2, 4, 2, 2, None),
    "persistent": (3, 4, 2, 2, None),
    "peer-message": (3, 5, 3, 2, None),
    "mailbox-full": (3, 0, 0, 0, "mailbox_full"),
    "unknown-member": (0, 0, 0, 0, "unknown_member"),
    "duplicate-member": (0, 0, 0, 0, "duplicate_member"),
    "duplicate-message": (1, 0, 0, 0, "duplicate_message"),
    "oversized-message": (0, 0, 0, 0, "message_size"),
    "message-budget": (1, 0, 0, 0, "team_message_budget"),
    "model-budget": (2, 2, 1, 1, None),
    "tool-budget": (2, 4, 1, 1, None),
    "forbidden-path": (1, 2, 1, 0, None),
    "write-denied": (1, 2, 1, 0, None),
    "missing-file": (1, 2, 1, 0, None),
    "model-error": (1, 1, 0, 0, None),
    "context-budget": (1, 0, 0, 0, None),
    "turn-budget": (1, 3, 3, 3, None),
    "cancel-idle": (0, 0, 0, 0, None),
    "cancel-busy": (2, 1, 0, 0, None),
    "receiver-closed": (0, 0, 0, 0, "mailbox_closed"),
    "member-limit": (0, 0, 0, 0, "member_limit"),
    "note-injection": (2, 2, 1, 1, None),
}
STOPS = {
    "model-budget": ["completed", "team_model_budget"],
    "tool-budget": ["completed", "tool_error"],
    "forbidden-path": ["tool_error"], "write-denied": ["tool_error"],
    "missing-file": ["tool_error"], "model-error": ["model_error"],
    "context-budget": ["context_budget"], "turn-budget": ["turn_limit"],
    "cancel-busy": ["cancelled", "cancelled_queued"],
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
            entry = zipfile.ZipInfo("agent-teams/" + name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def check_history(messages):
    pending, seen, results = set(), set(), []
    for m in messages:
        if m["message_type"] == "tool":
            assert m["id"] in pending
            pending.remove(m["id"])
            results.append(json.loads(m["content"]))
        else:
            assert not pending
            for call in m.get("tool_calls") or []:
                assert call["id"] and call["id"] not in seen
                pending.add(call["id"])
                seen.add(call["id"])
    assert not pending
    return results


def validate(report, expected):
    u, limits, name = report["usage"], report["limits"], report["scenario"]
    assert tuple(u[k] for k in ("accepted", "models", "tools", "reads")) == expected[:4], (name, u)
    assert report["errors"] == ([] if expected[4] is None else [expected[4]])
    assert all(report[k] for k in ("isolation_ok", "source_unchanged", "shared_file_view", "no_write_output", "workspace_removed"))
    assert u["spawned"] == u["joined"] == (1 if name == "member-limit" else 2)
    assert u["active"] == u["aborted"] == 0
    assert u["accepted"] <= limits["messages"] and u["models"] <= limits["models"] and u["tools"] <= limits["tools"]
    receipts, inputs, reads = [], [], 0
    tool_errors = []
    for member_id, m in report["members"].items():
        assert m["lifecycle"] == "closed" and m["pairs_valid"]
        assert m["events"][-2:] == ["closing", "closed"]
        messages = m["messages"]
        private = "CORE_PRIVATE" if member_id == "core" else "CONFIG_PRIVATE"
        other = "CONFIG_PRIVATE" if member_id == "core" else "CORE_PRIVATE"
        assert private in messages[0]["content"] and other not in json.dumps(messages)
        assert all(msg["message_type"] != "system" for msg in messages[1:])
        outputs = check_history(messages)
        for output in outputs:
            if not output["ok"]:
                tool_errors.append(output["error"])
            elif "path" in output["data"]:
                data = output["data"]
                assert data["path"] == ("src/lib.rs" if member_id == "core" else "config.toml")
                assert sha(data["text"].encode()) == data["sha256"]
                reads += 1
        receipts.extend(m["receipts"])
        inputs.extend(m["model_input_bytes"])
        assert len(m["graph_nodes"]) <= 18
        for receipt in m["receipts"]:
            assert receipt["member"] == member_id
            if receipt["summary"]:
                assert len(receipt["summary"].encode()) <= 512
            if receipt["status"] == "completed":
                assert "未运行被审查项目的测试" in receipt["summary"]
    assert len(receipts) == u["accepted"] and len({r["message_id"] for r in receipts}) == u["accepted"]
    assert len(inputs) == u["models"] and all(n <= limits["context_bytes"] for n in inputs)
    assert reads == u["reads"]
    assert all(r in receipts for r in report["receipts"])
    jobs = sorted(r["status"] for r in receipts if r["status"] != "noted")
    expected_jobs = STOPS.get(name, ["completed"] * (2 if name in ("normal", "persistent", "peer-message") else 1 if name == "note-injection" else 0))
    assert jobs == sorted(expected_jobs), (name, jobs, expected_jobs)
    expected_error = {"tool-budget": "team_tool_budget", "forbidden-path": "denied_path", "write-denied": "permission_denied", "missing-file": "missing_file"}.get(name)
    assert tool_errors == ([] if expected_error is None else [expected_error])
    if name == "peer-message":
        assert report["members"]["config"]["notes"] == 1
        notes = [json.loads(m["content"]) for m in report["members"]["config"]["messages"] if '\"kind\":\"peer_note\"' in m["content"]]
        assert notes[0]["from"] == "core"
    if name == "persistent":
        assert report["members"]["core"]["reads"] == 2
        assert report["members"]["core"]["events"].count("busy") == 2
        assert "CORE_FOLLOWUP" not in json.dumps(report["members"]["config"]["messages"])
    if name == "normal":
        assert all(m["graph_nodes"] == ["ModelTurn", "ExecuteTools", "ModelTurn"] for m in report["members"].values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package = {name: (PACKAGE / name).read_bytes() for name in FILES}
    targets, reports = {}, []
    env = os.environ.copy()
    # Same fixed dependencies as R07; reuse compiled dependencies locally.
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-r07-target")
    with tempfile.TemporaryDirectory(prefix="agent-r15-verify-") as directory:
        with zipfile.ZipFile(io.BytesIO(pack(package))) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "agent-teams"
        run(["cargo", "fmt", "--check"], folder, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], folder, env)
        match = re.search(r"test result: ok\. (\d+) passed; 0 failed;", tests)
        assert match, tests
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
        for name, expected in CASES.items():
            report = json.loads(run(["cargo", "run", "--locked", "--quiet", "--", "--json", name], folder, env))
            validate(report, expected)
            output = run(["cargo", "run", "--locked", "--quiet", "--", name], folder, env).encode()
            targets[PUBLIC / "outputs" / ("r15-" + name + ".txt")] = output
            package["outputs/" + name + ".txt"] = output
            report["stdout_sha256"] = sha(output)
            reports.append(report)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], folder, env).encode()
        assert output == targets[PUBLIC / "outputs/r15-normal.txt"]
        invalid = subprocess.run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "invalid"], cwd=folder, env=env, capture_output=True)
        assert invalid.returncode != 0
        rustc = run(["rustc", "--version"], folder, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="R15; single-process current-thread Tokio actors; pinned graph-flow and langchain-rust; deterministic Lead and teammate LLM; real temporary files, bounded channels, no durable messaging or HTTP",
                    rustc=rustc, tests_passed=int(match[1]),
                    source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES}, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[DATA] = serialized
    package["evidence.json"] = serialized
    targets[ARCHIVE] = pack(package)
    with tempfile.TemporaryDirectory(prefix="agent-r15-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as archive:
            archive.extractall(directory)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], Path(directory) / "agent-teams", env).encode()
        assert output == targets[PUBLIC / "outputs/r15-normal.txt"]
    chapter = CHAPTER.read_text()
    table = ["| 场景 | 入队 / 模型 / 工具 / 读取 | 拒绝或工作状态 | active / joined |", "| --- | --- | --- | --- |"]
    for r in reports:
        u = r["usage"]
        statuses = r["errors"] + sorted({receipt["status"] for m in r["members"].values() for receipt in m["receipts"]})
        table.append("| `{}` | {} / {} / {} / {} | {} | {} / {} |".format(
            r["scenario"], u["accepted"], u["models"], u["tools"], u["reads"],
            "、".join("`" + state + "`" for state in statuses) or "—", u["active"], u["joined"]))
    start, end = "<!-- r15-results:start -->", "<!-- r15-results:end -->"
    assert chapter.count(start) == chapter.count(end) == 1, "Missing or duplicate R15 result markers"
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    targets[CHAPTER] = (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/agent-teams/([^#\s]+)#([\w-]+)", chapter):
        source = (PACKAGE / filename).read_text()
        assert source.count("// region " + region + "\n") == source.count("// endregion " + region + "\n") == 1, region
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R15 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f'R15: {len(CASES)} scenarios, {match[1]} Rust tests, Clippy, mailboxes/private histories/budgets/cancellation/join, offline and final download passed; ' + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
