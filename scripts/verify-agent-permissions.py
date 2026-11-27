"""Verify the R03 Cargo package (ADK-Rust 3.0): policy, held calls, approvals bound to the exact call.

python3 scripts/verify-agent-permissions.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，然后 fmt、clippy、cargo test、离线构建；
10 个场景各连跑两次必须逐字节相同，核对读写计数、等待中的请求、结果状态；非法参数必须以退出码 2 结束。
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
SLUG = "permissions"
OUTPUT = adk.PUBLIC / "outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r03-results.json"
ARCHIVE = adk.PUBLIC / "permissions.zip"
OLD_ARCHIVE = adk.PUBLIC / "permissions-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
# 场景：(读取尝试, 写入尝试, 写入成功, 工具结果, 仍在等待, 摘要正确)，以及写入调用最后的结果状态
SCENARIOS = {
    "read": ((1, 0, 0, 1, 0, False), None),
    "deny": ((1, 0, 0, 2, 0, False), "refused"),
    "invalid-path": ((1, 0, 0, 2, 0, False), "refused"),
    "unknown": ((1, 0, 0, 2, 0, False), "not_run"),
    "wait": ((1, 0, 0, 2, 1, False), "held"),
    "approve": ((1, 1, 1, 3, 0, True), "ok"),
    "decline": ((1, 0, 0, 3, 0, False), "refused"),
    "tamper": ((1, 0, 0, 2, 1, False), "held"),
    "replay": ((1, 1, 1, 4, 1, True), "held"),
    "write-error": ((1, 1, 0, 4, 1, False), "held"),
}
STATS = re.compile(r"统计：read_attempts=(\d+) write_attempts=(\d+) write_successes=(\d+) tool_results=(\d+) "
                   r"pending=(\d+) summary_matches=(true|false) readme_unchanged=(true|false)")


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
    env = adk.cargo_env("learn-agent-r03-target")
    rows = []
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r03"
        for name, (expected, last_write) in SCENARIOS.items():
            output = adk.repeat_identical([binary, name], folder, env, times=2)
            m = STATS.search(output)
            require(m is not None, f"{name}: no stats\n{output}")
            got = tuple(int(x) for x in m.groups()[:5]) + (m.group(6) == "true",)
            require(got == expected, f"{name}: {got} != {expected}")
            require(m.group(7) == "true", f"{name}: README must stay unchanged")
            statuses = re.findall(r"\] result  id=\S+ (\S+) status=(\S+)", output)
            require(statuses[0] == ("read_file", "ok"), f"{name}: first result must be the README read")
            writes = [s for tool, s in statuses if tool != "read_file"]
            require((writes[-1] if writes else None) == last_write, f"{name}: last write status {writes}")
            if name in ("approve", "replay", "write-error"):
                # 恢复时执行的是原来等待的那次调用：同一个调用 ID（写入失败时同样如此）
                held = re.search(r"\] result  id=(\S+) write_summary status=held", output).group(1)
                done = "ok" if name != "write-error" else "failed"
                require(f"] result  id={held} write_summary status={done}" in output, f"{name}: resumed call id")
            targets[OUTPUT / f"r03-{name}.txt"] = output.encode()
            rows.append(dict(name=name, read_attempts=got[0], write_attempts=got[1], write_successes=got[2],
                             tool_results=got[3], pending=got[4], summary_matches=got[5], readme_unchanged=True,
                             statuses=[f"{t}:{s}" for t, s in statuses], stdout_sha256=sha(output.encode())))
        p = adk.run([binary, "nope"], folder, env, ok=(2,))
        require("usage:" in p.stderr, "invalid scenario must print usage")
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R03 on ADK-Rust 3.0 RC: ScriptedLlm, an application ToolPolicy (allow / deny / require approval), "
              "InMemoryApprovalStore decisions keyed by call fingerprint, real temporary files",
        **header, source_sha256={name: sha(data) for name, data in sorted(files.items())},
        archive_sha256=sha(packed), **checks, repeated_identical_runs=2, scenarios=rows)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    stale = [p for p in OUTPUT.glob("r03-*.txt") if p not in targets] + ([OLD_ARCHIVE] if OLD_ARCHIVE.exists() else [])
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R03 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R03 artifacts: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R03: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy, usage error; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
