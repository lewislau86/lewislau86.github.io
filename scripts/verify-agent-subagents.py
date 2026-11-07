"""Run R06 outside the checkout; save/check transcripts, evidence and download.

python3 scripts/verify-agent-subagents.py [--check]
Uses the Rust standard library only; scripted models, real files and one child thread.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/subagents.rs"
README = ROOT / "docs/public/learn-agent-rust/code/subagents-README.md"
CHAPTER = ROOT / "docs/learn-agent-rust/subagents.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r06-results.json"
OUT = ROOT / "docs/public/learn-agent-rust/outputs"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/subagents-lab.zip"
# scenario, child models/tools/messages/stop, total models/tools/reads/successes,
# parent messages/stop, task goal
SCENARIOS = [
    ("normal", 2, 1, 5, "Completed", 4, 2, 1, 1, 5, "Completed", True),
    ("changed-readme", 2, 1, 5, "Completed", 4, 2, 1, 1, 5, "Completed", True),
    ("missing-file", 2, 1, 4, "MissingFile", 4, 2, 1, 0, 5, "Completed", False),
    ("child-model-budget", 1, 1, 4, "ChildModelBudget", 3, 2, 1, 1, 5, "Completed", False),
    ("child-tool-budget", 1, 0, 4, "ChildToolBudget", 3, 1, 0, 0, 5, "Completed", False),
    ("global-model-budget", 1, 1, 4, "GlobalModelBudget", 2, 2, 1, 1, 4, "GlobalModelBudget", False),
    ("global-tool-budget", 1, 0, 4, "GlobalToolBudget", 3, 1, 0, 0, 5, "Completed", False),
    ("parent-answer-budget", 2, 1, 5, "Completed", 3, 2, 1, 1, 4, "GlobalModelBudget", False),
    ("cancel", 1, 0, 4, "Cancelled", 3, 1, 0, 0, 5, "Completed", False),
    ("cancel-before-start", 0, 0, 2, "Cancelled", 2, 1, 0, 0, 5, "Completed", False),
    ("gate-closed", 1, 0, 4, "Cancelled", 3, 1, 0, 0, 5, "Completed", False),
    ("forbidden-path", 2, 1, 4, "Denied", 4, 2, 0, 0, 5, "Completed", False),
    ("recursive", 2, 1, 4, "Denied", 4, 2, 0, 0, 5, "Completed", False),
    ("invalid-task", 0, 0, 2, "InvalidTask", 2, 1, 0, 0, 5, "Completed", False),
    ("oversized-result", 2, 1, 4, "OutputLimit", 4, 2, 1, 1, 5, "Completed", False),
    ("model-error", 2, 1, 4, "ModelError", 4, 2, 1, 1, 5, "Completed", False),
]


def run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Command failed: {}\n{}\n{}".format(args, result.stdout, result.stderr))
    return result.stdout


def validate_messages(output):
    for prefix in ("父", "子"):
        messages = re.findall(r"^" + prefix + r" (\d+) \| (.*)$", output, re.M)
        if [int(i) for i, _ in messages] != list(range(1, len(messages) + 1)):
            raise ValueError("Non-contiguous history: " + prefix)
        pending, seen = set(), set()
        for _, message in messages:
            match = re.match(r"(assistant|tool) \| call_id=(\S+) ", message)
            if not match:
                if message.startswith("assistant | ") and pending:
                    raise ValueError("Final answer before tool results")
                continue
            role, call_id = match.groups()
            if role == "assistant":
                if call_id in seen:
                    raise ValueError("Reused call ID")
                seen.add(call_id)
                pending.add(call_id)
            else:
                if call_id not in pending:
                    raise ValueError("Unmatched tool result")
                pending.remove(call_id)
        if pending:
            raise ValueError("Unresolved accepted tool call")
    parent = "\n".join(re.findall(r"^父 \d+ \| .*$", output, re.M))
    child = "\n".join(re.findall(r"^子 \d+ \| .*$", output, re.M))
    if "PARENT_ONLY_NOTE" in child or "CHILD_RAW_ONLY" in parent:
        raise ValueError("Fixture history leaked across contexts")
    return parent, child


def table(results):
    lines = ["| 场景 | 子模型 / 工具 | 总模型 / 工具 | 读取尝试 / 成功 | 子停止原因 | 练习目标达成 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in results:
        lines.append("| `{name}` | {child_models} / {child_tools} | {total_models} / {total_tools} | {reads} / {successes} | `{child_stop}` | {goal} |".format(
            **row, goal="是" if row["goal_met"] else "否"))
    return "\n".join(lines)


def package_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo("subagents-lab/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifacts, results = {}, []
    package = {"subagents.rs": SOURCE.read_bytes(), "README.md": README.read_bytes()}
    with tempfile.TemporaryDirectory(prefix="agent-r06-verify-") as directory:
        local = Path(directory) / "subagents.rs"
        shutil.copyfile(SOURCE, local)
        binary = str(Path(directory) / "subagents")
        tests = str(Path(directory) / "subagents-tests")
        run(["rustfmt", "--edition", "2024", "--check", str(local)], directory)
        run(["rustc", "--edition=2024", "-D", "warnings", str(local), "-o", binary], directory)
        run(["rustc", "--edition=2024", "-D", "warnings", "--test", str(local), "-o", tests], directory)
        test_output = run([tests], directory)
        if "9 passed; 0 failed" not in test_output:
            raise ValueError("Rust tests failed")
        for name, *expected in SCENARIOS:
            output = run([binary, name], directory)
            child = re.search(r"子统计：models=(\d+) tools=(\d+) messages=(\d+) stop=(\w+)", output)
            total = re.search(r"总统计：models=(\d+) tools=(\d+) reads=(\d+) successes=(\d+) parent_messages=(\d+) parent_stop=(\w+)", output)
            goal = re.search(r"边界：context_isolated=true fixture_goal_met=(true|false)", output)
            if not (child and total and goal):
                raise ValueError("Missing metrics: " + name)
            actual = [*map(int, child.groups()[:3]), child[4], *map(int, total.groups()[:5]), total[6], goal[1] == "true"]
            if actual != expected:
                raise ValueError("Unexpected scenario {}: {} != {}".format(name, actual, expected))
            if "清理：active_workers=0 scratch_removed=true workspace_removed=true" not in output:
                raise ValueError("Resources left after scenario: " + name)
            parent_text, child_text = validate_messages(output)
            if name == "normal" and "CHILD_RAW_ONLY" not in child_text:
                raise ValueError("Child did not receive actual file contents")
            if name == "changed-readme" and "项目启动命令：cargo run --release" not in parent_text:
                raise ValueError("Parent answer did not follow the changed file")
            if not actual[-1] and total[6] == "Completed" and "任务未完成：" not in parent_text:
                raise ValueError("Failure presented as completed task")
            artifacts[OUT / ("r06-" + name + ".txt")] = output.encode()
            package["outputs/" + name + ".txt"] = output.encode()
            keys = ["child_models", "child_tools", "child_messages", "child_stop", "total_models", "total_tools", "reads", "successes", "parent_messages", "parent_stop", "goal_met"]
            results.append(dict(name=name, **dict(zip(keys, actual)), context_isolated=True,
                                active_workers=0, scratch_removed=True, workspace_removed=True,
                                stdout_sha256=hashlib.sha256(output.encode()).hexdigest()))
        for invalid in [["unknown"], ["normal", "extra"]]:
            p = subprocess.run([binary] + invalid, cwd=directory, capture_output=True, timeout=30)
            if p.returncode == 0:
                raise ValueError("Invalid arguments accepted")
        evidence = dict(scope="R06 scripted parent/child; separate message vectors; shared quotas; real files and one cooperative child thread; no HTTP/framework/database",
                        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                        rustc=run(["rustc", "--version"], directory).strip(),
                        host=run(["rustc", "-vV"], directory).split("host: ")[1].splitlines()[0],
                        contract_tests_passed=9, invalid_cli_cases=2, scenarios=results)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        for key in ("rustc", "host"):
            evidence[key] = recorded[key]
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    artifacts[DATA] = serialized
    package["evidence.json"] = serialized
    environment = "rustc={}\nhost={}\nedition=2024\ndependencies=Rust standard library only\nmodels=scripted parent and child\nexecution=same process, one child thread\nscenarios=16\ncontract_tests=9\n".format(evidence["rustc"], evidence["host"]).encode()
    artifacts[OUT / "r06-environment.txt"] = environment
    package["environment.txt"] = environment
    artifacts[ARCHIVE] = package_bytes(package)
    with tempfile.TemporaryDirectory(prefix="agent-r06-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(artifacts[ARCHIVE])) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "subagents-lab"
        binary = str(folder / "subagents")
        run(["rustc", "--edition=2024", "-D", "warnings", "subagents.rs", "-o", binary], folder)
        for name in ("normal", "cancel"):
            if run([binary, name], folder).encode() != package["outputs/" + name + ".txt"]:
                raise ValueError("Extracted download differs: " + name)
    chapter = CHAPTER.read_text()
    start, end = "<!-- r06-results:start -->", "<!-- r06-results:end -->"
    if chapter.count(start) != 1 or chapter.count(end) != 1:
        raise ValueError("Missing result table markers")
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    artifacts[CHAPTER] = (before + start + "\n\n" + table(results) + "\n\n" + end + after).encode()
    source = SOURCE.read_text()
    for region in re.findall(r"<<< @/public/learn-agent-rust/code/subagents.rs#([\w-]+)", chapter):
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing/duplicate code region: " + region)
    for filename in re.findall(r"<<< @/public/learn-agent-rust/outputs/(r06-[\w-]+\.txt)", chapter):
        if OUT / filename not in artifacts:
            raise ValueError("Unverified output import: " + filename)
    for path, content in artifacts.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R06 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R06: 16 scenarios, 9 Rust contract tests, 2 invalid CLI cases and extracted download passed; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
