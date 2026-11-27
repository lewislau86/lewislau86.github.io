"""Verify the R04 Cargo package (ADK-Rust 3.0): callback order and failure consequences.

python3 scripts/verify-agent-hooks.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，然后 fmt、clippy、cargo test、离线构建；
15 个场景各连跑两次必须逐字节相同（stdout），核对计数、结果状态、停止原因与回调顺序；非法参数以退出码 2 结束。
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
SLUG = "hooks"
OUTPUT = adk.PUBLIC / "outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r04-results.json"
ARCHIVE = adk.PUBLIC / "hooks.zip"
OBSOLETE = [adk.PUBLIC / "hooks-lab.zip", adk.PUBLIC / "figures/r04-worker-timeout.svg"]
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
# 场景：(写入尝试, 写入成功, 回调失败数, 结果状态, 停止原因, 任务通过)，以及必须 / 不能出现的回调
SCENARIOS = {
    "normal": ((1, 1, 0, "ok", "final_answer", True), ["after_agent/stop-log"], []),
    "prompt-block": ((0, 0, 0, "none", "final_answer", False), ["after_agent/stop-log"], ["before_tool/"]),
    "prompt-error": ((0, 0, 1, "none", "hook.failed", False), [], ["after_agent/", "before_tool/"]),
    "permission-deny": ((0, 0, 0, "refused", "final_answer", False), ["before_tool/before-log"], ["after_tool/"]),
    "pre-block": ((0, 0, 0, "not_run", "final_answer", False), ["after_tool/after-log"], ["before_tool/before-log"]),
    "pre-error": ((0, 0, 1, "not_run", "final_answer", False), ["after_agent/stop-log"], ["before_tool/before-log", "after_tool/"]),
    "pre-panic": ((0, 0, 1, "not_run", "final_answer", False), ["after_agent/stop-log"], ["before_tool/before-log", "after_tool/"]),
    "pre-timeout": ((0, 0, 1, "not_run", "final_answer", False), ["after_agent/stop-log"], ["before_tool/before-log", "after_tool/"]),
    "post-error": ((1, 1, 1, "withheld", "final_answer", False), ["after_agent/stop-log"], ["after_tool/after-log"]),
    "post-timeout": ((1, 1, 1, "withheld", "final_answer", False), ["after_agent/stop-log"], ["after_tool/after-log"]),
    "post-rewrite": ((1, 1, 0, "ok", "final_answer", True), ["after_agent/stop-log"], ["after_tool/after-log"]),
    "tool-error": ((1, 0, 0, "failed", "final_answer", False), ["after_tool/after-log"], []),
    "stop-error": ((1, 1, 1, "ok", "hook.failed", False), ["after_agent/stop-log"], []),
    "stop-timeout": ((1, 1, 1, "ok", "hook.timeout", False), ["after_agent/stop-log"], []),
    "stop-rewrite": ((1, 1, 0, "ok", "final_answer", True), ["after_agent/stop-log"], []),
}
STATS = re.compile(r"统计：write_attempts=(\d+) write_successes=(\d+) hook_failures=(\d+) result_status=(\S+) "
                   r"stop=(\S+) summary_written=(true|false) task_ok=(true|false)")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    targets = {ARCHIVE: packed}
    env = adk.cargo_env("learn-agent-r04-target")
    rows = []
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r04"
        for name, (expected, must, must_not) in SCENARIOS.items():
            output = adk.repeat_identical([binary, name], folder, env, times=2)
            m = STATS.search(output)
            require(m is not None, f"{name}: no stats\n{output}")
            got = (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5), m.group(7) == "true")
            require(got == expected, f"{name}: {got} != {expected}")
            hooks = [line[5:] for line in output.splitlines() if line.startswith("hook ")]
            for item in must:
                require(any(h.startswith(item) for h in hooks), f"{name}: expected hook {item}")
            for item in must_not:
                require(not any(h.startswith(item) for h in hooks), f"{name}: unexpected hook {item}")
            if name == "normal":
                order = [h.split(" ")[0] for h in hooks]
                require(order == ["before_agent/input-log", "before_agent/input-check", "before_tool/before-check",
                                  "before_tool/before-log", "after_tool/after-check", "after_tool/after-log",
                                  "after_agent/stop-log"], f"normal order {order}")
            stop_runs = sum(h.startswith("after_agent/stop-log") for h in hooks)
            require(stop_runs <= 1, f"{name}: stop hook ran {stop_runs} times")
            targets[OUTPUT / f"r04-{name}.txt"] = output.encode()
            rows.append(dict(name=name, write_attempts=got[0], write_successes=got[1], hook_failures=got[2],
                             result_status=got[3], stop=got[4], task_ok=got[5], summary_written=m.group(6) == "true",
                             hooks=hooks, stdout_sha256=sha(output.encode())))
        p = adk.run([binary, "nope"], folder, env, ok=(2,))
        require("usage:" in p.stderr, "invalid scenario must print usage")
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R04 on ADK-Rust 3.0 RC: agent and tool callbacks registered in order, an application ToolPolicy, "
              "callbacks that continue / respond / fail / panic / time out, real temporary files, ScriptedLlm",
        **header, source_sha256={name: sha(data) for name, data in sorted(files.items())},
        archive_sha256=sha(packed), **checks, repeated_identical_runs=2, scenarios=rows)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    stale = [p for p in OUTPUT.glob("r04-*.txt") if p not in targets] + [p for p in OBSOLETE if p.exists()]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R04 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R04 artifacts: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R04: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy, usage error; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
