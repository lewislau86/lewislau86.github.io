"""Run every written chapter's original verifier and record a source-bound audit.

This is the website maintainer's exhaustive check. The downloaded run.py has a
smaller, explicitly documented test/demo scope and no website dependency.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agent_package", ROOT / "scripts/package-agent-experiments.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def save_report(results, log_directory):
    lessons = package.configuration()
    by_id = {row["id"]: row for row in lessons}
    if len(results) != len(lessons) or {row["id"] for row in results} != set(by_id):
        raise ValueError("Audit results must cover every written chapter")
    rows = []
    for result in results:
        lesson = by_id[result["id"]]
        text = (log_directory / (lesson["id"] + ".log")).read_text(encoding="utf-8")
        rows.append(dict(id=lesson["id"], slug=lesson["slug"], verifier=lesson["verifier"],
                         exit_code=result["exit_code"], elapsed_seconds=result["elapsed_seconds"],
                         summary=text.strip().splitlines()[-1] if text.strip() else "No verifier output",
                         inputs_sha256=package.inputs(lesson)))
    env = dict(os.environ, RUSTUP_TOOLCHAIN="1.99.1")
    report = dict(schema_version=1, checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  scope="Every chapter's original --check verifier; deterministic model fixtures; no live external provider",
                  environment=dict(python=sys.version.split()[0],
                    rustc=subprocess.check_output(["rustc", "--version"], env=env, text=True).strip(),
                    host=subprocess.check_output(["rustc", "-vV"], env=env, text=True).split("host: ")[1].splitlines()[0]),
                  passed=sum(r["exit_code"] == 0 for r in rows), total=len(rows), lessons=rows)
    package.REPORT.parent.mkdir(parents=True, exist_ok=True)
    package.REPORT.write_bytes(package.encoded(report))
    return report


def update_rows(results, log_directory):
    """Replace only the given lessons' rows; each updated row records its own check time."""
    report = json.loads(package.REPORT.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in package.configuration()}
    rows = {row["id"]: row for row in report["lessons"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for result in results:
        lesson = by_id[result["id"]]
        text = (log_directory / (lesson["id"] + ".log")).read_text(encoding="utf-8")
        rows[lesson["id"]] = dict(id=lesson["id"], slug=lesson["slug"], verifier=lesson["verifier"],
                                  exit_code=result["exit_code"], elapsed_seconds=result["elapsed_seconds"],
                                  summary=text.strip().splitlines()[-1] if text.strip() else "No verifier output",
                                  inputs_sha256=package.inputs(lesson), checked_at=now)
    report["lessons"] = [rows[row["id"]] for row in report["lessons"]]
    report["passed"] = sum(r["exit_code"] == 0 for r in report["lessons"])
    package.REPORT.write_bytes(package.encoded(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=ROOT / ".cache/agent-experiment-audit")
    parser.add_argument("--lesson", action="append", help="Recheck only these lessons and update their audit rows "
                        "(migration to ADK-Rust 3.0 merges chapter by chapter; see agent.md)")
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    results = []
    for lesson in package.configuration():
        if args.lesson and lesson["id"] not in args.lesson:
            continue
        started = time.monotonic()
        before = package.inputs(lesson)
        print("Checking {}: {} --check".format(lesson["id"], lesson["verifier"]), flush=True)
        with (args.logs / (lesson["id"] + ".log")).open("w", encoding="utf-8") as log:
            try:
                process = subprocess.run([sys.executable, lesson["verifier"], *lesson.get("verifier_args", []), "--check"], cwd=ROOT,
                                         stdout=log, stderr=subprocess.STDOUT, timeout=1500)
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = 124
        if package.inputs(lesson) != before:
            code = 125
        result = dict(id=lesson["id"], exit_code=code, elapsed_seconds=round(time.monotonic() - started, 1))
        results.append(result)
        print("{} {} ({}s); log: {}".format("PASS" if code == 0 else "FAIL", lesson["id"], result["elapsed_seconds"], args.logs / (lesson["id"] + ".log")), flush=True)
    if args.lesson:
        report = update_rows(results, args.logs)
        failed = [r["id"] for r in results if r["exit_code"] != 0]
        print("Updated audit rows: {}; failed: {}".format(", ".join(args.lesson), ", ".join(failed) or "none"))
        if failed:
            raise SystemExit(1)
        return
    report = save_report(results, args.logs)
    print("Full chapter audit: {}/{} passed".format(report["passed"], report["total"]))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
