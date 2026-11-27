"""P02 ADK-Rust 3.0 part: real process exits around a non-idempotent tool, durable action ledger.

python3 scripts/verify-agent-effects-adk.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
每个场景用独立进程依次运行 first / recover / retry，进程退出由程序在工具内或工具之后注入；
最后用 inspect 读回 SQLite 会话里的轨迹和外部工单数，逐项核对契约。整套场景连跑两遍，输出必须逐字节相同。

工程在专题 2 章节目录的 adk/ 子目录（code/side-effect-reliability/adk/），随专题 2 的下载包发布；
scripts/verify-agent-effects.py 打包时会调用本脚本（带相同的 --check）。
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402
from learn_agent_rust_adk import require  # noqa: E402

ROOT = adk.ROOT
SLUG = "side-effect-reliability/adk"
OUTPUT = adk.PUBLIC / "outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/p02adk-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", ".cargo/config.toml",
         "src/main.rs", "src/trace.rs"]

# 场景：依次运行的步骤 (阶段, 选项, 期望退出码)，以及最终会话里最后一条结果的状态
# （轨迹里的 status 是注解值：already_succeeded 的注解是 succeeded）、外部服务被调用次数、外部工单数。
SCENARIOS = {
    "normal": ([("first", [], 0)], "ok", 1, 1),
    "crash-in-tool": ([("first", ["--crash", "in-tool"], 9), ("recover", [], 0)], "outcome_unknown", 1, 1),
    "crash-after-tool": ([("first", ["--crash", "after-tool"], 9), ("recover", [], 0)], "succeeded", 1, 1),
    "retry-call-key": ([("first", ["--crash", "in-tool"], 9), ("recover", [], 0), ("retry", [], 0)], "ok", 2, 2),
    "retry-business-key": ([("first", ["--crash", "in-tool", "--key", "business"], 9), ("recover", [], 0),
                            ("retry", ["--key", "business"], 0)], "ok", 2, 1),
    "memory-ledger": ([("first", ["--crash", "after-tool", "--ledger", "memory"], 9),
                       ("recover", ["--ledger", "memory"], 0)], "outcome_unknown", 1, 1),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run_suite(binary, folder, env):
    reports, text = [], []
    for name, (steps, last_status, attempts, tickets) in SCENARIOS.items():
        with tempfile.TemporaryDirectory(prefix=f"p02adk-{name}-") as state:
            commands = []
            for phase, options, code in steps:
                p = adk.run([binary, state, phase, *options], folder, env, ok=(code,))
                commands.append(dict(command=" ".join([phase, *options]), exit_code=p.returncode,
                                     stderr=p.stderr.strip()))
            inspect = adk.run([binary, state, "inspect"], folder, env).stdout.splitlines()
        results = [l for l in inspect if "] result " in l]
        status = results[-1].split("status=")[1].split(" ")[0]
        count = int(inspect[-1].split("=")[1])
        calls = int(inspect[-2].split("=")[1])
        require(status == last_status, f"{name}: last status {status} != {last_status}")
        # 恢复只补答案：外部服务被调用的次数不因 recover 增加
        require(calls == attempts, f"{name}: provider attempts {calls} != {attempts}")
        require(count == tickets, f"{name}: provider tickets {count} != {tickets}")
        if name == "retry-business-key":
            require('"deduplicated":true' in results[-1], f"{name}: provider did not deduplicate")
        if name.startswith("crash") or name == "memory-ledger":
            require(len(results) == 1, f"{name}: recovery must not execute the tool again")
        reports.append(dict(scenario=name, steps=commands, trace=inspect, last_status=status,
                            provider_attempts=calls, provider_tickets=count))
        text.append(f"== {name}")
        text += [f"$ {c['command']}  # exit={c['exit_code']}" + (f" {c['stderr']}" if c["stderr"] else "") for c in commands]
        text += inspect
        text.append("")
    return reports, "\n".join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    packed = adk.pack(SLUG, files)  # 只用于在临时目录里按读者的布局构建；发布的 zip 由 verify-agent-effects.py 生成
    targets = {}
    env = adk.cargo_env("learn-agent-p02adk-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-p02-adk"
        reports, summary = run_suite(binary, folder, env)
        _, again = run_suite(binary, folder, env)
        require(summary == again, "P02 ADK suite output differs between two runs")
        header = adk.evidence_header(folder, env)
    targets[OUTPUT / "p02adk-summary.txt"] = (summary + "\n").encode()
    evidence = dict(
        scope="P02 ADK-Rust 3.0 part: ScriptedLlm, SQLite session + SqliteActionLedger in one file, "
              "real process exits injected in/after a non-idempotent tool, file-backed provider that dedupes by operation",
        **header,
        source_sha256={name: sha(data) for name, data in sorted(files.items())},
        **checks, repeated_identical_suites=2, scenarios=reports)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale P02 ADK artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f"P02 ADK: {len(SCENARIOS)} crash/recovery scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, "
          "fmt, Clippy; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
