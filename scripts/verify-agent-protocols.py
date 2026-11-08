"""Generate/check the R16 protocol experiment and the final standalone download."""
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
PACKAGE = PUBLIC / "code/team-protocols"
CHAPTER = ROOT / "docs/learn-agent-rust/team-protocols.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r16-results.json"
ARCHIVE = PUBLIC / "team-protocols.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/protocol.rs", "src/runtime.rs", "src/tests.rs"]
# writes, errors, plan-1 status before cleanup (None when no plan-1).
CASES = {
    "normal": (1, [], "completed"),
    "unapproved": (0, ["not_approved"], "pending"),
    "rejected": (0, ["not_approved"], "rejected"),
    "resubmit": (1, ["not_approved"], "rejected"),
    "wrong-sender": (0, ["wrong_identity"], "pending"),
    "wrong-recipient": (0, ["wrong_identity"], "pending"),
    "wrong-kind": (0, ["wrong_kind"], "pending"),
    "unknown-request": (0, ["unknown_request"], None),
    "duplicate-request": (0, ["duplicate_request"], "pending"),
    "duplicate-response": (0, ["request_not_pending"], "approved"),
    "late-response": (0, ["request_not_pending"], "expired"),
    "expired-grant": (0, ["not_approved"], "expired"),
    "changed-plan": (0, ["plan_changed"], "approved"),
    "replay-write": (1, ["not_approved"], "completed"),
    "forbidden-path": (0, ["permission_denied"], "approved"),
    "progress-injection": (0, ["not_approved"], "pending"),
    "cancel-request": (0, ["request_not_pending"], "cancelled"),
    "shutdown-rejected": (1, ["not_approved"], "cancelled"),
    "shutdown-timeout": (0, ["request_not_pending"], None),
    "shutdown-panic": (0, [], None),
    "ack-without-exit": (0, [], None),
    "abort-fallback": (0, [], None),
    "shutdown-freeze": (0, ["member_closing"], "cancelled"),
    "mailbox-full": (1, ["mailbox_full"], "completed"),
    "schema-errors": (0, ["invalid_message"] * 3 + ["message_size"], None),
    "request-limit": (0, ["request_limit"], "pending"),
    "clock-regression": (0, ["clock_regression"], None),
    "write-failed": (0, ["write_failed"], "failed"),
}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(" ".join(args) + "\n" + result.stdout + result.stderr)
    return result.stdout


