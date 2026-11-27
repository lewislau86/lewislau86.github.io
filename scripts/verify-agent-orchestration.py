"""Verify the three graph-orchestration labs (G01–G03) on ADK-Rust 3.0 / adk-graph.

python3 scripts/verify-agent-orchestration.py [--check] [--lab G01|G02|G03]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
每个实验：打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
场景各连跑两次必须逐字节相同，并逐项核对契约。G02 的每条命令是一个独立进程，状态只在 SQLite 检查点里。
"""
import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402
from learn_agent_rust_adk import require  # noqa: E402

ROOT = adk.ROOT
OUTPUT = adk.PUBLIC / "outputs"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}

G01 = {
    "normal": ["scenario=normal outcome=accepted repairs=1 draft=2", "trace=prepare>check>repair>check>accept", "step=4 ran=accept"],
    "exhausted": ["scenario=exhausted outcome=needs_human repairs=2", "trace=prepare>check>repair>check>repair>check>repair>handoff"],
    "runaway": ["steps_run=12", "recursion_limit=12 error=RecursionLimitExceeded", "saved_state trace_len=12 repairs=0 outcome=none"],
    "probes": ["dangling_edge rejected_at_compile=true", "missing_start rejected_at_compile=true",
               "bad_goto rejected_at_run=true", "unmapped_route rejected_at_run=true", "no_edge completed=true",
               'two_edges ran=["a","b","c"]', 'typo_channel trace=["a"] traces="b"', "strict_channels rejected=true",
               'local_mutation x="original"', "malformed_required rejected=true", "counter_channel n=2.0"],
}
G03 = {
    "normal": ["step=1 ran=license,security", "step=2 ran=merge", "verdict=ready security_runs=1 license_runs=1"],
    "failure": ["first_run error=node_failed node=security security_runs=1 license_runs=1",
                "resumed verdict=ready security_runs=2 license_runs=1"],
    "collision": ["overwrite: count=1.0 expected=2", "counter: count=2.0 expected=2"],
    "subgraph": ['parent risk="high" scratch_exported=false', "wrong_mapping rejected_at_compile=true"],
    "timeout": ["on_timeout=fail error=node_timed_out node=license", "on_timeout=skip verdict=incomplete"],
}
LABS = {
    "G01": ("graph-state-routing", "graph-state-lab", G01),
    "G02": ("graph-pause-resume", "graph-resume-lab", None),
    "G03": ("graph-parallel-subgraphs", "graph-parallel-lab", G03),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scenario_lab(binary, folder, env, cases):
    outputs = {}
    for name, fragments in cases.items():
        text = adk.repeat_identical([binary, name], folder, env, times=2)
        for fragment in fragments:
            require(fragment in text, f"{name}: missing {fragment!r}\n{text}")
        outputs[name] = text
    p = adk.run([binary, "unknown"], folder, env, ok=(2,))
    require("usage:" in p.stderr, "unknown scenario must print usage")
    return outputs


# G02：每个流程在新的临时目录里依次运行独立进程；暂停 ID 由框架按线程、步骤、节点、问题算出，可复现
FLOWS = ["approved", "rejected", "revised", "loose", "conflict", "tampered"]


def resume_flow(binary, folder, env, flow):
    lines, last_id = [], None
    with tempfile.TemporaryDirectory(prefix="g02-") as work:
        db = Path(work) / "review.db"

        def call(*args, db_path=db):
            text = adk.run([binary, db_path, *args], folder, env).stdout
            lines.append("$ " + " ".join(["lab", Path(db_path).name, *args]))
            lines.append(text.rstrip())
            found = re.search(r"interrupt=(int_[0-9a-f]+)", text)
            return text, (found.group(1) if found else None)

        if flow == "approved":
            _, pid = call("init")
            call("show")
            text, _ = call("answer", pid, "approve")
            require("outcome=approved" in text and "render=1" in text, text)
            text, _ = call("show")
            require("approve=3" in text, "a completed thread must not rerun nodes")
            text, _ = call("answer", pid, "approve")
            require("resume_rejected" in text, "a second answer must be refused")
        elif flow == "rejected":
            _, pid = call("init")
            text, _ = call("answer", pid, "reject")
            require("outcome=rejected" in text and "render=0" in text, text)
        elif flow == "revised":
            _, pid = call("init")
            text, new = call("answer", pid, "revise")
            require("revision=2" in text and new and new != pid, text)
            text, _ = call("answer", pid, "approve")
            require("resume_rejected" in text, "an answer for the old pause must be refused")
            text, _ = call("answer", new, "approve")
            require("revision=2 report=upgrade report: revision 2 approved" in text, text)
        elif flow == "loose":
            _, pid = call("init")
            text, _ = call("answer", pid, "maybe")
            require("resume_rejected" in text, "an answer outside the schema must be refused")
            call("answer", pid, "revise")
            text, _ = call("answer-loose", "approve")
            # 按节点名回答，批准落到了第 2 版——审批人只看过第 1 版
            require("revision=2" in text and "outcome=approved" in text, text)
        elif flow == "conflict":
            _, pid = call("init")
            text, _ = call("conflict", pid)
            require("status=refused reason=checkpoint_conflict" in text and "render=1" in text, text)
            require(text.count("status=completed") == 1, text)
        elif flow == "tampered":
            call("init")
            text, _ = call("tamper", "rename")
            require("reason=graph_version" in text and "approve=1" in text, text)
            text, _ = call("tamper", "rename-unchecked")
            require("outcome=none" in text and "trace=draft" in text, text)
            db2 = Path(work) / "second" / "review.db"  # 新目录：runs.log 也从零开始
            db2.parent.mkdir()
            call("init", db_path=db2)
            text, _ = call("tamper", "corrupt", db_path=db2)
            require("kind=checkpoint_unreadable" in text, text)
    return "\n".join(lines).replace("review.db", "DB") + "\n"


def resume_lab(binary, folder, env):
    outputs = {}
    for flow in FLOWS:
        first = resume_flow(binary, folder, env, flow)
        require(first == resume_flow(binary, folder, env, flow), f"{flow}: output differs between two runs")
        outputs[flow] = first
    p = adk.run([binary], folder, env, ok=(2,))
    require("usage:" in p.stderr, "missing arguments must print usage")
    return outputs


def verify_lab(lab, check):
    slug, binary_name, cases = LABS[lab]
    files = adk.chapter_files(slug, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(slug, files)
    archive = adk.PUBLIC / f"{slug}.zip"
    targets = {archive: packed}
    env = adk.cargo_env(f"learn-agent-{lab.lower()}-target")
    with adk.staged(slug, packed) as folder:
        checks = adk.standard_checks(folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / binary_name
        outputs = resume_lab(binary, folder, env) if cases is None else scenario_lab(binary, folder, env, cases)
        header = adk.evidence_header(folder, env)
    for name, text in outputs.items():
        targets[OUTPUT / f"{lab.lower()}-{name}.txt"] = text.encode()
    data = ROOT / f"scripts/data/learn-agent-rust/{lab.lower()}-results.json"
    evidence = dict(
        scope=f"{lab} on ADK-Rust 3.0 RC adk-graph: deterministic business nodes, no model provider"
              + ("; independent CLI processes over a SQLite checkpointer" if cases is None else ""),
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=sorted(outputs),
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if check and data.exists():
        recorded = json.loads(data.read_text())
        evidence["rustc"], evidence["cargo"] = recorded["rustc"], recorded["cargo"]
    targets[data] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    stale = [p for p in OUTPUT.glob(f"{lab.lower()}-*.txt") if p not in targets]
    for path, content in targets.items():
        if check:
            require(path.exists() and path.read_bytes() == content, f"Stale {lab} artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if check:
        require(not stale, f"Obsolete {lab} outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"{lab}: {len(outputs)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if check else "artifacts saved"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--lab", choices=sorted(LABS))
    args = parser.parse_args()
    for lab in ([args.lab] if args.lab else sorted(LABS)):
        verify_lab(lab, args.check)
    if not args.lab:
        print("Graph orchestration verified: G01/G02/G03 on adk-graph")


if __name__ == "__main__":
    main()
