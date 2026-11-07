"""Run R07 from an isolated package; save/check real outputs, evidence and zip.

python3 scripts/verify-agent-skills.py [--check]
The first run needs network for the pinned Rust toolchain and Cargo dependencies.
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
PACKAGE = PUBLIC / "code/skill-loading"
DATA = ROOT / "scripts/data/learn-agent-rust/r07-results.json"
ARCHIVE = PUBLIC / "skill-loading.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/skills.rs", "skills/rust-review/SKILL.md", "skills/sql-style/SKILL.md"]
# loads, unique bodies, reads, model turns, expected tool error
CASES = {
    "normal": (1, 1, 1, 3, None),
    "no-skill": (0, 0, 1, 2, None),
    "repeat": (2, 1, 1, 4, None),
    "unknown": (1, 0, 0, 2, "unknown_skill"),
    "invalid-name": (1, 0, 0, 2, "invalid_skill_name"),
    "changed": (1, 0, 0, 2, "stale_skill"),
    "missing": (1, 0, 0, 2, "missing_manifest"),
    "oversize": (1, 0, 0, 2, "file_too_large"),
    "budget": (1, 0, 0, 2, "context_budget"),
    "permission": (1, 1, 0, 3, "permission_denied"),
    "version-two": (1, 1, 1, 3, None),
    "empty-catalog": (1, 0, 0, 2, "unknown_skill"),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, cwd, env):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=True, timeout=900).stdout


def pack(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo("skill-loading/" + name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def validate(report, expected):
    state = report["state"]
    loads, unique, reads, turns, error = expected
    actual = (state["load_requests"], len(state["loaded"]), state["read_attempts"], state["model_turns"])
    if actual != (loads, unique, reads, turns):
        raise ValueError("Wrong counters: " + report["scenario"])
    if state["write_attempts"] or report["review_file_exists"] or not report["source_unchanged"]:
        raise ValueError("Unexpected filesystem mutation")
    messages = state["messages"]
    system = messages[0]["content"]
    if "先给结论" in system or "忽略权限" in system:
        raise ValueError("Skill body leaked into the initial system catalog")
    pending, seen = set(), set()
    outputs = []
    for message in messages:
        if message["message_type"] == "ai":
            if pending:
                raise ValueError("Model called with pending tools")
            for call in message.get("tool_calls") or []:
                if not call["id"] or call["id"] in seen:
                    raise ValueError("Reused/empty call ID")
                pending.add(call["id"])
                seen.add(call["id"])
        elif message["message_type"] == "tool":
            if message["id"] not in pending:
                raise ValueError("Unpaired tool result")
            pending.remove(message["id"])
            outputs.append(json.loads(message["content"]))
    if pending or state["pending"]:
        raise ValueError("Unresolved tool calls")
    errors = [o["error"] for o in outputs if not o["ok"]]
    if errors != ([] if error is None else [error]):
        raise ValueError("Wrong error boundary: " + report["scenario"])
    if state["stop"] != ("completed" if error is None else "tool_error"):
        raise ValueError("Wrong stop condition")
    injected = [o["data"] for o in outputs if o["ok"] and "instructions" in o["data"]]
    if sum(len(o["instructions"].encode()) for o in injected) != state["injected_bytes"] or len(injected) != unique:
        raise ValueError("Incorrect injection accounting")
    if any("SQL 查询规范" in o["instructions"] for o in injected):
        raise ValueError("Unrelated skill loaded")
    if report["scenario"] == "version-two" and injected[0]["source"]["version"] != "2.0.0":
        raise ValueError("Wrong active version")
    if report["scenario"] == "repeat" and sum(o.get("data", {}).get("already_loaded", False) for o in outputs) != 1:
        raise ValueError("Duplicate activation not acknowledged")
    if report["graph_nodes"] != [node for _ in outputs for node in ("ModelTurn", "ExecuteTools")] + ["ModelTurn"]:
        raise ValueError("Graph did not execute the expected sequence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package = {name: (PACKAGE / name).read_bytes() for name in FILES}
    targets, reports = {}, []
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-r07-target")
    with tempfile.TemporaryDirectory(prefix="agent-r07-verify-") as directory:
        with zipfile.ZipFile(io.BytesIO(pack(package))) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "skill-loading"
        run(["cargo", "fmt", "--check"], folder, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], folder, env)
        if not re.search(r"test result: ok\. \d+ passed; 0 failed;", tests):
            raise ValueError("Rust regression tests did not pass")
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
        for name, expected in CASES.items():
            report = json.loads(run(["cargo", "run", "--locked", "--quiet", "--", "--json", name], folder, env))
            validate(report, expected)
            output = run(["cargo", "run", "--locked", "--quiet", "--", name], folder, env).encode()
            targets[PUBLIC / "outputs" / ("r07-" + name + ".txt")] = output
            package["outputs/" + name + ".txt"] = output
            report["stdout_sha256"] = sha(output)
            reports.append(report)
        offline = run(["cargo", "run", "--locked", "--offline", "--quiet"], folder, env).encode()
        if offline != targets[PUBLIC / "outputs/r07-normal.txt"]:
            raise ValueError("Offline run differs")
        invalid = subprocess.run(["cargo", "run", "--locked", "--offline", "--quiet", "--", "invalid"], cwd=folder, env=env, capture_output=True)
        if invalid.returncode == 0:
            raise ValueError("Invalid CLI scenario accepted")
        rustc = run(["rustc", "--version"], folder, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="R07; pinned langchain-rust LLM trait and real graph-flow; scripted decisions; owned temporary skills/workspace; no HTTP/database",
                    source_sha256={name: sha((PACKAGE / name).read_bytes()) for name in FILES},
                    rustc=rustc, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[DATA] = serialized
    package["evidence.json"] = serialized
    targets[ARCHIVE] = pack(package)
    # Re-extract the final user download, not only its source-only intermediate.
    with tempfile.TemporaryDirectory(prefix="agent-r07-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as archive:
            archive.extractall(directory)
        output = run(["cargo", "run", "--locked", "--offline", "--quiet"], Path(directory) / "skill-loading", env).encode()
        if output != targets[PUBLIC / "outputs/r07-normal.txt"]:
            raise ValueError("Download differs from website outputs")
    chapter = (ROOT / "docs/learn-agent-rust/skill-loading.md").read_text()
    table = ["| 场景 | 加载请求 | 正文份数 | 注入字节 | 读 / 写尝试 | 错误 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for report in reports:
        s = report["state"]
        errors = [json.loads(m["content"])["error"] for m in s["messages"]
                  if m["message_type"] == "tool" and not json.loads(m["content"])["ok"]]
        table.append("| `{}` | {} | {} | {} | {} / {} | {} |".format(
            report["scenario"], s["load_requests"], len(s["loaded"]), s["injected_bytes"],
            s["read_attempts"], s["write_attempts"], "、".join("`" + e + "`" for e in errors) or "—"))
    start, end = "<!-- r07-results:start -->", "<!-- r07-results:end -->"
    if chapter.count(start) != 1 or chapter.count(end) != 1:
        raise ValueError("Missing or duplicate R07 result markers")
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    targets[ROOT / "docs/learn-agent-rust/skill-loading.md"] = (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/skill-loading/([^#\s]+)#([\w-]+)", chapter):
        source = (PACKAGE / filename).read_text()
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing/duplicate snippet region: " + region)
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R07 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R07: 12 scenarios, Rust tests, Clippy, pairing/bytes/permission assertions, offline and final download passed; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
