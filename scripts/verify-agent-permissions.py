"""Run R03 in isolation and save/check its transcripts, evidence and download.

python3 scripts/verify-agent-permissions.py [--check]
Only the Python standard library and a Rust compiler (edition 2024) are needed.
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
SOURCE = PUBLIC / "code/permissions.rs"
DATA = ROOT / "scripts/data/learn-agent-rust/r03-results.json"
ARCHIVE = PUBLIC / "permissions-lab.zip"
# (write attempts, successful writes, tool results, pending, summary matches)
SCENARIOS = {
    "read": (0, 0, 1, False, False),
    "deny": (0, 0, 2, False, False),
    "invalid-path": (0, 0, 2, False, False),
    "unknown": (0, 0, 2, False, False),
    "wait": (0, 0, 1, True, False),
    "approve": (1, 1, 2, False, True),
    "decline": (0, 0, 2, False, False),
    "tamper": (0, 0, 1, True, False),
    "replay": (1, 1, 2, False, True),
    "write-error": (1, 0, 2, False, False),
}
README = """# R03 工具权限与审批实验

教程正文以网站为准：https://lewislau86.github.io/learn-agent-rust/permissions
需要支持 edition 2024 的 Rust 稳定工具链（Rust 1.85 或更新）。无第三方依赖。

在解压后的目录中运行：

    rustc --edition=2024 -D warnings permissions.rs -o permissions
    ./permissions approve
    ./permissions wait
    ./permissions decline
    ./permissions tamper
    ./permissions replay
    ./permissions write-error
    rustc --edition=2024 -D warnings --test permissions.rs -o permission-tests
    ./permission-tests

Windows 用户将 ./permissions 与 ./permission-tests 换成对应 .exe 路径。
全部场景：read deny invalid-path unknown wait approve decline tamper replay write-error。
每次运行创建并清理自己的临时工作区，不需要从教程仓库启动。
模型请求与人工回复由程序固定生成，实际调用 std::fs 读写文件。
wait 只在本次进程内保留状态；再次启动命令会创建新会话。
这不是通用文件系统沙箱，也不提供真实模型、认证 UI 或跨进程恢复。
outputs/ 与 evidence.json 是生成学习包时的实际运行记录。
"""


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("permissions-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {}
    package = {"permissions.rs": SOURCE.read_bytes(), "README.md": README.encode()}
    scenarios = []
    with tempfile.TemporaryDirectory(prefix="agent-r03-verify-") as directory:
        folder = Path(directory)
        executable = str(folder / "permissions")
        tests = str(folder / "permission-tests")
        run(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", executable], directory)
        run(["rustc", "--edition=2024", "-D", "warnings", "--test", str(SOURCE), "-o", tests], directory)
        test_output = run([tests, "--test-threads=1"], directory)
        test_names = re.findall(r"^test tests::(\w+) \.\.\. ok$", test_output, re.M)
        if len(test_names) != 6 or "test result: ok. 6 passed; 0 failed;" not in test_output:
            raise ValueError("R03 regression tests did not all pass")
        for name, expected in SCENARIOS.items():
            output = run([executable, name], directory)
            match = re.search(r"^stats read_attempts=(\d+) write_attempts=(\d+) write_successes=(\d+) tool_results=(\d+) pending=(true|false) summary_matches=(true|false) readme_unchanged=(true|false)$", output, re.M)
            if not match:
                raise ValueError("Missing counters: " + name)
            reads, attempts, successes, results = map(int, match.groups()[:4])
            pending, summary, unchanged = [value == "true" for value in match.groups()[4:]]
            if reads != 1 or not unchanged or (attempts, successes, results, pending, summary) != expected:
                raise ValueError("Wrong counters or filesystem state: " + name)
            statuses = re.findall(r"^tool_result call_id=(\S+) status=(\S+)", output, re.M)
            if len(statuses) != results or statuses[0] != ("read-1", "ok"):
                raise ValueError("Incorrect tool-result pairing: " + name)
            if name in ("deny", "invalid-path", "unknown") and statuses[-1] != ("write-1", "denied"):
                raise ValueError("Policy refusal was lost")
            if name == "decline" and statuses[-1] != ("write-1", "declined"):
                raise ValueError("Human refusal was lost")
            if name == "write-error" and statuses[-1] != ("write-1", "tool_error"):
                raise ValueError("Execution failure was reported as success")
            if name == "tamper" and "rejected_input reason=approval_mismatch" not in output:
                raise ValueError("Changed approval was accepted")
            if name in ("replay", "write-error") and "rejected_input reason=no_pending_approval" not in output:
                raise ValueError("Approval replay was accepted")
            files[PUBLIC / "outputs" / ("r03-" + name + ".txt")] = output.encode()
            package["outputs/" + name + ".txt"] = output.encode()
            scenarios.append(dict(name=name, read_attempts=reads, write_attempts=attempts,
                                  write_successes=successes, tool_results=results,
                                  pending=pending, summary_matches=summary, readme_unchanged=unchanged,
                                  statuses=statuses, stdout_sha256=hashlib.sha256(output.encode()).hexdigest()))
        invalid = subprocess.run([executable, "invalid-scenario"], cwd=directory, capture_output=True, text=True)
        if invalid.returncode != 2 or "usage:" not in invalid.stderr:
            raise ValueError("Invalid CLI scenario must fail")
        environment = dict(rustc=run(["rustc", "--version"], directory).strip(), platform=platform.platform())
    if args.check and DATA.exists():
        # Preserve the toolchain used to first publish these transcripts.
        environment = json.loads(DATA.read_text())["environment"]
    evidence = dict(scope="R03; scripted tool requests and trusted simulated human replies; std::fs; in-memory only",
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    environment=environment, regression_tests=test_names, scenarios=scenarios)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    files[DATA] = serialized
    package["evidence.json"] = serialized
    files[ARCHIVE] = zip_bytes(package)
    # Also compile and run the actual archive in a separate extracted directory.
    with tempfile.TemporaryDirectory(prefix="agent-r03-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(files[ARCHIVE])) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "permissions-lab"
        executable = str(folder / "permissions")
        run(["rustc", "--edition=2024", "-D", "warnings", "permissions.rs", "-o", executable], folder)
        if run([executable, "approve"], folder).encode() != package["outputs/approve.txt"]:
            raise ValueError("Downloaded example differs from the website example")
    for path, content in files.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R03 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R03: 10 scenarios, 6 regression tests, extracted download passed; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
