"""Verify the K01 RAG lab on ADK-Rust 3.0 / adk-rag.

python3 scripts/verify-agent-rag.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
suite 在两个新目录各跑一次必须逐字节相同，逐项核对场景，并检查资料目录里文件的实际变化。
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
SLUG = "retrieval-augmented-generation"
OUTPUT = adk.PUBLIC / "outputs"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/k01-results.json"
CORPUS = ["release.md", "operations.md", "untrusted.md", "private.md"]
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs", *[f"corpus/{n}" for n in CORPUS]]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}

SUITE = [
    "scenario=normal\nquote=Upgrade v2 requires Rust 1.99.1. Run cargo test before publishing.\n"
    "citation=A/release.md:L3-L3@63c4bb1531c9478b",
    "scenario=no-hit\nabstain=no_evidence",
    "scenario=zero-score threshold=0.0 hits=2 scores=[0.000,0.000] first=A/operations.md:L3-L3\n"
    "quote=Backup the database before schema migration.",
    "scenario=scope visible_hits_a=1 private_leak=false visible_hits_b=1 b_documents=[B/private.md]",
    "scenario=budget\nabstain=no_evidence",
    "scenario=injection cited=A/untrusted.md:L3-L3 quoted_as_data=true generator=fixture actions=0",
    "scenario=bad-citation unsupported_quote_rejected=true unknown_id_rejected=true",
    "scenario=evaluation embedder=hashed-words labeled_queries=4 recall_at_2=3/4 mrr_at_2=0.750",
    "scenario=lexical-gap\nabstain=no_evidence",
    "scenario=swap-embedder embedder=synonym-table recall_at_2=4/4 mrr_at_2=1.000\n"
    "quote=Rollback: restore the previous release after a failed migration.",
    "scenario=collision dims=4 query=unicorn hits=1",
    "scenario=stale rejected=stale_index",
    "scenario=updated chunks_in_a=5\nquote=Upgrade v2 requires Rust 2.00.0.",
    "scenario=deleted rejected=source_missing removed_chunks=2 rebuilt_hits=0",
    "scenario=agent-cited\n[assistant] call    id=scripted_tc_0_0 rag_search {\"query\":\"upgrade Rust\"}",
    "[assistant] source  kb://A/release.md#L3-L3",
    "[assistant] cites   kb://A/release.md#L3-L3\n[assistant] final\nscenario=agent-uncited",
    "[run] error   guardrail.output_blocked",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def suite_once(binary, folder, env):
    with tempfile.TemporaryDirectory(prefix="k01-") as work:
        target = Path(work) / "case"
        text = adk.run([binary, "suite", target], folder, env).stdout
        # 资料真的被改过、删过；其他文件保持原样；agent 场景用的是另一份新资料
        require(not (target / "release.md").exists(), "suite must delete release.md")
        for name in ["operations.md", "untrusted.md", "private.md"]:
            require((target / name).read_bytes() == (folder / "corpus" / name).read_bytes(), name)
        require((target / "agent/release.md").read_bytes() == (folder / "corpus/release.md").read_bytes(),
                "agent corpus must stay untouched")
        # 已存在的目标目录必须拒绝，并且一个字节都不动
        before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        adk.run([binary, "suite", target], folder, env, ok=(2,))
        after = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        require(before == after, "refusing an existing directory must leave it unchanged")
    return text


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "rag-lab"
    first = suite_once(binary, folder, env)
    require(first == suite_once(binary, folder, env), "suite output differs between two runs")
    for fragment in SUITE:
        require(fragment in first, f"suite: missing {fragment!r}\n{first}")
    require(first.count("scenario=") == 16, "expected 16 scenarios")
    corpus = folder / "corpus"
    query = adk.repeat_identical([binary, "query", corpus, "A", "upgrade Rust"], folder, env, times=2)
    require(query.startswith("quote=Upgrade v2 requires Rust 1.99.1.") and "citation=A/release.md:L3-L3@" in query,
            query)
    gap = adk.run([binary, "query", corpus, "A", "revert disaster"], folder, env).stdout
    require(gap == "abstain=no_evidence\n", gap)
    unknown = adk.run([binary, "query", corpus, "unknown", "upgrade"], folder, env).stdout
    require(unknown == "abstain=no_evidence\n", unknown)
    private = adk.run([binary, "query", corpus, "B", "upgrade"], folder, env).stdout
    require("citation=B/private.md:" in private, private)
    usage = adk.run([binary, "unknown"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown command must print usage")
    return {"k01-suite.txt": first, "k01-query.txt": query}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-k01-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        outputs = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="K01 on ADK-Rust 3.0 RC adk-rag: InMemoryVectorStore, deterministic word-hash embedder, "
              "extractive generation fixture, ScriptedLlm for the RagTool/CitationRequired scenarios; no network",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=16, labeled_queries=4,
        recall_at_2={name: int(found) / 4 for name, found in
                     re.findall(r"embedder=([a-z-]+)[^\n]*?recall_at_2=(\d)/4", outputs["k01-suite.txt"])},
        held_out=False,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    targets = {OUTPUT / name: text.encode() for name, text in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale K01 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    print(f"K01: 16 scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
