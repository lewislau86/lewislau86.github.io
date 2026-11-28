"""Verify the R09 cross-session memory lab on ADK-Rust 3.0.

python3 scripts/verify-agent-memory.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要和几条详细轨迹各连跑两次必须逐字节相同（每一步都是程序自己启动的独立子进程），
逐行核对场景，再按 README 跑一遍全部 chat / erase 命令，并把结果表写进正文。
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
SLUG = "memory"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/memory.md"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r09-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["new-process", "naive-load", "preload", "tool-origin", "erase", "corrupt"]
RUST_TESTS = 6
FOUND_ZH = "recall:found 中文 from session-A versions=1 answer=中文"
MISSING = "recall:missing answer=default"
# 场景 → (子进程数, 每一步的结果, 文件检查)
EXPECTED = {
    "new-process": (2, ["remember:saved", FOUND_ZH], ""),
    "update": (3, ["remember:saved", "remember:saved",
                   "recall:found English from session-C versions=2 answer=English"], ""),
    "repeat": (3, ["remember:saved", "remember:unchanged", FOUND_ZH], ""),
    "naive-load": (4, ["remember:saved", "remember:saved", "load_memory:count=2 first=中文 answer=中文",
                       "recall:found English from session-C versions=2 answer=English"], ""),
    "preload": (3, ["remember:saved", "preload:injected=0 answer=default", "preload:injected=1 answer=中文"], ""),
    "scope": (4, ["remember:saved", MISSING, MISSING, FOUND_ZH], ""),
    "eager-model": (2, ["remember:rejected not_from_user", MISSING], ""),
    "tool-origin": (3, ["remember:saved", "read_note remember:rejected not_from_user", FOUND_ZH], ""),
    "unknown-key": (1, ["remember:rejected unknown_key"], "file_has_abc123=no"),
    "forget": (4, ["remember:saved", "remember:saved", "forget:removed=2", MISSING], "file_has_English=yes"),
    "erase": (5, ["remember:saved", "remember:saved", "erase:removed=2 compact=false",
                  "erase:removed=0 compact=true", MISSING],
              "after_delete_file_has_English=yes after_compact_file_has_English=no"),
    "corrupt": (1, ["error migration registry creation failed: (code: 26) file is not a database"],
                "bytes_unchanged=yes"),
    "truncated": (2, ["remember:saved", "error migration registry creation failed: (code: 11) database disk image is malformed"],
                  "bytes_unchanged=yes"),
    "schema-newer": (2, ["remember:saved", "error schema version mismatch: database is at v99 but code only knows up to v3"],
                     "bytes_unchanged=yes"),
}
LINE = re.compile(r"^(?P<name>[a-z-]+): processes=(?P<n>\d+) steps=\[(?P<steps>.*)\](?: (?P<checks>.+))?$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        m = LINE.match(line)
        require(m, f"unexpected summary line: {line}")
        rows.append(dict(name=m["name"], processes=int(m["n"]), steps=m["steps"].split("; "),
                         checks=m["checks"] or ""))
    return rows


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "memory"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    require([r["name"] for r in rows] == list(EXPECTED), "scenario list changed")
    for row in rows:
        got = (row["processes"], row["steps"], row["checks"])
        require(got == EXPECTED[row["name"]], f"{row['name']}: expected {EXPECTED[row['name']]}, got {got}")
    outputs = {"r09-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r09-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    # 第二个进程的第一次请求只有系统消息和这一轮的用户输入：上一个进程的会话没有带过来
    second = outputs["r09-new-process.txt"].split("--- process 2:", 1)[1]
    require(re.search(r"^request 0: roles=system,user tools=", second, re.M), "process 2 must start empty")
    require("[preload] […] user: reply_language=中文" in outputs["r09-preload.txt"], "preload must show the injected memory")
    require('"timestamp":"…"' in outputs["r09-naive-load.txt"], "load_memory timestamps must be scrubbed")
    # 按 README 手动走一遍：两个 chat 进程共用 demo.db
    db = folder / "demo.db"
    first = adk.run([binary, "chat", db, "user-1", "project-a", "session-A", "请记住：reply_language=中文"], folder, env)
    require(first.stdout.rstrip().endswith("outcome: remember:saved"), first.stdout)
    second = adk.run([binary, "chat", db, "user-1", "project-a", "session-B", "以后请用什么语言回答？"], folder, env)
    require(second.stdout.rstrip().endswith(f"outcome: {FOUND_ZH}"), second.stdout)
    other = adk.run([binary, "chat", db, "user-1", "project-b", "session-C", "以后请用什么语言回答？"], folder, env)
    require(other.stdout.rstrip().endswith(f"outcome: {MISSING}"), other.stdout)
    pre = adk.run([binary, "chat", db, "user-1", "project-a", "session-D", "以后请用什么语言回答？", "--recall", "preload"],
                  folder, env)
    require(pre.stdout.rstrip().endswith("outcome: preload:injected=0 answer=default"), pre.stdout)
    erased = adk.run([binary, "erase", db, "user-1", "--compact"], folder, env)
    require(erased.stdout.strip() == "outcome: erase:removed=1 compact=true", erased.stdout)
    db.unlink()
    usage = adk.run([binary, "no-such-scenario"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    bad = adk.run([binary, "chat", folder / "x.db", "u", "p", "s", "hi", "--recall", "nope"], folder, env, ok=(2,))
    require("usage:" in bad.stderr, "bad --recall must print usage")
    return outputs, rows


def table(rows):
    lines = ["| 场景 | 独立子进程 | 每一步的结果 | 文件检查 |", "| --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| `{}` | {} | {} | {} |".format(
            r["name"], r["processes"], "<br>".join(f"`{s}`" for s in r["steps"]),
            " ".join(f"`{c}`" for c in r["checks"].split()) or "—"))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r09-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        require(checks["rust_tests_passed"] == RUST_TESTS, f"expected {RUST_TESTS} Rust tests, got {checks}")
        outputs, rows = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R09 on ADK-Rust 3.0 RC: adk-memory SqliteMemoryService in a file shared by separate processes, "
              "application remember/recall_memory/forget tools, adk-tool LoadMemoryTool and PreloadMemoryTool, "
              "delete_user plus FTS optimize and VACUUM; rule-based model",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=rows,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    start, end = "<!-- r09-results:start -->", "<!-- r09-results:end -->"
    text = CHAPTER.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[CHAPTER] = chapter.encode()
    stale = [p for p in OUTPUT.glob("r09-*") if p not in targets]
    old_archive = adk.PUBLIC / "memory-lab.zip"
    if old_archive.exists():
        stale.append(old_archive)
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R09 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R09 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R09: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
