"""Verify the R08 context-compaction lab on ADK-Rust 3.0.

python3 scripts/verify-agent-compaction.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要和几条详细轨迹各连跑两次必须逐字节相同，逐项核对场景，并把结果表写进正文。
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
SLUG = "context-compaction"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/context-compaction.md"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r08-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["normal", "intra", "naive-trim", "omit-fact", "omit-unchecked", "not-smaller"]
# 场景：(摘要器结果, 压缩事件数, 审查模型请求数, 技能加载次数, 给出结论, 写明未运行测试)
EXPECTED = {
    "normal": ("accepted,accepted", 2, 9, 2, True, True),
    "small": ("", 0, 8, 1, True, True),
    "intra": ("accepted", 1, 8, 2, True, True),
    "naive-trim": ("", 0, 8, 2, False, False),
    "omit-fact": ("rejected compaction.summary_facts,rejected compaction.summary_facts", 0, 8, 1, True, True),
    "omit-unchecked": ("accepted,accepted", 2, 8, 2, False, False),
    "invent-fact": ("rejected compaction.summary_facts,rejected compaction.summary_facts", 0, 8, 1, True, True),
    "bad-json": ("rejected compaction.summary_schema,rejected compaction.summary_schema", 0, 8, 1, True, True),
    "summary-error": ("failed model.unavailable,failed model.unavailable", 0, 8, 1, True, True),
    "not-smaller": ("accepted,accepted", 0, 8, 1, True, True),
}
LINE = re.compile(r"^(?P<name>[a-z-]+): summary_calls=\[(?P<calls>[^\]]*)\] compactions=(?P<compactions>\d+) "
                  r"review_calls=(?P<review>\d+) skill_loads=(?P<loads>\d+) conclusion=(?P<conclusion>\w+) "
                  r"says_untested=(?P<untested>\w+)$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        m = LINE.match(line)
        require(m, f"unexpected summary line: {line}")
        rows.append(dict(name=m["name"], summary_calls=m["calls"], compactions=int(m["compactions"]),
                         review_calls=int(m["review"]), skill_loads=int(m["loads"]),
                         conclusion=m["conclusion"] == "true", says_untested=m["untested"] == "true"))
    return rows


def est_tokens(detail):
    return [int(n) for n in re.findall(r"^request \d+: .* est_tokens=(\d+)$", detail, re.M)]


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "context-compaction"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    require([r["name"] for r in rows] == list(EXPECTED), "scenario list changed")
    for row in rows:
        got = (row["summary_calls"], row["compactions"], row["review_calls"], row["skill_loads"],
               row["conclusion"], row["says_untested"])
        require(got == EXPECTED[row["name"]], f"{row['name']}: expected {EXPECTED[row['name']]}, got {got}")
    outputs = {"r08-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r08-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    normal = est_tokens(outputs["r08-normal.txt"])
    require(normal[5] > 1000 and normal[6] < normal[5] // 5, f"normal tokens {normal}")
    intra = est_tokens(outputs["r08-intra.txt"])
    # 读完第三份资料后历史超过 1000，压缩后第 5 次请求回到阈值以下：摘要通知 + 最后一对调用与结果
    require(intra[5] < 1000 and "intra: summary_calls=[accepted] compactions=1" in summary, f"intra tokens {intra}")
    require(re.search(r"^request 5: roles=system,user,model,function tools=", outputs["r08-intra.txt"], re.M),
            "intra request 5 must keep only the last call/result pair after the summary")
    require("missing_evidence" in outputs["r08-naive-trim.txt"], "naive-trim must lose the target")
    usage = adk.run([binary, "no-such-scenario"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    return outputs, rows, {"normal": normal, "intra": intra}


def table(rows):
    lines = ["| 场景 | 摘要器结果 | 压缩事件 | 审查模型请求 | 技能加载 | 给出结论 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        calls = r["summary_calls"].replace(",", "，") or "—"
        lines.append("| `{}` | {} | {} | {} | {} | {} |".format(
            r["name"], calls, r["compactions"], r["review_calls"], r["skill_loads"],
            "是" if r["conclusion"] else "否"))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r08-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        outputs, rows, tokens = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R08 on ADK-Rust 3.0 RC: EventsCompactionConfig between runs, IntraCompactionConfig within a run, "
              "history_max_events trim, application FactSummarizer gate; rule-based models, real temp-dir files",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=rows, est_tokens=tokens,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    start, end = "<!-- r08-results:start -->", "<!-- r08-results:end -->"
    text = CHAPTER.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[CHAPTER] = chapter.encode()
    stale = [p for p in OUTPUT.glob("r08-*") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R08 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R08 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R08: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
