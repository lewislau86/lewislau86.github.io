"""Run the standalone R01 loop, its failure paths and Rust tests; save/check evidence.

python3 scripts/verify-learn-agent-rust-loop.py [--check]
No model service, framework crate or database is used.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/agent-loop.rs"
CHAPTER = ROOT / "docs/learn-agent-rust/agent-loop.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r01-results.json"
OUTPUT = ROOT / "docs/public/learn-agent-rust/outputs"
# name, flags, model turns, tool dispatches, read attempts, successes, messages, stop, goal
SCENARIOS = [
    ("normal", [], 2, 1, 1, 1, 4, "FinalAnswer", True),
    ("changed-readme", ["--scenario", "changed-readme"], 2, 1, 1, 1, 4, "FinalAnswer", True),
    ("missing-file", ["--scenario", "missing-file"], 2, 1, 1, 0, 4, "FinalAnswer", False),
    ("model-budget", ["--max-model-turns", "1"], 1, 1, 1, 1, 3, "ModelBudget", False),
    ("zero-model-budget", ["--max-model-turns", "0"], 0, 0, 0, 0, 1, "ModelBudget", False),
    ("tool-budget", ["--max-tool-calls", "0"], 1, 0, 0, 0, 3, "ToolBudget", False),
    ("repeat", ["--scenario", "repeat"], 3, 2, 2, 2, 7, "ToolBudget", False),
    ("repeat-model-budget", ["--scenario", "repeat", "--max-model-turns", "2"], 2, 2, 2, 2, 5, "ModelBudget", False),
    ("two-tools", ["--scenario", "two-tools"], 2, 2, 2, 2, 5, "FinalAnswer", True),
    ("batch-budget", ["--scenario", "two-tools", "--max-tool-calls", "1"], 1, 0, 0, 0, 4, "ToolBudget", False),
    ("duplicate-id", ["--scenario", "duplicate-id"], 2, 1, 1, 1, 4, "InvalidCall", False),
    ("unknown-tool", ["--scenario", "unknown-tool"], 2, 1, 0, 0, 4, "FinalAnswer", False),
    ("invalid-path", ["--scenario", "invalid-path"], 2, 1, 0, 0, 4, "FinalAnswer", False),
]


def command(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def validate_trace(output, stop):
    pending, seen = set(), set()
    for line in output.splitlines():
        request = re.match(r"消息 \d+ \| assistant \| call_id=(\S+) ", line)
        result = re.match(r"消息 \d+ \| tool \| call_id=(\S+) ", line)
        if request:
            call_id = request[1]
            if call_id in seen:
                if stop != "InvalidCall":
                    raise ValueError("Reused call ID was accepted")
                continue
            seen.add(call_id)
            pending.add(call_id)
        elif result:
            if result[1] not in pending:
                raise ValueError("Unpaired or repeated result")
            pending.remove(result[1])
        elif re.match(r"消息 \d+ \| assistant \| ", line) and pending:
            raise ValueError("Final answer before all tool results")
    if pending:
        raise ValueError("Unpaired accepted calls")


def results_table(results):
    lines = ["| 场景 | 模型轮次 | 工具执行尝试 | 文件读取尝试 / 成功 | 停止原因 | 练习目标达成 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in results:
        lines.append("| `{name}` | {model_turns} | {tool_calls} | {read_attempts} / {read_successes} | `{stop}` | {goal} |".format(
            **row, goal="是" if row["fixture_goal_met"] else "否"))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected_files, results = {}, []
    with tempfile.TemporaryDirectory(prefix="learn-agent-r01-verify-") as temp:
        # Compile a copied source outside the checkout, using no sibling crates.
        local_source = Path(temp) / SOURCE.name
        shutil.copyfile(SOURCE, local_source)
        executable = str(Path(temp) / "agent-r01")
        command(["rustfmt", "--edition", "2024", "--check", str(local_source)], temp)
        command(["rustc", "--edition=2024", "-D", "warnings", str(local_source), "-o", executable], temp)
        test_executable = str(Path(temp) / "agent-r01-tests")
        command(["rustc", "--edition=2024", "-D", "warnings", "--test", str(local_source), "-o", test_executable], temp)
        tests = command([test_executable], temp)
        if "6 passed; 0 failed" not in tests:
            raise ValueError("Rust contract tests did not all pass")
        for name, flags, *expected in SCENARIOS:
            output = command([executable] + flags, temp)
            stats = re.search(r"统计：model_turns=(\d+) tool_calls=(\d+) read_attempts=(\d+) read_successes=(\d+) messages=(\d+)", output)
            end = re.search(r"停止：(\w+)；fixture_goal_met=(true|false)", output)
            if not stats or not end:
                raise ValueError("Missing run statistics: " + name)
            actual = list(map(int, stats.groups())) + [end[1], end[2] == "true"]
            if actual != expected:
                raise ValueError("Unexpected result: {}: {} != {}".format(name, actual, expected))
            validate_trace(output, end[1])
            if end[1] == "FinalAnswer" and not actual[-1] and "任务未完成：" not in output:
                raise ValueError("Tool failure presented as task completion: " + name)
            if name == "changed-readme" and "README 里的启动命令是：cargo run --release" not in output:
                raise ValueError("Answer did not follow changed file contents")
            expected_files[OUTPUT / ("r01-" + name + ".txt")] = output
            results.append(dict(name=name, args=flags, **dict(zip(
                ["model_turns", "tool_calls", "read_attempts", "read_successes", "messages", "stop", "fixture_goal_met"], actual)),
                stdout_sha256=hashlib.sha256(output.encode()).hexdigest()))
        for flags in [["--scenario", "unknown"], ["--max-model-turns", "-1"], ["--scenario"]]:
            result = subprocess.run([executable] + flags, cwd=temp, capture_output=True, text=True)
            if result.returncode == 0:
                raise ValueError("Invalid CLI arguments accepted")
        evidence = dict(scope="R01 standard-library explicit loop; scripted model; real temporary file; no HTTP/framework/database",
                        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                        rustc=command(["rustc", "--version"], temp).strip(),
                        host=command(["rustc", "-vV"], temp).split("host: ")[1].splitlines()[0],
                        unit_tests_passed=6, scenarios=results)
    if args.check and DATA.exists():
        historical = json.loads(DATA.read_text())
        for key in ("rustc", "host"):
            evidence[key] = historical[key]
    expected_files[OUTPUT / "r01-environment.txt"] = (
        "rustc=" + evidence["rustc"] + "\nhost=" + evidence["host"]
        + "\nedition=2024\ndependencies=Rust standard library only\n"
        + "model=scripted, no HTTP\nworkspace=owned temporary fixture\n"
        + "scenarios=13\ncontract_tests=6\ninvalid_cli_cases=3\n")
    expected_files[DATA] = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    chapter = CHAPTER.read_text()
    start, end = "<!-- r01-results:start -->", "<!-- r01-results:end -->"
    if chapter.count(start) != 1 or chapter.count(end) != 1:
        raise ValueError("Missing R01 results markers")
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    expected_files[CHAPTER] = before + start + "\n\n" + results_table(results) + "\n\n" + end + after
    # Check snippet regions and include only evidence produced by this run.
    source = SOURCE.read_text()
    for region in re.findall(r"<<< @/public/learn-agent-rust/code/agent-loop.rs#([\w-]+)", chapter):
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing/duplicate source region: " + region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/(r01-[\w-]+\.txt)", chapter):
        if OUTPUT / name not in expected_files:
            raise ValueError("Unverified output referenced: " + name)
    for path, content in expected_files.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit("Stale R01 evidence: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print("R01: 13 scenarios, 6 Rust contract tests and 3 invalid CLI cases passed; " + ("evidence checked" if args.check else "evidence saved"))


if __name__ == "__main__":
    main()
