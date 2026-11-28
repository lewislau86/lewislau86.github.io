"""Verify the R06 subagent lab on ADK-Rust 3.0.

python3 scripts/verify-agent-subagents.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要与几条详细轨迹各连跑两次必须逐字节相同，逐项核对场景，并把结果表写进正文。
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
SLUG = "subagents"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/subagents.md"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r06-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["normal", "changed-readme", "child-loop-limit", "parent-answer-budget", "global-model-budget", "cancel",
           "forbidden-path", "recursive", "oversized-result", "transfer"]
# 场景：(停止, 回答者, 父模型请求, 子模型请求, 读取尝试/成功, 练习目标)
EXPECTED = {
    "normal": ("final_answer", "coordinator", 2, 2, "1/1", True),
    "changed-readme": ("final_answer", "coordinator", 2, 2, "1/1", True),
    "missing-file": ("final_answer", "coordinator", 2, 2, "1/0", False),
    "child-loop-limit": ("final_answer", "coordinator", 2, 1, "1/1", False),
    "global-model-budget": ("budget.model_calls", "-", 1, 1, "1/1", False),
    "global-tool-budget": ("final_answer", "coordinator", 2, 1, "0/0", False),
    "parent-answer-budget": ("budget.model_calls", "-", 1, 2, "1/1", False),
    "cancel": ("ended", "-", 1, 1, "0/0", False),
    "cancel-before-start": ("ended", "-", 0, 0, "0/0", False),
    "forbidden-path": ("final_answer", "coordinator", 2, 2, "1/0", False),
    "recursive": ("final_answer", "coordinator", 2, 2, "0/0", False),
    "invalid-task": ("final_answer", "coordinator", 2, 0, "0/0", False),
    "oversized-result": ("final_answer", "coordinator", 2, 2, "1/1", False),
    "model-error": ("final_answer", "coordinator", 2, 1, "0/0", False),
    "transfer": ("final_answer", "reader", 1, 2, "1/1", True),
}
# 交接后子 Agent 看到用户原话，父会话的标记跟着过去；当工具调用时不应出现
SEES_PARENT_NOTE = {"transfer"}
LINE = re.compile(r"^(?P<name>[a-z-]+): stop=(?P<stop>\S+) answered_by=(?P<by>\S+) parent_model_calls=(?P<p>\d+) "
                  r"child_model_calls=(?P<c>\d+) reads=(?P<reads>\d+/\d+) parent_saw_child_raw=(?P<raw>\w+) "
                  r"child_saw_parent_note=(?P<note>\w+) goal_met=(?P<goal>\w+)$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        m = LINE.match(line)
        require(m, f"unexpected summary line: {line}")
        rows.append(dict(name=m["name"], stop=m["stop"], answered_by=m["by"], parent_model_calls=int(m["p"]),
                         child_model_calls=int(m["c"]), reads=m["reads"], parent_saw_child_raw=m["raw"] == "true",
                         child_saw_parent_note=m["note"] == "true", goal_met=m["goal"] == "true"))
    return rows


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "learn-agent-r06"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    require([r["name"] for r in rows] == list(EXPECTED), "scenario list changed")
    for row in rows:
        want = EXPECTED[row["name"]]
        got = (row["stop"], row["answered_by"], row["parent_model_calls"], row["child_model_calls"], row["reads"],
               row["goal_met"])
        require(got == want, f"{row['name']}: expected {want}, got {got}")
        require(not row["parent_saw_child_raw"], f"{row['name']}: child raw text reached the parent")
        require(row["child_saw_parent_note"] == (row["name"] in SEES_PARENT_NOTE), f"{row['name']}: parent note")
    outputs = {"r06-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r06-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    normal = outputs["r06-normal.txt"]
    require("child request 0: roles=system,user tools=[read_file]" in normal, normal)
    require('child request 0 user text: "读取 README.md，只返回启动命令。"' in normal, normal)
    require('{"response":"启动命令：cargo run"}' in normal, normal)
    require("status=outcome_unknown" in outputs["r06-cancel.txt"], outputs["r06-cancel.txt"])
    require("code=delegate.output_limit" in outputs["r06-oversized-result.txt"], "oversized report must be refused")
    require("transfer_to_agent" in outputs["r06-transfer.txt"], "transfer must call transfer_to_agent")
    usage = adk.run([binary, "unknown"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    return outputs, rows


def table(rows):
    lines = ["| 场景 | 父 / 子模型请求 | 读取尝试 / 成功 | 停止 | 回答者 | 练习目标达成 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| `{}` | {} / {} | {} | `{}` | {} | {} |".format(
            r["name"], r["parent_model_calls"], r["child_model_calls"], r["reads"].replace("/", " / "), r["stop"],
            "—" if r["answered_by"] == "-" else f"`{r['answered_by']}`", "是" if r["goal_met"] else "否"))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r06-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        outputs, rows = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R06 on ADK-Rust 3.0 RC: AgentTool (isolated session, forwarded events) and transfer_to_agent, "
              "shared RunBudget, cancellation token; rule-based models, real temp-dir file reads; no network",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=rows,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    start, end = "<!-- r06-results:start -->", "<!-- r06-results:end -->"
    text = CHAPTER.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[CHAPTER] = chapter.encode()
    stale = [p for p in OUTPUT.glob("r06-*") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R06 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R06 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R06: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
