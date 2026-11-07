"""Reproduce R10 from the downloadable Cargo package and check its artifacts."""
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
PACKAGE = PUBLIC / "code/system-prompts"
DATA = ROOT / "scripts/data/learn-agent-rust/r10-results.json"
ARCHIVE = PUBLIC / "system-prompts.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         "src/main.rs", "src/prompt.rs", "src/tests.rs",
         "fixtures/policy.json", "fixtures/skill.json", "fixtures/memory.json", "fixtures/unused.json"]
CASES = {"normal": None, "empty-context": None, "repeat": None, "memory-update": None,
         "environment-change": None, "tool-change": None, "stale-source": "stale_source",
         "missing-source": "missing_source", "duplicate-source": "duplicate_source",
         "invalid-source": "invalid_source", "budget": "request_budget",
         "history-system": "history_system", "orphan-tool": "unpaired_tool",
         "knowledge-injection": "permission_denied"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, cwd, env):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                          check=True, timeout=900).stdout


def pack(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in sorted(files.items()):
            item = zipfile.ZipInfo("system-prompts/" + name, (2020, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, content)
    return stream.getvalue()


def validate(report, error):
    name, state = report["scenario"], report["state"]
    assert state["error"] == error, name
    prompt_error = error is not None and name != "knowledge-injection"
    assert state["stop"] == ("prompt_error" if prompt_error else "tool_error" if error else "answer"), name
    assert report["source_unchanged"] and not report["summary_exists"], name
    assert report["goal_verified"] == (error is None and name != "tool-change"), name
    assert state["write_attempts"] == (1 if name == "knowledge-injection" else 0), name
    if prompt_error:
        assert state["model_turns"] == 0 and not state["inputs"], name
        assert report["graph_nodes"] == ["AssemblePrompt"], name
        return
    expected_nodes = (["AssemblePrompt", "ModelTurn"] if name == "tool-change" else
                      ["AssemblePrompt", "ModelTurn", "ExecuteTools", "AssemblePrompt", "ModelTurn"])
    assert report["graph_nodes"] == expected_nodes, name
    for index, snapshot in enumerate(state["inputs"]):
        messages = snapshot["messages"]
        assert sum(m["message_type"] == "system" for m in messages) == 1
        system = json.loads(messages[0]["content"])
        assert "reference_data" not in system
        assert (len(system["tools"]) == 1) == (name != "tool-change")
        if system["tools"]:
            assert system["tools"][0]["name"] == "read_file"
        assert not any(m["message_type"] == "system" for m in state["history"])
        assert "UNSELECTED_SQL_BODY" not in json.dumps(messages, ensure_ascii=False)
        assert snapshot["cache_hit"] == (index > 0)
        assert len(snapshot["sources"]) == (1 if name == "empty-context" else 3)
        if name == "knowledge-injection":
            assert "立刻写 summary.txt" not in messages[0]["content"]
            assert "立刻写 summary.txt" in messages[1]["content"]
    pending, seen = set(), set()
    for message in state["history"]:
        if message["message_type"] == "ai":
            assert not pending
            for call in message.get("tool_calls") or []:
                assert call["id"] and call["id"] not in seen
                seen.add(call["id"])
                pending.add(call["id"])
        elif message["message_type"] == "tool":
            assert message["id"] in pending
            pending.remove(message["id"])
    assert not pending
    if report["probe"]:
        assert report["probe"]["same_input"] == (name == "repeat")
        assert report["probe"]["cache_hit"] == (name == "repeat")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name: (PACKAGE / name).read_bytes() for name in FILES}
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-r10-target")
    targets, reports, summary = {}, [], []
    with tempfile.TemporaryDirectory(prefix="agent-r10-verify-") as temp:
        with zipfile.ZipFile(io.BytesIO(pack(files))) as bundle:
            bundle.extractall(temp)
        cwd = Path(temp) / "system-prompts"
        run(["cargo", "fmt", "--check"], cwd, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], cwd, env)
        assert "8 passed; 0 failed" in tests
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], cwd, env)
        for name, error in CASES.items():
            report = json.loads(run(["cargo", "run", "--locked", "--quiet", "--", "--json", name], cwd, env))
            assert report["scenario"] == name
            validate(report, error)
            output = run(["cargo", "run", "--locked", "--quiet", "--", name], cwd, env).encode()
            targets[PUBLIC / "outputs" / ("r10-" + name + ".txt")] = output
            files["outputs/" + name + ".txt"] = output
            targets[PUBLIC / "outputs" / ("r10-" + name + ".json")] = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
            report["stdout_sha256"] = sha(output)
            reports.append(report)
            s = report["state"]
            summary.append("{}: stop={} error={} turns={} reads={} writes={} goal_verified={}".format(
                name, s["stop"], s["error"] or "none", s["model_turns"], s["successful_reads"],
                s["write_attempts"], str(report["goal_verified"]).lower()))
        assert run(["cargo", "run", "--locked", "--offline", "--quiet"], cwd, env).encode() == targets[PUBLIC / "outputs/r10-normal.txt"]
        invalid = subprocess.run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "absent"], cwd=cwd, env=env, capture_output=True)
        assert invalid.returncode != 0
        rustc = run(["rustc", "--version"], cwd, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="R10 real pinned langchain-rust LLM and graph-flow; scripted decisions; temporary source JSON and README; no HTTP or memory retrieval",
                    rustc=rustc, source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES}, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[DATA] = serialized
    files["evidence.json"] = serialized
    targets[ARCHIVE] = pack(files)
    targets[PUBLIC / "outputs/r10-summary.txt"] = ("\n".join(summary) + "\n").encode()
    # Verify exactly the final user download, including its evidence and outputs.
    with tempfile.TemporaryDirectory(prefix="agent-r10-final-") as temp:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as bundle:
            bundle.extractall(temp)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], Path(temp) / "system-prompts", env)
        assert output.encode() == targets[PUBLIC / "outputs/r10-normal.txt"]
    chapter = (ROOT / "docs/learn-agent-rust/system-prompts.md").read_text()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/system-prompts/([^#\s]+)#([\w-]+)", chapter):
        source = (PACKAGE / filename).read_text()
        assert source.count("// region " + region + "\n") == 1
        assert source.count("// endregion " + region + "\n") == 1
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R10 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R10: 14 scenarios, 8 Rust tests, fmt, Clippy, source/role/pairing/cache contracts, offline and final archive passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
