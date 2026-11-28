"""Verify the R10 system-prompt assembly lab on ADK-Rust 3.0.

python3 scripts/verify-agent-prompts.py [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
打包章节、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要和几条详细轨迹各连跑两次必须逐字节相同，逐行核对场景，并把结果表写进正文。
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
SLUG = "system-prompts"
OUTPUT = adk.PUBLIC / "outputs"
CHAPTER = ROOT / "docs/learn-agent-rust/system-prompts.md"
EVIDENCE = ROOT / "scripts/data/learn-agent-rust/r10-results.json"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}
DETAILS = ["normal", "skill-in-system", "state-midrun", "braces", "knowledge-injection"]
RUST_TESTS = 6
OK = "model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文"
SQL = "model_calls=1 skill=sql-style@{} tools=[] answer=no_command"
# 每个场景的摘要行（“ | ”分开的几项），逐字核对
EXPECTED = {
    "normal": [OK, "prefix_stable_within_run=yes", "session_has_skill=no"],
    "repeat": [OK, "prefix_same=yes user_same=yes", "request_identical=yes"],
    "skill-switch": [f"first: {OK}", "second: " + SQL.format("user"), "prefix_same=yes user_same=no"],
    "skill-in-system": [f"first: {OK.replace('@user', '@system')}", "second: " + SQL.format("system"),
                        "prefix_same=no user_same=no"],
    "env-change": [OK.replace("answer=中文", "answer=English"), "prefix_same=no user_same=yes"],
    "state-midrun": ["run1: model_calls=3 skill=startup@user tools=[set_locale:ok,read_file:ok] answer=中文 "
                     "locales=[zh-CN,zh-CN,zh-CN]",
                     "run2: " + OK.replace("answer=中文", "answer=English") + " locales=[en-US,en-US]"],
    "tool-change": ["model_calls=1 skill=startup@user tools=[] answer=no_command", "prefix_same=no user_same=yes"],
    "braces": ["in_instruction: model_calls=0 skill=- tools=[] answer=error: agent.invalid_input: "
               "State variable 'window_id' not found", f"in_static: {OK} verbatim=yes"],
    "agents-as-skill": [OK, "agents_md_in_request=no"],
    "skill-update": [OK, "prefix_same=yes user_same=no"],
    "stale-skill": ["agent_built=no refused=stale_skill: startup"],
    "knowledge-injection": ["model_calls=2 skill=startup@user tools=[write_file:refused] answer=no_command",
                            "injected_text_role=user", "summary_exists=no"],
    "budget": ["model_calls=0 skill=- tools=[] answer=request_budget bytes=563"],
}
REQUEST = re.compile(r"^request (\d+): roles=(\S+) tools=\[([^\]]*)\] prefix=([0-9a-f]{12}) "
                     r"user_turn=([0-9a-f]{12}) locale=(\S+) skill=(\S+) bytes=(\d+)$", re.M)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        name, rest = line.split(": ", 1)
        rows.append(dict(name=name, parts=rest.split(" | ")))
    return rows


def verify(folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / "system-prompts"
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    require([r["name"] for r in rows] == list(EXPECTED), "scenario list changed")
    for row in rows:
        require(row["parts"] == EXPECTED[row["name"]], f"{row['name']}: expected {EXPECTED[row['name']]}, got {row['parts']}")
    outputs = {"r10-summary.txt": summary}
    for name in DETAILS:
        outputs[f"r10-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    normal = REQUEST.findall(outputs["r10-normal.txt"])
    require(len(normal) == 2 and normal[0][1] == "system,system,user" and normal[1][1] == "system,system,user,model,function",
            f"normal requests {normal}")
    require(normal[0][2] == "read_file,set_locale,write_file", "tool declarations keep registration order")
    require(normal[0][3] == normal[1][3], "prefix must stay the same within the run")
    require('[user] "[skill:startup]' in outputs["r10-normal.txt"], "the skill must sit in the user turn")
    contents = outputs["r10-normal.txt"].split("request 0 contents:")[1].splitlines()
    require(contents[1].startswith('  [system] "你是只读项目助手') and "不要猜命令" in contents[1],
            "policy and AGENTS.md must be the first system message")
    roles = REQUEST.findall(outputs["r10-skill-in-system.txt"])
    require(all(r[1].startswith("system,system,system,user") for r in roles), "skill-in-system adds a system message")
    require("move that text to `static_instruction`" in outputs["r10-braces.txt"], "braces error must name static_instruction")
    require('[assistant] state   locale = "en-US"' in outputs["r10-state-midrun.txt"], "set_locale must write the state")
    require(int(EXPECTED["budget"][0].rsplit("=", 1)[1]) > 300, "budget scenario must exceed 300 bytes")
    midrun = REQUEST.findall(outputs["r10-state-midrun.txt"])
    require([m[5] for m in midrun] == ["zh-CN"] * 3 + ["en-US"] * 2, f"state-midrun locales {midrun}")
    injected = outputs["r10-knowledge-injection.txt"]
    require("status=refused" in injected and "denied by policy" in injected, "write_file must be refused by the policy")
    usage = adk.run([binary, "no-such-scenario"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, "unknown scenario must print usage")
    return outputs, rows


def table(rows):
    lines = ["| 场景 | 结果 |", "| --- | --- |"]
    for r in rows:
        lines.append("| `{}` | {} |".format(r["name"], "<br>".join(f"`{p}`" for p in r["parts"])))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = adk.chapter_files(SLUG, FILES)
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(SLUG, files)
    archive = adk.PUBLIC / f"{SLUG}.zip"
    env = adk.cargo_env("learn-agent-r10-target")
    with adk.staged(SLUG, packed) as folder:
        checks = adk.standard_checks(folder, env)
        require(checks["rust_tests_passed"] == RUST_TESTS, f"expected {RUST_TESTS} Rust tests, got {checks}")
        outputs, rows = verify(folder, env)
        header = adk.evidence_header(folder, env)
    evidence = dict(
        scope="R10 on ADK-Rust 3.0 RC: static_instruction / instruction templates / global_instruction_provider, "
              "with_skills injection into the user turn, ToolDeclarations order, DeclarativePolicy, before_model "
              "budget; rule-based model records every request; real temp-dir files",
        **header, source_sha256={n: sha(d) for n, d in sorted(files.items())}, archive_sha256=sha(packed),
        **checks, repeated_identical_runs=2, scenarios=rows,
        outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if args.check and EVIDENCE.exists():
        recorded = json.loads(EVIDENCE.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    start, end = "<!-- r10-results:start -->", "<!-- r10-results:end -->"
    text = CHAPTER.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[EVIDENCE] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[CHAPTER] = chapter.encode()
    stale = [p for p in OUTPUT.glob("r10-*") if p not in targets]
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"Stale R10 artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if args.check:
        require(not stale, "Obsolete R10 outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"R10: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if args.check else "artifacts saved"), flush=True)


if __name__ == "__main__":
    main()
