"""Run the R04 Rust hook lab; save or --check evidence and a standalone zip.

All scenarios run outside the checkout. Worker failures and timeouts are real
child processes; prompt, tool request and prior approval are fixed fixtures.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/learn-agent-rust"
SOURCE = PUBLIC / "code/hooks.rs"
DATA = ROOT / "scripts/data/learn-agent-rust/r04-results.json"
ARCHIVE = PUBLIC / "hooks-lab.zip"
# write attempts, successes, hook failures, result status, stop reason, task ok
CASES = {
    "normal": (1, 1, 0, "ok", "completed", True),
    "prompt-block": (0, 0, 0, None, "prompt_blocked", False),
    "permission-deny": (0, 0, 0, "permission_denied", "permission_denied", False),
    "pre-block": (0, 0, 0, "hook_blocked", "pre_hook_blocked", False),
    "pre-error": (0, 0, 1, "hook_error", "pre_hook_failed", False),
    "pre-panic": (0, 0, 1, "hook_error", "pre_hook_failed", False),
    "pre-timeout": (0, 0, 1, "hook_error", "pre_hook_failed", False),
    "post-error": (1, 1, 1, "ok", "post_hook_failed", False),
    "post-timeout": (1, 1, 1, "ok", "post_hook_failed", False),
    "post-block": (1, 1, 1, "ok", "post_hook_failed", False),
    "tool-error": (1, 0, 0, "tool_error", "tool_failed", False),
    "stop-error": (1, 1, 1, "ok", "completed", False),
    "stop-timeout": (1, 1, 1, "ok", "completed", False),
    "stop-block": (1, 1, 1, "ok", "completed", False),
}
README = """# R04 生命周期与 Hooks

教程：https://lewislau86.github.io/learn-agent-rust/hooks
最低 Rust 1.85，edition 2024；只依赖标准库。下载后从任意目录运行：

    rustc --edition=2024 -D warnings hooks.rs -o hooks
    ./hooks normal
    ./hooks pre-block
    ./hooks pre-panic
    ./hooks pre-timeout
    ./hooks post-error
    ./hooks stop-timeout
    rustc --edition=2024 -D warnings --test hooks.rs -o hook-tests
    ./hook-tests

