"""Verify the R02 Cargo package (ADK-Rust 3.0) and generate reproducible course artifacts.

python3 scripts/verify-learn-agent-rust-r02.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
本脚本把章节打成下载包，在临时目录解压、旁边放好 adk-rust/，然后：
fmt、clippy -D warnings、cargo test、离线构建；默认演示连跑 3 次必须逐字节相同；
逐个场景生成两条路径（Runner 直接运行 LlmAgent / 放进图里运行）的对照 JSON，并检查场景契约。
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402
from learn_agent_rust_adk import require  # noqa: E402

ROOT = adk.ROOT
SLUG = "tools-and-graph"
PACKAGE = adk.CODE / SLUG
OUTPUT = adk.PUBLIC / "outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r02-results.json"
ARCHIVE = adk.PUBLIC / "tools-and-graph.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}

# 每个场景的契约：模型调用次数、工具结果条数、停止原因（None 表示模型给出最终回答）、回答是否通过检查，
# 以及轨迹里必须出现的片段。旧版（graph-flow）的 9 个场景全部保留或拆细，映射写在正文第 6 节。
CASES = {
    "normal": (3, 2, None, True, ["list_files status=ok", "read_file status=ok"]),
    "batch": (2, 2, None, True, ["id=scripted_tc_0_0 list_files", "id=scripted_tc_0_1 read_file"]),
    "unknown-tool": (2, 1, None, False, ["search_files status=not_run", "Tool search_files not found"]),
    "invalid-args": (2, 1, None, False, ["status=failed code=tool.invalid_arguments", "is not of type \\\"string\\\""]),
    "extra-field": (2, 1, None, False, ["status=failed", "Additional properties are not allowed"]),
    "invalid-json": (2, 1, None, False, ["read_file status=not_run", "arguments are not valid JSON"]),
    "not-an-object": (2, 1, None, False, ["status=failed", "is not of type \\\"object\\\""]),
    "outside-path": (2, 1, None, False, ["code=path.not_allowed", "outside this tool's scope"]),
    "missing-file": (3, 2, None, False, ["(file.missing): README.md does not exist"]),
    "unreadable-file": (3, 2, None, False, ["tool 'read_file' failed: tool.unavailable (file.unreadable)\"}"]),
    "unreadable-file-exposed": (3, 2, None, False, ["code=file.unreadable", "read README.md: Is a directory"]),
    "duplicate-id": (2, 2, None, True, ["id=call-1 list_files status=ok", "id=call-1 read_file status=ok"]),
    "zero-budget": (0, 0, "budget.model_calls", False, []),
    "turn-limit": (1, 1, "agent.legacy", False, ["list_files status=ok"]),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_report(name, report):
    calls, results, stop, ok, fragments = CASES[name]
    direct = report["direct"]
    require(report["scenario"] == name and report["equal"] is True, f"{name}: direct and graph differ")
    got = (direct["model_calls"], direct["tool_results"], direct["error"], direct["verified"])
    require(got == (calls, results, stop, ok), f"{name}: {got} != {(calls, results, stop, ok)}")
    text = "\n".join(direct["trace"])
    for fragment in fragments:
        require(fragment in text, f"{name}: trace lacks {fragment!r}\n{text}")
    # 每个调用恰好得到一条结果（按出现顺序比较 ID；duplicate-id 场景里两条 ID 相同，同样成立）
    ids = lambda kind: [l.split("id=")[1].split(" ")[0] for l in direct["trace"] if f"] {kind} " in l]
    require(ids("call   ") == ids("result "), f"{name}: calls and results are not paired")
    if direct["answer"] is not None:
        require(report["graph_check"] == direct["verified"], f"{name}: graph check disagrees")
    else:
        require(report["graph_check"] is None, f"{name}: graph should stop before check_answer")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    targets = {ARCHIVE: packed}
    env = adk.cargo_env("learn-agent-r02-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r02"
        summary = adk.repeat_identical([binary], folder, env)
        targets[OUTPUT / "r02-summary.txt"] = summary.encode()
        reports = []
        for name in CASES:
            output = adk.run([binary, "--json", name], folder, env).stdout
            report = json.loads(output)
            check_report(name, report)
            reports.append(report)
            targets[OUTPUT / f"r02-{name}.json"] = output.encode()
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R02 on ADK-Rust 3.0 RC: ScriptedLlm, real temporary directory, in-memory sessions; "
              "Runner(LlmAgent) compared with Runner(GraphAgent wrapping the same agent)",
        **header,
        source_sha256={name: sha(data) for name, data in sorted(files.items())},
        archive_sha256=sha(packed),
        **checks,
        repeated_identical_runs=3,
        scenarios=reports,
    )
    if args.check and DATA.exists():  # 保留记录时的环境，便于在另一台兼容机器上检查
        recorded = json.loads(DATA.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[DATA] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    stale_outputs = [p for p in OUTPUT.glob("r02-*.json") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R02 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if args.check:
        require(not stale_outputs, "Obsolete R02 outputs: " + ", ".join(p.name for p in stale_outputs))
    else:
        for path in stale_outputs:
            path.unlink()
    print(f"R02: {len(CASES)} scenario pairs, {checks['rust_tests_passed']} Rust tests, fmt, Clippy, "
          "3 identical runs; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
