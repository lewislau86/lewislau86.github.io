"""Extract the final unified archive and exercise its reader-facing commands."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-postgres", action="store_true")
    parser.add_argument("--lesson", help="Check only one chapter (default: all)")
    args = parser.parse_args()
    archive = ROOT / "docs/public/learn-agent-rust/learn-agent-rust-experiments.zip"
    with tempfile.TemporaryDirectory(prefix="agent-book-download-") as directory:
        with zipfile.ZipFile(archive) as z:
            z.extractall(directory)
        package = Path(directory) / "learn-agent-rust-experiments"
        # Reuse compiled dependencies between download checks, outside public/.
        cache = ROOT / ".cache/agent-download-target"
        cache.mkdir(parents=True, exist_ok=True)
        (package / ".cache").mkdir()
        (package / ".cache/target").symlink_to(cache, target_is_directory=True)
        command = [sys.executable, "run.py"]
        for operation in (["integrity"], ["list"], ["doctor"]):
            subprocess.run(command + operation, cwd=package, check=True)
        subprocess.run(["bash", "environment/check-environment.sh"], cwd=package, check=True,
                       env=dict(os.environ, RUSTUP_TOOLCHAIN="1.99.1"))
        flags = ["test", args.lesson] if args.lesson else ["test", "--all"]
        if args.offline:
            flags.append("--offline")
        if args.skip_postgres:
            flags.append("--skip-postgres")
        process = subprocess.run(command + flags, cwd=package)
        report_path = package / ".cache/last-run.json"
        if not report_path.exists():
            raise SystemExit("Reader command exited before writing its report (exit {})".format(process.returncode))
        report = json.loads(report_path.read_text())
        destination = ROOT / ".cache/agent-download-results.json"
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        if process.returncode or report["failed"] or (not args.skip_postgres and report["skipped"]):
            raise SystemExit("Unified download failed: " + str(destination))
        if not args.lesson:
            # Keep the worktree at its original absolute path, so Git's links
            # still resolve after run.py returns.
            kept = Path(directory) / "kept"
            keep_args = ["run", "R20", "--keep", str(kept)] + (["--offline"] if args.offline else [])
            subprocess.run(command + keep_args, cwd=package, check=True)
            case = kept / "integrated-agent/run/case"
            subprocess.run(["git", "-C", str(case / "repository"), "worktree", "list", "--porcelain"], check=True)
            if not (case / "run.json").is_file():
                raise SystemExit("--keep did not preserve R20 evidence")
        print("Extracted unified download: {} passed / {} skipped; {}".format(len(report["passed"]), len(report["skipped"]), destination))


if __name__ == "__main__":
    main()
