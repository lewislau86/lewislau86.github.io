"""Verify the R07 skill-loading lab on ADK-Rust 3.0 / adk-skill.

python3 scripts/verify-agent-skills.py [--check]

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
SLUG = "skill-loading"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/skill-loading.md"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r07-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs", "skills/rust-review/SKILL.md",
         "skills/rust-review/references/checklist.md", "skills/sql-style/SKILL.md"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["normal", "repeat", "two-skills", "changed", "truncated", "permission", "resource", "auto-inject"]
# 场景：(目录条目, load_skill 次数, 正文字节, 读, 写, 审查格式, 错误数)
EXPECTED = {
    "normal": (2, 1, 276, 1, 0, True, 0),
    "no-skill": (2, 0, 0, 1, 0, False, 0),
    "repeat": (2, 2, 552, 1, 0, True, 0),
    "two-skills": (2, 2, 671, 1, 0, True, 0),
    "unknown": (2, 1, 0, 0, 0, False, 1),
    "invalid-name": (2, 1, 0, 0, 0, False, 1),
    "changed": (2, 1, 276, 1, 0, True, 0),
    "broken-skill": (2, 1, 276, 1, 0, True, 0),
    "truncated": (2, 1, 36, 1, 0, False, 0),
    "permission": (2, 1, 341, 1, 0, True, 1),
    "resource": (2, 1, 276, 1, 0, True, 2),
    "resource-compatible": (2, 0, 0, 1, 0, False, 0),
    "resource-escape": (2, 0, 0, 0, 0, False, 1),
    "empty-catalog": (0, 1, 0, 0, 0, False, 1),
    "auto-inject": (2, 0, 307, 1, 0, True, 0),
}
LINE = re.compile(r"^(?P<name>[a-z-]+): catalog=(?P<catalog>\d+) load_skill_calls=(?P<loads>\d+) "
                  r"skill_text_bytes=(?P<bytes>\d+) reads=(?P<reads>\d+) writes=(?P<writes>\d+) "
                  r"review_txt=(?P<review_txt>\w+) injected_up_front=(?P<injected>\w+) "
                  r"review_format=(?P<format>\w+) errors=(?P<errors>\d+)$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        m = LINE.match(line)
        require(m, f"unexpected summary line: {line}")
        rows.append(dict(name=m["name"], catalog=int(m["catalog"]), load_skill_calls=int(m["loads"]),
                         skill_text_bytes=int(m["bytes"]), reads=int(m["reads"]), writes=int(m["writes"]),
                         review_txt=m["review_txt"] == "true", injected_up_front=m["injected"] == "true",
                         review_format=m["format"] == "true", errors=int(m["errors"])))
    return rows


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "skill-loading"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    require([r["name"] for r in rows] == list(EXPECTED), "scenario list changed")
    for row in rows:
        got = (row["catalog"], row["load_skill_calls"], row["skill_text_bytes"], row["reads"], row["writes"],
               row["review_format"], row["errors"])
        require(got == EXPECTED[row["name"]], f"{row['name']}: expected {EXPECTED[row['name']]}, got {got}")
        require(not row["review_txt"], f"{row['name']}: review.txt must never be written")
        require(row["injected_up_front"] == (row["name"] == "auto-inject"), f"{row['name']}: injection mode")
    outputs = {"r07-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r07-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    permission = outputs["r07-permission.txt"]
    require(re.search(r"^request 0: .*tools=\[(?!.*write_file)", permission, re.M), "write_file hidden before load")
    require(re.search(r"^request 2: .*write_file", permission, re.M), "write_file visible after load")
    require("write_file status=refused" in permission, "policy must refuse write_file")
    require("只列证据" not in outputs["r07-changed.txt"], "the index is a snapshot")
    require("[... truncated]" in outputs["r07-truncated.txt"], "truncation marker")
    require(outputs["r07-resource.txt"].count("must be loaded before") >= 2, "activation check")
    two = [l for l in outputs["r07-two-skills.txt"].splitlines() if "state   skill:active:reviewer" in l]
    require(len(two) == 2 and "rust-review" not in two[1], "second activation replaces the first")
    usage = adk.run([binary, "no-such-scenario"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    return outputs, rows


def table(rows):
    lines = ["| 场景 | load_skill 次数 | 进入会话的正文字节 | 读 / 写 | 审查格式 | 错误 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| `{}` | {} | {} | {} / {} | {} | {} |".format(
            r["name"], r["load_skill_calls"], r["skill_text_bytes"], r["reads"], r["writes"],
            "是" if r["review_format"] else "否", r["errors"] or "—"))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r07-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        require(checks["rust_tests_passed"] == 8, f"expected 8 Rust tests, got {checks['rust_tests_passed']}")
        outputs, rows = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R07 on ADK-Rust 3.0 RC adk-skill: load_skill_index, SkillToolset (list/load/load_resource), "
              "ToolRegistry for allowed-tools, SkillInjector comparison; rule-based model, real temp-dir files",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=rows,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    start, end = "<!-- r07-results:start -->", "<!-- r07-results:end -->"
    text = CHAPTER.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[CHAPTER] = chapter.encode()
    stale = [p for p in OUTPUT.glob("r07-*") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R07 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R07 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R07: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
