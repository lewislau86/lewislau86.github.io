"""Verify P04 Rust, private PostgreSQL drills and an independently extracted archive."""
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
SOURCE = ROOT / "docs/public/learn-agent-rust/code/production-readiness"
CHAPTER = ROOT / "docs/learn-agent-rust/production-readiness.md"
DATA = ROOT / "scripts/data/learn-agent-rust/p04-results.json"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/production-readiness-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", ".gitignore", "README.md", "lab.py", "src/main.rs", "src/schema.sql"]


def require(value, message):
    if not value:
        raise ValueError(message)


def command(args, cwd, env=None):
    p = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args[0], p.stdout, p.stderr))
    return p.stdout


def package(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("production-readiness-lab/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, content)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {n: (SOURCE / n).read_bytes() for n in FILES}
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="agent-p04-") as directory:
        root = Path(directory)
        folder = root / "source"
        for n, content in files.items():
            path = folder / n
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(root / "target"), RUSTFLAGS="-D warnings")
        command(["cargo", "fmt", "--", "--check"], folder, env)
        tests = command(["cargo", "test", "--locked"], folder, env)
        require("4 passed; 0 failed" in tests, "Unexpected test count")
        command(["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"], folder, env)
        command(["cargo", "build", "--locked"], folder, env)
        print(command(["python3", "lab.py", "--binary", root / "target/debug/learn-agent-p04", "--output", root / "results"], folder, env).strip(), flush=True)
        result = json.loads((root / "results/results.json").read_text())
        require(len(result["scenarios"]) == 24 and all(r["passed"] for r in result["scenarios"]), "Incomplete drills")
        require(result["cli_processes"] == 62, "Process coverage changed")
        measurements = json.loads((root / "results/measurements.json").read_text())
        require(0 < measurements["p50_ms"] <= measurements["p95_ms"] and measurements["restore_check_ms"] > 0, "Invalid measurements")
        observation = dict(measurements, rustc=command(["rustc", "--version"], folder).strip(),
                           host=command(["rustc", "-vV"], folder).split("host: ")[1].splitlines()[0],
                           postgres_patch=result["libraries"]["server_version_num"])
        # Durations and host are observations, not cross-machine golden assertions.
        # Functional scenarios, process count, durability settings and hashes still compare exactly.
        if args.check:
            recorded = json.loads(DATA.read_text())
            observation = recorded["observation"]
            result["libraries"]["server_version_num"] = recorded["libraries"]["server_version_num"]
        evidence = dict(result, observation=observation, rust_tests=4,
                        files_sha256={n: hashlib.sha256(c).hexdigest() for n, c in files.items()},
                        scope="PostgreSQL18 local application harness; fixed authentication fixtures; admission reservations, transactional schema migration, process death and stale worker fencing, logical backup to separate cluster; no provider or remote side effects")
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
        artifacts[DATA] = serialized
        outputs = {r["scenario"] + ".txt": (root / "results" / (r["scenario"] + ".txt")).read_bytes() for r in result["scenarios"]}
        artifacts.update({ROOT / "docs/public/learn-agent-rust/outputs" / ("p04-" + n): c for n, c in outputs.items()})
        artifacts[ROOT / "docs/public/learn-agent-rust/outputs/p04-observation.json"] = (json.dumps(observation, ensure_ascii=False, indent=2) + "\n").encode()
        archive = package(dict(files, **{"evidence.json": serialized}, **{"outputs/" + n: c for n, c in outputs.items()}))
        artifacts[ARCHIVE] = archive
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            z.extractall(root / "download")
        extracted = root / "download/production-readiness-lab"
        download_env = dict(env, CARGO_TARGET_DIR=str(root / "download-target"))
        command(["cargo", "build", "--locked", "--offline"], extracted, download_env)
        print(command(["python3", "lab.py", "--binary", root / "download-target/debug/learn-agent-p04", "--output", root / "again"], extracted, download_env).strip(), flush=True)
        second = json.loads((root / "again/results.json").read_text())
        second["libraries"]["server_version_num"] = result["libraries"]["server_version_num"]
        require(second == result, "Extracted download logical results differ")
        for n, content in outputs.items():
            require((root / "again" / n).read_bytes() == content, "Extracted output differs: " + n)
    chapter = CHAPTER.read_text()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/production-readiness/([\w./-]+)#([\w-]+)", chapter):
        source = files[filename].decode()
        require(source.count("// region " + region + "\n") == 1 and source.count("// endregion " + region + "\n") == 1, "Missing region " + region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/p04-([\w-]+).txt", chapter):
        require(name + ".txt" in outputs, "Unknown chapter output: " + name)
    start, end = "<!-- p04-results:start -->", "<!-- p04-results:end -->"
    require(chapter.count(start) == chapter.count(end) == 1, "Missing results markers")
    table = "| 场景 | 实际断言结果 |\n| --- | --- |\n"
    for row in result["scenarios"]:
        details = "; ".join("{}={}".format(k, str(v).lower() if isinstance(v, bool) else v) for k, v in row.items() if k not in ("scenario", "passed"))
        table += "| `{}` | {} |\n".format(row["scenario"], details)
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    artifacts[CHAPTER] = (before + start + "\n\n" + table.rstrip() + "\n\n" + end + after).encode()
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale P04 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("P04: 4 Rust tests, Clippy, 24 scenarios / 62 CLI processes per pass, extracted download replay; " + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
