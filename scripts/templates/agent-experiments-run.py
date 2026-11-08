"""Run the downloaded course labs with Python's standard library only.

Generated collection: edit this template in the website repository, then package.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def command(args, cwd, env):
    print("+ " + shlex.join([str(x) for x in args]), flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=900)


def integrity():
    expected = json.loads((ROOT / "checksums.json").read_text(encoding="utf-8"))
    for name, digest in expected.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Missing or modified packaged file: " + name)
    print("Integrity passed: {} files".format(len(expected)))


def doctor():
    print("Python: " + sys.version.split()[0])
    for name in ("rustup", "rustc", "cargo", "git"):
        executable = shutil.which(name)
        print("{}: {}".format(name, executable or "MISSING"))
    for lesson in ("P01", "P04"):
        configured = os.environ.get(lesson + "_PG_BIN")
        binary = Path(configured) / "postgres" if configured else shutil.which("postgres")
        print("{} PostgreSQL 18: {}".format(lesson, binary or "MISSING (needed only for P01/P04)"))
    print("Install: rustup toolchain install 1.99.1 --profile minimal --component rustfmt --component clippy")
    print("Platform: macOS/Linux/WSL; PostgreSQL labs need a non-root Unix user.")


def run_lesson(lesson, action, offline, keep):
    slug = lesson["slug"]
    source = ROOT / "chapters" / slug
    if keep:
        destination = keep / slug
        if source == destination or source in destination.parents:
            raise ValueError("Result directory must be outside the chapter source")
        destination.mkdir()
        context = nullcontext(str(destination))
    else:
        context = tempfile.TemporaryDirectory(prefix="agent-lab-" + lesson["id"].lower() + "-")
    with context as directory:
        work = Path(directory)
        project = work / "project"
        shutil.copytree(source, project)
        run = work / "run"
        run.mkdir()
        for name, content in lesson.get("inputs", {}).items():
            target = run / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        target = ROOT / ".cache" / "target"
        env = dict(os.environ, RUSTUP_TOOLCHAIN="1.99.1", CARGO_TARGET_DIR=str(target),
                   CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", "4"))
        flags = ["--locked"] + (["--offline"] if offline else [])
        executable_suffix = ".exe" if os.name == "nt" else ""
        if lesson["kind"] == "cargo":
            if action == "test":
                command(["cargo", "fmt", "--check"], project, env)
                command(["cargo", "test"] + flags + ["--", "--test-threads=1"], project, env)
                command(["cargo", "clippy"] + flags + ["--all-targets", "--", "-D", "warnings"], project, env)
            command(["cargo", "build"] + flags, project, env)
            binary = target / "debug" / (lesson["binary"] + executable_suffix)
        else:
            source_file = project / (slug + ".rs")
            binary = work / ("lab" + executable_suffix)
            if action == "test":
                command(["rustfmt", "--edition", "2024", "--check", source_file], project, env)
                tests = work / ("tests" + executable_suffix)
                command(["rustc", "--edition=2024", "-D", "warnings", "--test", source_file, "-o", tests], project, env)
                command([tests, "--test-threads=1"], project, env)
            command(["rustc", "--edition=2024", "-D", "warnings", source_file, "-o", binary], project, env)
        substitutions = dict(binary=str(binary), run=str(run), python=sys.executable)
        for step in lesson["demo"]:
            expanded = []
            for part in step:
                for key, value in substitutions.items():
                    part = part.replace("{" + key + "}", value)
                expanded.append(part)
            command(expanded, project, env)
        if keep:
            print("Saved results: " + str(destination))
    print("PASS {} {} ({})".format(lesson["id"], slug, action), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "doctor", "integrity", "run", "test"])
    parser.add_argument("lesson", nargs="?", help="R00..R20, G01..G03, K01, P01..P06, or topic slug")
    parser.add_argument("--all", action="store_true", help="Run every chapter, including PostgreSQL labs")
    parser.add_argument("--offline", action="store_true", help="Require Cargo dependencies already cached")
    parser.add_argument("--skip-postgres", action="store_true", help="Explicitly omit P01/P04; reported as skipped")
    parser.add_argument("--keep", type=Path, help="Save experiment results under this new/existing parent")
    args = parser.parse_args()
    lessons = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["lessons"]
    if args.action == "list":
        for row in lessons:
            chapter = "第 {} 章".format(row['chapter']) if 'chapter' in row else "专题 {}".format(int(row['id'][1:]))
            print("{}  {:30} {} · {}{}".format(row["id"], row["slug"], chapter, row["title"], " [PostgreSQL 18]" if row["requires_postgres"] else ""))
        return
    if args.action == "doctor":
        doctor()
        return
    if args.action == "integrity":
        integrity()
        return
    if args.all == bool(args.lesson):
        parser.error("Choose either one lesson or --all")
    selected = lessons if args.all else [r for r in lessons if args.lesson in (r["id"], r["slug"])]
    if not selected:
        parser.error("Unknown lesson: " + str(args.lesson))
    if args.keep:
        args.keep = args.keep.resolve()
        args.keep.mkdir(parents=True, exist_ok=True)
        for row in selected:
            if (args.keep / row["slug"]).exists():
                parser.error("Result directory already exists: " + str(args.keep / row["slug"]))
    passed, failed, skipped = [], [], []
    for lesson in selected:
        if args.skip_postgres and lesson["requires_postgres"]:
            skipped.append(lesson["id"])
            print("SKIP {}: --skip-postgres".format(lesson["id"]), flush=True)
            continue
        try:
            run_lesson(lesson, args.action, args.offline, args.keep)
            passed.append(lesson["id"])
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            failed.append(lesson["id"])
            print("FAIL {}: {}".format(lesson["id"], error), file=sys.stderr, flush=True)
    report = dict(action=args.action, offline=args.offline, passed=passed, failed=failed, skipped=skipped)
    output = ROOT / ".cache" / "last-run.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if failed or not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
