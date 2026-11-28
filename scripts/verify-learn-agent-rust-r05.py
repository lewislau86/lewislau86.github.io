"""Verify the R05 todo-planning lab on ADK-Rust 3.0.

python3 scripts/verify-learn-agent-rust-r05.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要和三条详细轨迹各连跑两次必须逐字节相同，并逐项核对场景结果。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402
from learn_agent_rust_adk import require  # noqa: E402

ROOT = adk.ROOT
SLUG = "todo-planning"
OUTPUT = adk.PUBLIC / "outputs"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r05-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["normal", "claims-only", "template-only"]

SUMMARY = [
    "normal: stop=answer model_calls=7 revision=5 reads=1 completed=true goal_verified=true "
    "seen_revisions=[0, 1, 2, 2, 3, 4, 5]",
    "claims-only: stop=answer model_calls=7 revision=5 reads=0 completed=true goal_verified=false",
    "read-error: stop=answer model_calls=4 revision=2 reads=0 completed=false goal_verified=false "
    "seen_revisions=[0, 1, 2, 2]",
    "budget-stop: stop=agent.legacy model_calls=3 revision=2 reads=1 completed=false",
    "template-only: stop=answer model_calls=3 revision=1 reads=0 completed=false goal_verified=false "
    "seen_revisions=[0, 0, 0] next_run_first_seen=1",
    "next-run: first_run_revision=5 second_run_first_seen=5",
    "fresh-session: s1_revision=5 s2_plan=none",
    "append-step: status=ok code=- unchanged=false revision=1->2",
    "yield-step: status=ok code=- unchanged=false revision=2->3",
    "permission-denied: status=refused code=- unchanged=true revision=2->2 summary_exists=false",
    "same-batch-naive: results=ok,ok revision=1->2 read_started=false step_appended=true lost_update=true",
    "same-batch: results=ok,todo.revision_conflict revision=1->2 read_started=true step_appended=false "
    "lost_update=false",
]
REJECTED = {
    "two-active": "todo.multiple_active", "skip-completion": "todo.invalid_transition",
    "unknown-status": "todo.invalid_arguments", "duplicate-id": "todo.duplicate_id",
    "empty-content": "todo.invalid_content", "too-many": "todo.item_count",
    "remove-item": "todo.removed_item", "changed-content": "todo.content_changed",
    "stale-revision": "todo.revision_conflict", "reopen-completed": "todo.invalid_transition",
    "wrong-type": "todo.invalid_arguments", "unknown-field": "todo.invalid_arguments",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshots(detail):
    rows = []
    for revision, rest in re.findall(r"^request \d+: revision=(\d+) (.*)$", detail, re.M):
        items = dict(pair.split("=") for pair in rest.split()) if "=" in rest else {}
        rows.append({"revision": int(revision), "items": items})
    return rows


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "learn-agent-r05"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    for fragment in SUMMARY:
        require(fragment in summary, f"summary: missing {fragment!r}\n{summary}")
    for name, code in REJECTED.items():
        require(re.search(rf"^{name}: status=failed code={re.escape(code)} unchanged=true .*summary_exists=false$",
                          summary, re.M), f"{name}: expected {code}\n{summary}")
    require(len(summary.splitlines()) == 24, "expected 24 scenarios")
    outputs = {"r05-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r05-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    normal = outputs["r05-normal.txt"]
    require("[assistant] call    id=call-3 read_file" in normal and "启动说明：" in normal, normal)
    require("todo_read" in outputs["r05-claims-only.txt"], "claims-only must read the plan, not the file")
    require("code=todo.revision_conflict" in outputs["r05-template-only.txt"], "template-only must conflict")
    usage = adk.run([binary, "unknown"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r05-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        outputs = verify(folder, env)
        header = adk.evidence_header(folder, env)
    reports = {}
    for name in ("normal", "claims-only"):
        line = re.search(rf"^{name}: (.*)$", outputs["r05-summary.txt"], re.M).group(1)
        fields = dict(pair.split("=", 1) for pair in line.split(" seen_revisions=")[0].split())
        reports[name] = {"reads": int(fields["reads"]), "all_completed": fields["completed"] == "true",
                         "goal_verified": fields["goal_verified"] == "true"}
    evidence = dict(
        scope="R05 on ADK-Rust 3.0 RC: plan in session state via a todo_write FunctionTool and state_delta, "
              "before_model callback for visibility, rule-based PlanLlm, real temp-dir file reads; no network",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=24,
        normal_snapshots=snapshots(outputs["r05-normal.txt"]), reports=reports,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    targets = {OUTPUT / name: text.encode() for name, text in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    stale = [p for p in OUTPUT.glob("r05-*") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R05 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R05 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R05: 24 scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
