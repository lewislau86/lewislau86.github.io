"""Verify R11 typed recovery, real filesystem effects and reproducible downloads."""
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
SOURCE = PUBLIC / "code/error-recovery.rs"
DATA = ROOT / "scripts/data/learn-agent-rust/r11-results.json"
ARCHIVE = PUBLIC / "error-recovery-lab.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/error-recovery.md"
# stop, calls, last call attempts, waited ms, virtual now ms, reads, appends
CASES = {
    "normal": ("completed", 1, 1, 0, 10, 1, 0),
    "transient": ("completed", 2, 2, 100, 120, 1, 0),
    "backoff": ("completed", 3, 3, 300, 330, 1, 0),
    "attempt-limit": ("attempt_limit", 3, 3, 300, 330, 0, 0),
    "call-budget": ("call_budget", 2, 2, 100, 120, 0, 0),
    "wait-budget": ("wait_budget", 2, 2, 100, 120, 0, 0),
    "deadline": ("deadline", 1, 1, 0, 10, 0, 0),
    "retry-after": ("completed", 2, 2, 250, 270, 1, 0),
    "retry-after-too-long": ("deadline", 1, 1, 0, 10, 0, 0),
    "permission-denied": ("failed", 0, 0, 0, 0, 0, 0),
    "invalid-input": ("failed", 0, 0, 0, 0, 0, 0),
    "missing-file": ("failed", 1, 1, 0, 10, 0, 0),
    "permanent": ("failed", 1, 1, 0, 10, 0, 0),
    "append-ok": ("completed", 1, 1, 0, 10, 0, 1),
    "append-unknown": ("needs_reconciliation", 1, 1, 0, 10, 0, 1),
    "resume-budget": ("call_budget", 2, 2, 100, 120, 0, 0),
    "resume-cooldown": ("completed", 2, 2, 100, 120, 1, 0),
    "resume-expired": ("deadline", 1, 1, 0, 200, 0, 0),
    "cancelled-backoff": ("cancelled", 1, 1, 0, 10, 0, 0),
    "revoked-backoff": ("failed", 1, 1, 0, 10, 0, 0),
    "shared-budget": ("call_budget", 3, 0, 300, 330, 1, 0),
}
README = """# 错误分类与恢复

教程：https://lewislau86.github.io/learn-agent-rust/error-recovery
最低 Rust 1.85，edition 2024；只依赖标准库，无需 Python、密钥或数据库。

    rustc --edition=2024 -D warnings error-recovery.rs -o recovery
    ./recovery backoff
    ./recovery resume-budget
    ./recovery append-unknown
    rustc --edition=2024 -D warnings --test error-recovery.rs -o recovery-tests
    ./recovery-tests

默认使用自动清理的临时目录；可提供一个尚不存在的目录，保留实际文件供检查：

    ./recovery append-unknown ./inspect-unknown

现有目录会被拒绝，不覆盖其中内容。Windows 使用对应 .exe。
全部 21 个场景见源码 SCENARIOS。不带参数等同 normal。
故障、Retry-After 值、每次尝试耗时与等待均为注入，虚拟时间不实际 sleep。
成功读取、缺文件错误和日志追加由标准库真实执行。
暂停和恢复只发生在同一进程，转移原状态的所有权并复用累计账本。
截止时间限制下次尝试的准入，不中断正在执行的文件 I/O。
写入结果不明后停止；本包不实现自动对账、业务幂等或断电持久性。
没有模型服务、消息协议集成、上下文压缩、模型切换或 graph-flow 集成。
outputs/ 与 evidence.json 是打包时的实际记录。
"""


