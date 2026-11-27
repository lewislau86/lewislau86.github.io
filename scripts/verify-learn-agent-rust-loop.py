"""Verify the R01 Cargo package (ADK-Rust 3.0) and generate reproducible course artifacts.

python3 scripts/verify-learn-agent-rust-loop.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，然后 fmt、clippy、cargo test、离线构建；
14 个场景各连跑两次必须逐字节相同，核对计数、停止原因、调用与结果配对；非法参数必须以退出码 2 结束；
最后把结果表写进正文 <!-- r01-results:start --> 与 <!-- r01-results:end --> 之间。
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
SLUG = "agent-loop"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/agent-loop.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r01-results.json"
ARCHIVE = adk.PUBLIC / "agent-loop.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
# 场景：参数，(模型调用, 工具结果, 读取尝试, 读取成功, 会话事件, 停止原因, 练习目标达成)
SCENARIOS = {
    "normal": ([], (2, 1, 1, 1, 4, "final_answer", True)),
    "changed-readme": (["--scenario", "changed-readme"], (2, 1, 1, 1, 4, "final_answer", True)),
    "missing-file": (["--scenario", "missing-file"], (2, 1, 1, 0, 4, "final_answer", False)),
    "model-budget": (["--max-model-calls", "1"], (1, 1, 1, 1, 4, "budget.model_calls", False)),
    "zero-model-budget": (["--max-model-calls", "0"], (0, 0, 0, 0, 2, "budget.model_calls", False)),
    "tool-budget": (["--max-tool-calls", "0"], (1, 1, 0, 0, 4, "budget.tool_calls", False)),
    "repeat": (["--scenario", "repeat", "--max-tool-calls", "2"], (3, 3, 2, 2, 8, "budget.tool_calls", False)),
    "repeat-model-budget": (["--scenario", "repeat", "--max-model-calls", "2"], (2, 2, 2, 2, 6, "budget.model_calls", False)),
    "loop-limit": (["--scenario", "repeat", "--max-iterations", "3"], (3, 3, 3, 3, 7, "agent.legacy", False)),
    "two-tools": (["--scenario", "two-tools"], (2, 2, 2, 2, 5, "final_answer", True)),
    "batch-budget": (["--scenario", "two-tools", "--max-tool-calls", "1"], (1, 2, 0, 0, 4, "budget.tool_calls", False)),
    "duplicate-id": (["--scenario", "duplicate-id"], (3, 2, 2, 2, 6, "final_answer", True)),
    "unknown-tool": (["--scenario", "unknown-tool"], (2, 1, 0, 0, 4, "final_answer", False)),
    "invalid-path": (["--scenario", "invalid-path"], (2, 1, 0, 0, 4, "final_answer", False)),
}
STATS = re.compile(r"统计：model_calls=(\d+) tool_results=(\d+) read_attempts=(\d+) read_successes=(\d+) session_events=(\d+)")
STOP = re.compile(r"停止：(\S+)；fixture_goal_met=(true|false)")
START, END = "<!-- r01-results:start -->", "<!-- r01-results:end -->"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_trace(name, output, stop):
    calls = re.findall(r"\] call    id=(\S+)", output)
    results = re.findall(r"\] result  id=(\S+)", output)
    # 每个被接受的调用恰好一条结果、ID 一一对应；预算拒绝的调用也有（not_run）结果
    require(calls == results, f"{name}: calls {calls} vs results {results}")
    if stop.startswith("budget."):
        require(f"stop    code={stop}" in output, f"{name}: budget stop event missing")
    else:
        # 循环上限等其他停止方式不写停止事件
        require("stop    code=" not in output, f"{name}: unexpected stop event")
    if stop == "final_answer":
        require(re.search(r'\] text    "', output) is not None, f"{name}: no final answer")


def table(rows):
    lines = ["| 场景 | 参数 | 模型调用 | 工具结果 | 读取尝试 / 成功 | 会话事件 | 停止原因 | 练习目标 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        args = " ".join(r["args"]) or "—"
        lines.append(f"| `{r['name']}` | `{args}` | {r['model_calls']} | {r['tool_results']} | "
                     f"{r['read_attempts']} / {r['read_successes']} | {r['session_events']} | `{r['stop']}` | "
                     f"{'达成' if r['fixture_goal_met'] else '未达成'} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    targets = {ARCHIVE: packed}
    env = adk.cargo_env("learn-agent-r01-target")
    rows = []
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r01"
        for name, (flags, expected) in SCENARIOS.items():
            output = adk.repeat_identical([binary, *flags], folder, env, times=2)
            stats, stop = STATS.search(output), STOP.search(output)
            require(stats is not None and stop is not None, f"{name}: missing stats\n{output}")
            got = tuple(int(x) for x in stats.groups()) + (stop.group(1), stop.group(2) == "true")
            require(got == expected, f"{name}: {got} != {expected}")
            check_trace(name, output, got[5])
            if name == "normal":
                require("request 1: roles=system,user,model,function tools=[read_file]" in output, "normal: history")
            if name == "two-tools":
                # 一批两个调用的结果都写进历史以后，才发第二次请求
                require("request 1: roles=system,user,model,function,function tools=[read_file]" in output, "two-tools")
            if name == "changed-readme":
                require("cargo run --release" in output, "changed-readme must answer from the file read")
            if got[5] == "final_answer" and not got[6]:
                require("任务未完成：" in output, f"{name}: failure must be reported, not invented")
            targets[OUTPUT / f"r01-{name}.txt"] = output.encode()
            rows.append(dict(name=name, args=flags, model_calls=got[0], tool_results=got[1], read_attempts=got[2],
                             read_successes=got[3], session_events=got[4], stop=got[5], fixture_goal_met=got[6],
                             stdout_sha256=sha(output.encode())))
        for bad in (["--scenario", "unknown"], ["--max-model-calls", "-1"], ["--scenario"]):
            p = adk.run([binary, *bad], folder, env, ok=(2,))
            require("usage:" in p.stderr, f"{bad}: usage expected")
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R01 on ADK-Rust 3.0 RC: a rule-based Llm implementation that only reads its LlmRequest, "
              "FunctionTool on a real temporary README, RunBudget limits, in-memory session",
        **header, source_sha256={name: sha(data) for name, data in sorted(files.items())},
        archive_sha256=sha(packed), **checks, repeated_identical_runs=2, invalid_cli_cases=3, scenarios=rows)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    text = CHAPTER.read_text(encoding="utf-8")
    require(text.count(START) == 1 and text.count(END) == 1, "chapter needs exactly one r01-results block")
    before, rest = text.split(START)
    targets[CHAPTER] = (before + START + "\n\n" + table(rows) + "\n\n" + END + rest.split(END)[1]).encode()
    # 正文导入的片段与输出必须存在
    for region in set(re.findall(r"code/agent-loop/src/main\.rs#([\w-]+)", text)):
        require(files["src/main.rs"].decode().count(f"// region {region}\n") == 1, f"region {region} missing")
    for output in set(re.findall(r"outputs/(r01-[\w-]+\.txt)", text)):
        require(OUTPUT / output in targets, f"chapter imports {output}, which this run did not produce")
    stale = [p for p in OUTPUT.glob("r01-*.txt") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R01 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R01 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R01: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy, "
          "3 usage errors; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
