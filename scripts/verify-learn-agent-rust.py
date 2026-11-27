"""Verify the R00 Cargo package (ADK-Rust 3.0) and generate reproducible course artifacts.

python3 scripts/verify-learn-agent-rust.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，然后 fmt、clippy、cargo test、离线构建；
三种模式各连跑两次必须逐字节相同，并核对计数、轨迹与结果；非法参数必须以退出码 2 结束。
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
SLUG = "architecture-and-setup"
OUTPUT = adk.PUBLIC / "outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r00-results.json"
ARCHIVE = adk.PUBLIC / "architecture-and-setup.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
# 模式：命令行参数，(模型调用, 工具结果, 读取尝试, 读取成功, 会话事件, 结果, 工具结果状态)
MODES = {
    "normal": ([], (2, 1, 1, 1, 4, "completed", "status=ok")),
    "deny": (["--deny"], (2, 1, 0, 0, 4, "denied", "status=refused")),
    "missing-file": (["--missing-file"], (2, 1, 1, 0, 4, "missing_file", "status=failed code=file.missing")),
}
STATS = re.compile(r"统计：model_calls=(\d+) tool_results=(\d+) read_attempts=(\d+) read_successes=(\d+) "
                   r"session_events=(\d+) outcome=(\S+)")


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
    env = adk.cargo_env("learn-agent-r00-target")
    scenarios = []
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r00"
        for name, (flags, expected) in MODES.items():
            output = adk.repeat_identical([binary, *flags], folder, env, times=2)
            match = STATS.search(output)
            require(match is not None, f"{name}: no stats line\n{output}")
            got = tuple(int(x) for x in match.groups()[:5]) + (match.group(6),)
            require(got == expected[:6], f"{name}: {got} != {expected[:6]}")
            require(expected[6] in output, f"{name}: trace lacks {expected[6]!r}")
            answer = re.search(r'\] text    "([^"]*)"', output).group(1)
            require(answer.endswith("cargo run") == (name == "normal"), f"{name}: unexpected answer {answer}")
            require(answer.startswith("任务未完成：") == (name != "normal"), f"{name}: failure must be reported")
            # 每个调用恰好得到一条结果，且 ID 相同
            ids = [re.search(r"id=(\S+)", l).group(1) for l in output.splitlines() if "] call " in l or "] result " in l]
            require(len(ids) == 2 and ids[0] == ids[1], f"{name}: call/result pairing {ids}")
            # 第二次请求必须带上模型的调用和工具结果：上下文变长，参数不变
            require("request 1: roles=system,user,model,function tools=[read_file]" in output, f"{name}: request history")
            kinds = {"call": "model", "result": "function", "text": "model"}
            roles = ["user"] + [kinds[m] for m in re.findall(r"^\[assistant\] (call|result|text) ", output, re.M)]
            require(len(roles) == got[4], f"{name}: roles {roles} vs session events {got[4]}")
            targets[OUTPUT / f"r00-{name}.txt"] = output.encode()
            scenarios.append(dict(name=name, args=flags, model_turns=got[0], tool_requests=got[1],
                                  read_attempts=got[2], read_successes=got[3], messages=got[4],
                                  roles=roles, outcome=got[5],
                                  stdout_sha256=sha(output.encode()), exit_code=0))
        bad = adk.run([binary, "--unknown"], folder, env, ok=(2,))
        require("usage:" in bad.stderr, "invalid argument must print usage")
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R00 on ADK-Rust 3.0 RC: ScriptedLlm, FunctionTool reading a real temporary README, "
              "DeclarativePolicy allow/deny, in-memory session",
        **header, source_sha256={name: sha(data) for name, data in sorted(files.items())},
        archive_sha256=sha(packed), **checks, repeated_identical_runs=2, scenarios=scenarios)
    if args.check and DATA.exists():
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R00 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f"R00: 3 modes x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy, usage error; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