def command(args, cwd, timeout=30):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          check=True, timeout=timeout).stdout


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("error-recovery-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def check_chapter(results, outputs):
    chapter = CHAPTER.read_text()
    table = ["| 场景 | 停止原因 | 调用 | 等待 ms | 日志行 |",
             "| --- | --- | --- | --- | --- |"]
    table.extend("| `{name}` | `{stop}` | {calls} | {waited_ms} | {lines} |".format(**row)
                 for row in results)
    expected = "<!-- r11-results:start -->\n" + "\n".join(table) + "\n<!-- r11-results:end -->"
    if expected not in chapter:
        raise ValueError("R11 chapter result table differs from verified scenarios")
    source = SOURCE.read_text()
    for region in re.findall(r"<<< @/public/learn-agent-rust/code/error-recovery.rs#([\w-]+)", chapter):
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing or ambiguous source region: " + region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r11-([\w-]+).txt", chapter):
        if name not in outputs:
            raise ValueError("Unknown imported output: " + name)


def inspect(name, output, workspace):
    match = re.search(r"^stats stop=(\w+) calls=(\d+) last_attempts=(\d+) waited_ms=(\d+) now_ms=(\d+) results=(\d+) logical_calls=(\d+) reads=(\d+) appends=(\d+) lines=(\d+) paused=(true|false)$",
                      output, re.M)
    if not match:
        raise ValueError("Missing stats: " + name)
    stop = match[1]
    calls, attempts, waited, now, results, logical, reads, appends, lines = map(int, match.groups()[1:10])
    paused = match[11] == "true"
    if (stop, calls, attempts, waited, now, reads, appends) != CASES[name]:
        raise ValueError("Wrong result: " + name)
    expected_logical = 2 if name == "shared-budget" else 1
    if results != expected_logical or logical != expected_logical:
        raise ValueError("Each logical call must have exactly one terminal result")
    if lines != appends or appends > 1:
        raise ValueError("Duplicate append: " + name)
    log = workspace / "events.log"
    if appends:
        if log.read_bytes() != b"startup=cargo run\n":
            raise ValueError("Incorrect actual append: " + name)
    elif log.exists():
        raise ValueError("Unexpected side effect: " + name)
    readme = workspace / "README.md"
    if name == "missing-file":
        if readme.exists():
            raise ValueError("Missing-file fixture did not remove file")
    elif readme.read_bytes() != b"cargo run\n":
        raise ValueError("Read-only input changed")
    trace = [line.split("] ", 1)[1] for line in output.splitlines() if line.startswith("trace[")]
    dispatches = [re.fullmatch(r"attempt call_id=(\S+) attempt=(\d+) started_ms=(\d+)", line)
                  for line in trace if line.startswith("attempt ")]
    if len(dispatches) != calls or any(item is None for item in dispatches):
        raise ValueError("Calls differ from actual attempt trace")
    results_trace = [line for line in trace if line.startswith("result ")]
    if len(results_trace) != results:
        raise ValueError("Duplicate terminal result on reentry")
    result_ids = [re.fullmatch(r"result call_id=(\S+) status=(\w+)", line) for line in results_trace]
    expected_ids = ["read-1", "read-2"] if name == "shared-budget" else ["append-1" if name.startswith("append-") else "read-1"]
    if any(item is None for item in result_ids) or [item[1] for item in result_ids] != expected_ids:
        raise ValueError("Logical call identity changed during retry")
    read_value_matches = "read_value_matches=true" in output.splitlines()
    if read_value_matches != (reads == 1 and stop == "completed" and appends == 0):
        raise ValueError("Successful read did not return actual file content")
    if calls and [int(item[2]) for item in dispatches] != list(range(1, calls + 1)):
        raise ValueError("Attempt count reset on continuation")
    starts = [int(item[3]) for item in dispatches]
    if name in ("backoff", "attempt-limit", "shared-budget") and starts != [0, 110, 320]:
        raise ValueError("Backoff timeline changed")
    if name == "resume-budget" and "pause attempts=1 calls=1 waited_ms=0 due_ms=110" not in trace:
        raise ValueError("Missing owned continuation state")
    failure = re.search(r"^last_failure=(.+)$", output, re.M)[1]
    expected_failure = {
        "permission-denied": "Some(PermissionDenied)",
        "revoked-backoff": "Some(PermissionDenied)",
        "invalid-input": "Some(InvalidInput)",
        "missing-file": "Some(Permanent)",
        "permanent": "Some(Permanent)",
        "append-unknown": "Some(OutcomeUnknown)",
    }.get(name)
    if expected_failure and failure != expected_failure:
        raise ValueError("Error classification changed: " + name)
    return dict(name=name, stop=stop, calls=calls, last_attempts=attempts, waited_ms=waited,
                now_ms=now, results=results, logical_calls=logical, reads=reads, appends=appends,
                lines=lines, paused=paused, starts_ms=starts, trace=trace,
                stdout_sha256=hashlib.sha256(output.encode()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {}
    package = {"error-recovery.rs": SOURCE.read_bytes(), "README.md": README.encode()}
    with tempfile.TemporaryDirectory(prefix="agent-r11-verify-") as directory:
        root = Path(directory)
        binary = str(root / "recovery")
        tests_bin = str(root / "recovery-tests")
        command(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", binary], directory)
        command(["rustc", "--edition=2024", "-D", "warnings", "--test", str(SOURCE), "-o", tests_bin], directory)
        tests_output = command([tests_bin, "--test-threads=1"], directory)
        tests = re.findall(r"^test tests::(\w+) \.\.\. ok$", tests_output, re.M)
        if len(tests) != 13 or "test result: ok. 13 passed; 0 failed;" not in tests_output:
            raise ValueError("Rust regression tests failed")
        results = []
        for name in CASES:
            workspace = root / name
            output = command([binary, name, str(workspace)], directory)
            results.append(inspect(name, output, workspace))
            files[PUBLIC / "outputs" / ("r11-" + name + ".txt")] = output.encode()
            package["outputs/" + name + ".txt"] = output.encode()
        # External directory preservation is verified separately from Rust's result counters.
        sentinel = root / "existing"
        sentinel.mkdir()
        (sentinel / "keep.txt").write_bytes(b"keep\n")
        rejected = subprocess.run([binary, "normal", str(sentinel)], cwd=directory, capture_output=True)
        if rejected.returncode != 1 or sorted(p.name for p in sentinel.iterdir()) != ["keep.txt"] or (sentinel / "keep.txt").read_bytes() != b"keep\n":
            raise ValueError("Existing directory was not preserved")
        invalid = subprocess.run([binary, "invalid"], cwd=directory, capture_output=True)
        if invalid.returncode != 2 or b"usage:" not in invalid.stderr:
            raise ValueError("Invalid CLI input must fail")
        environment = dict(rustc=command(["rustc", "--version"], directory).strip(), platform=platform.platform())
    check_chapter(results, CASES)
    if args.check and DATA.exists():
        environment = json.loads(DATA.read_text())["environment"]
    evidence = dict(scope="R11 typed read retry and ambiguous append; injected faults and virtual clock; real file I/O; same-process continuation",
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    environment=environment, regression_tests=tests, scenarios=results)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    files[DATA] = serialized
    package["evidence.json"] = serialized
    files[ARCHIVE] = archive_bytes(package)
    content = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else files[ARCHIVE]
    with tempfile.TemporaryDirectory(prefix="agent-r11-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "error-recovery-lab"
        binary = str(folder / "recovery")
        command(["rustc", "--edition=2024", "-D", "warnings", "error-recovery.rs", "-o", binary], folder)
        for name in CASES:
            workspace = Path(directory) / name
            output = command([binary, name, str(workspace)], folder)
            inspect(name, output, workspace)
            if output.encode() != package["outputs/" + name + ".txt"]:
                raise ValueError("Downloaded source differs: " + name)
    for path, content in files.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R11 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R11: 21 scenarios, 13 Rust tests, actual file assertions and extracted download passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