Windows 将 ./hooks 和 ./hook-tests 换为对应 .exe 路径。
全部场景见源码 SCENARIOS；不带参数默认为 normal。
每次新建并清理临时工作区。请求和既有批准为固定输入，实际写文件。
普通回调在进程内；panic/hang 实验启动本程序的固定 worker 模式。
父进程超时后 kill + wait 回收直属 worker；不实现任意进程树管理或沙箱。
后置回调失败会保留写入结果。Stop 只通知一次，不强制续跑。
本包不提供模型服务、审批 UI、数据库或与 graph-flow 的集成。
outputs/ 和 evidence.json 是生成本包时的实际记录。
"""


def command(args, cwd, timeout=30):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          check=True, timeout=timeout).stdout


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("hooks-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def inspect(name, output):
    lines = output.splitlines()
    match = re.fullmatch(r"stats write_attempts=(\d+) write_successes=(\d+) stop_calls=(\d+) hook_failures=(\d+) summary_matches=(true|false) stop_reason=(\w+) task_ok=(true|false)", lines[-1])
    if not match:
        raise ValueError("Missing counters: " + name)
    attempts, successes, stops, failures = map(int, match.groups()[:4])
    summary, reason, ok = match.groups()[4:]
    result = re.search(r"^result call_id=write-1 status=(\w+)$", output, re.M)
    status = result[1] if result else None
    expected = CASES[name]
    if (attempts, successes, failures, status, reason, ok == "true") != expected:
        raise ValueError("Unexpected result: " + name)
    if stops != 1 or (summary == "true") != (successes == 1):
        raise ValueError("Wrong file or stop state: " + name)
    trace = [line.split("] ", 1)[1] for line in lines if line.startswith("trace[")]
    events = [line[6:] for line in trace if line.startswith("event=")]
    expected_events = ["UserPromptSubmit"]
    if name not in ("prompt-block", "permission-deny"):
        expected_events.append("PreToolUse")
    if attempts:
        expected_events.append("PostToolUse")
    expected_events.append("Stop")
    if events != expected_events:
        raise ValueError("Wrong lifecycle ordering: " + name)
    if name.startswith("pre-") and any("before-log" in line for line in trace):
        raise ValueError("Pre hook chain did not short circuit")
    if name.startswith("post-") and any("after-log" in line for line in trace):
        raise ValueError("Post hook chain did not short circuit")
    expected_fault = ("TimeoutReaped" if name.endswith("timeout") else
                      "WorkerExited" if name == "pre-panic" else
                      "InvalidDecision" if name in ("post-block", "stop-block") else
                      "Reported" if name.endswith("error") and name != "tool-error" else None)
    if expected_fault and not any(line.endswith(":" + expected_fault) for line in lines if line.startswith("hook_failure=")):
        raise ValueError("Missing typed hook fault: " + name)
    if name == "normal":
        ordered = [line for line in trace if line.startswith("hook=")]
        wanted = ["UserPromptSubmit/input-log", "PreToolUse/before-check", "PreToolUse/before-log",
                  "PostToolUse/after-check", "PostToolUse/after-log", "Stop/stop-log"]
        if ordered != ["hook=" + item + " outcome=continue" for item in wanted]:
            raise ValueError("Registration order changed")
    return dict(name=name, write_attempts=attempts, write_successes=successes, stop_calls=stops,
                hook_failures=failures, result_status=status, stop_reason=reason, task_ok=ok == "true",
                summary_matches=summary == "true", events=events, trace=trace,
                stdout_sha256=hashlib.sha256(output.encode()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {}
    package = {"hooks.rs": SOURCE.read_bytes(), "README.md": README.encode()}
    with tempfile.TemporaryDirectory(prefix="agent-r04-verify-") as directory:
        binary = str(Path(directory) / "hooks")
        test_binary = str(Path(directory) / "hook-tests")
        command(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", binary], directory)
        command(["rustc", "--edition=2024", "-D", "warnings", "--test", str(SOURCE), "-o", test_binary], directory)
        tests_output = command([test_binary, "--test-threads=1"], directory)
        tests = re.findall(r"^test tests::(\w+) \.\.\. ok$", tests_output, re.M)
        if len(tests) != 8 or "test result: ok. 8 passed; 0 failed;" not in tests_output:
            raise ValueError("Rust regression tests failed")
        results = []
        for name in CASES:
            output = command([binary, name], directory, timeout=15)
            results.append(inspect(name, output))
            content = output.encode()
            files[PUBLIC / "outputs" / ("r04-" + name + ".txt")] = content
            package["outputs/" + name + ".txt"] = content
        invalid = subprocess.run([binary, "invalid"], cwd=directory, capture_output=True, text=True, timeout=10)
        if invalid.returncode != 2 or "usage:" not in invalid.stderr:
            raise ValueError("Invalid CLI input must fail")
        environment = dict(rustc=command(["rustc", "--version"], directory).strip(), platform=platform.platform())
    if args.check and DATA.exists():
        environment = json.loads(DATA.read_text())["environment"]
    evidence = dict(scope="R04 single tool round; fixed approved call; real file I/O and owned child workers; no LLM or graph integration",
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), environment=environment,
                    regression_tests=tests, scenarios=results)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    files[DATA] = serialized
    package["evidence.json"] = serialized
    files[ARCHIVE] = archive_bytes(package)
    # Use the actual published zip in check mode, not just a reconstructed copy.
    archive_content = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else files[ARCHIVE]
    with tempfile.TemporaryDirectory(prefix="agent-r04-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "hooks-lab"
        binary = str(folder / "hooks")
        command(["rustc", "--edition=2024", "-D", "warnings", "hooks.rs", "-o", binary], folder)
        for name in ("normal", "pre-timeout", "post-error", "stop-timeout"):
            if command([binary, name], folder).encode() != package["outputs/" + name + ".txt"]:
                raise ValueError("Extracted download differs: " + name)
    for path, content in files.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R04 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R04: 14 scenarios, 8 regression tests and extracted download passed; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