def pack(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo("team-protocols/" + name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def validate(r, expected):
    name = r["scenario"]
    before, after = r["before_cleanup"], r["after_cleanup"]
    assert r["errors"] == expected[1], (name, r["errors"])
    assert before["writes"] == after["writes"] == expected[0], name
    assert r["active"] == 0 and len(r["joined"]) == 2
    assert [j["member"] for j in r["joined"]] == ["core", "config"]
    assert sum(j["aborted"] for j in r["joined"]) == int(name == "abort-fallback")
    assert r["workspace_removed"] and r["escape_absent"] and all(r["observations"].values()), name
    assert len(before["requests"]) <= 16
    if expected[2] is not None:
        assert before["requests"]["plan-1"]["status"] == expected[2], name
    for request in before["requests"].values():
        if request["kind"] == "plan":
            assert request["requester"] in ("core", "config") and request["responder"] == "lead"
            canonical = json.dumps(request["plan"], ensure_ascii=False, separators=(",", ":")).encode()
            assert sha(canonical) == request["digest"], name
        else:
            assert request["requester"] == "lead" and request["responder"] in ("core", "config")
    # Independently reconstruct the writes' provenance from recorded transitions.
    completed = [e["id"] for e in after["events"] if e["action"] == "completed"]
    assert len(completed) == expected[0]
    for request_id in completed:
        events = [e["action"] for e in after["events"] if e["id"] == request_id]
        assert events.index("opened") < events.index("response") < events.index("executing") < events.index("completed")
        request = after["requests"][request_id]
        assert request["status"] == "completed" and request["plan"]["path"] == "review.txt"
        assert request["requester"] == "core"
        assert request["plan"]["content"] == r["artifact"]["content"]
    if r["artifact"] is not None:
        assert expected[0] == 1
        assert r["artifact"]["path"] == "review.txt"
        assert sha(r["artifact"]["content"].encode()) == r["artifact"]["sha256"]
    else:
        assert expected[0] == 0
    for q in after["requests"].values():
        assert q["status"] not in ("pending", "executing")
        assert q["status"] != "approved" or q["kind"] == "shutdown"
    assert all(wire.endswith(":accepted") for wire in r["wire_received"])
    if name == "normal":
        assert all(j["outcome"] == "graceful" for j in r["joined"])
        assert before["requests"]["stop-core"]["status"] == before["requests"]["stop-config"]["status"] == "approved"
    if name == "shutdown-panic":
        assert before["requests"]["stop-core"]["status"] == "pending"
        assert after["requests"]["stop-core"]["status"] == "failed"
        assert r["joined"][0]["outcome"] == "panic"
    if name == "shutdown-timeout":
        assert after["requests"]["stop-core"]["status"] == "expired"
        assert r["joined"][0]["outcome"] == "cancelled"
    if name in ("ack-without-exit", "abort-fallback"):
        assert before["requests"]["stop-core"]["status"] == "approved"
        assert r["joined"][0]["outcome"] == ("aborted" if name == "abort-fallback" else "cancelled")
    if name == "resubmit":
        assert before["requests"]["plan-2"]["plan"]["revision"] == 2
        assert "Revised" in r["artifact"]["content"]
    if name == "shutdown-rejected":
        assert before["requests"]["stop-core"]["status"] == "rejected"
        assert before["requests"]["plan-2"]["status"] == "completed"
    if name == "request-limit":
        assert len(before["requests"]) == 16


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package = {name: (PACKAGE / name).read_bytes() for name in FILES}
    targets, reports = {}, []
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-r16-target")
    with tempfile.TemporaryDirectory(prefix="agent-r16-verify-") as directory:
        with zipfile.ZipFile(io.BytesIO(pack(package))) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "team-protocols"
        run(["cargo", "fmt", "--check"], folder, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], folder, env)
        match = re.search(r"test result: ok\. (\d+) passed; 0 failed;", tests)
        assert match and int(match[1]) == 15, tests
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
        for name, expected in CASES.items():
            report = json.loads(run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "--json", name], folder, env))
            validate(report, expected)
            output = run(["cargo", "run", "--locked", "--offline", "--quiet", "--", name], folder, env).encode()
            targets[PUBLIC / "outputs" / ("r16-" + name + ".txt")] = output
            package["outputs/" + name + ".txt"] = output
            report["stdout_sha256"] = sha(output)
            reports.append(report)
        assert run(["cargo", "run", "--locked", "--offline", "--quiet"], folder, env).encode() == targets[PUBLIC / "outputs/r16-normal.txt"]
        for arguments in [["invalid"], ["--json", "--json"], ["normal", "extra"]]:
            result = subprocess.run(["cargo", "run", "--locked", "--offline", "--quiet", "--"] + arguments, cwd=folder, env=env, capture_output=True)
            assert result.returncode == 2
        rustc = run(["rustc", "--version"], folder, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="R16; standalone protocol core; current-thread Tokio actors and real temporary files; scripted requests, injected monotonic ticks; one real receive timeout and one awaited abort fallback; no LLM/framework integration or durable messaging",
                    rustc=rustc, tests_passed=int(match[1]),
                    source_sha256={name: sha(content) for name, content in sorted(package.items()) if name in FILES}, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[DATA] = serialized
    package["evidence.json"] = serialized
    targets[ARCHIVE] = pack(package)
    # Run the final user archive, including every scenario, rather than just source files.
    with tempfile.TemporaryDirectory(prefix="agent-r16-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "team-protocols"
        run(["cargo", "build", "--locked", "--offline", "--quiet"], folder, env)
        for original in reports:
            name = original["scenario"]
            actual = json.loads(run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "--json", name], folder, env))
            validate(actual, CASES[name])
            assert actual == {key: value for key, value in original.items() if key != "stdout_sha256"}
            assert run(["cargo", "run", "--locked", "--offline", "--quiet", "--", name], folder, env).encode() == package["outputs/" + name + ".txt"]
    chapter = CHAPTER.read_text()
    table = ["| 场景 | 实际写入 | 协议拒绝 / 实验检查 | core 退出结果 |", "| --- | --- | --- | --- |"]
    for r in reports:
        result = "、".join("`" + e + "`" for e in r["errors"]) or "通过独立检查"
        table.append("| `{}` | {} | {} | `{}` |".format(r["scenario"], r["after_cleanup"]["writes"], result, r["joined"][0]["outcome"]))
    start, end = "<!-- r16-results:start -->", "<!-- r16-results:end -->"
    assert chapter.count(start) == chapter.count(end) == 1
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    targets[CHAPTER] = (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/team-protocols/([^#\s]+)#([\w-]+)", chapter):
        source = (PACKAGE / filename).read_text()
        assert source.count("// region " + region + "\n") == source.count("// endregion " + region + "\n") == 1, region
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R16 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f'R16: {len(CASES)} scenarios, {match[1]} Rust tests, Clippy, exact approval/identity/deadlines/shutdown/join, offline and all final-download scenarios passed; ' + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
