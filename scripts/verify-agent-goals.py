"""P05: bounded continuation, independent file goals and explicit handoff evidence."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/workflow-and-goal-control"
CHAPTER = ROOT / "docs/learn-agent-rust/workflow-and-goal-control.md"
DATA = ROOT / "scripts/data/learn-agent-rust/p05-results.json"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/workflow-and-goal-control-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", ".gitignore", "README.md", "lab.py"] + ["src/"+name+".rs" for name in ("main", "controller", "fixture", "goal", "tests")]


def require(value, message):
    if not value:
        raise ValueError(message)


def command(args, cwd, env=None):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args, p.stdout, p.stderr))
    return p.stdout


def package(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("workflow-and-goal-control-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def chapter_bytes(files, outputs, evidence):
    chapter = CHAPTER.read_text()
    for name, region in re.findall(r"<<< @/public/learn-agent-rust/code/workflow-and-goal-control/([\w./-]+)#([\w-]+)", chapter):
        source = files[name].decode()
        require(source.count("// region " + region + "\n") == source.count("// endregion " + region + "\n") == 1, "Unknown region: " + region)
    require("```rust" not in chapter, "Import code from source instead of copying Rust")
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/p05-([\w-]+).txt", chapter):
        require(name+".txt" in outputs, "Missing output: " + name)
    start, end = "<!-- p05-results:start -->", "<!-- p05-results:end -->"
    require(chapter.count(start) == chapter.count(end) == 1, "Missing result markers")
    rows = ["| 场景 | 正常返回次数 | 产物达标 | 最终原因 | episode / 调用 |", "| --- | --- | --- | --- | --- |"]
    for result in evidence["scenarios"]:
        rows.append("| `{}` | {} | {} | `{}` | {} / {} |".format(result["scenario"], result["normal_returns"], "是" if result["goal_verified"] else "否", result["reason"], result["used"]["episodes"], result["used"]["model_calls"]))
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    return (before + start + "\n\n" + "\n".join(rows) + "\n\n" + end + after).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="agent-p05-") as directory:
        root = Path(directory)
        folder = root / "source"
        for name, content in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(root / "target"))
        command(["cargo", "fmt", "--", "--check"], folder, env)
        tests = command(["cargo", "test", "--locked"], folder, env)
        require("11 passed; 0 failed" in tests, "Unexpected Rust test coverage")
        command(["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"], folder, env)
        command(["cargo", "build", "--locked"], folder, env)
        print(command(["python3", "lab.py", "--binary", root / "target/debug/learn-agent-p05", "--output", root / "results"], folder, env).strip(), flush=True)
        result = json.loads((root / "results/results.json").read_text())
        require(len(result["scenarios"]) == 22 and result["cli_processes"] == 24, "Scenario coverage changed")
        observation = dict(rustc=command(["rustc", "--version"], folder).strip(),
                           host=command(["rustc", "-vV"], folder).split("host: ")[1].splitlines()[0])
        if args.check:
            observation = json.loads(DATA.read_text())["observation"]
        evidence = dict(result, observation=observation, rust_tests=11,
                        files_sha256={name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
                        scope="Single-process fixed workflow and scripted proposal loop; bounded cumulative ledger, independent actual-file verifier, local handoff; no provider, framework integration, durable restart or remote actions")
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2)+"\n").encode()
        artifacts[DATA] = serialized
        outputs = {r["scenario"]+".txt": (root / "results" / (r["scenario"]+".txt")).read_bytes() for r in result["scenarios"]}
        artifacts.update({ROOT / "docs/public/learn-agent-rust/outputs" / ("p05-"+name): content for name, content in outputs.items()})
        packed = package(dict(files, **{"evidence.json": serialized}, **{"outputs/"+name: content for name, content in outputs.items()}))
        artifacts[ARCHIVE] = packed
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            archive.extractall(root / "download")
        extracted = root / "download/workflow-and-goal-control-lab"
        download_env = dict(env, CARGO_TARGET_DIR=str(root / "download-target"))
        command(["cargo", "build", "--locked", "--offline"], extracted, download_env)
        print(command(["python3", "lab.py", "--binary", root / "download-target/debug/learn-agent-p05", "--output", root / "again"], extracted, download_env).strip(), flush=True)
        require(json.loads((root / "again/results.json").read_text()) == result, "Extracted logical results differ")
        for name, content in outputs.items():
            require((root / "again" / name).read_bytes() == content, "Extracted output differs: " + name)
        artifacts[CHAPTER] = chapter_bytes(files, outputs, evidence)
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale P05 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("P05: 11 Rust tests, Clippy, 22 scenarios / 24 CLI processes per pass, extracted archive replay; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
