"""Run the R00 standard-library experiment and save/check reproducible evidence.

python3 scripts/verify-learn-agent-rust.py [--check]
This currently verifies R00 only, not the planned framework integrations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/architecture-and-setup.rs"
DATA = ROOT / "scripts/data/learn-agent-rust/r00-results.json"
OUTPUT = ROOT / "docs/public/learn-agent-rust/outputs"
SCENARIOS = [("normal", [], (1, 1, "completed")),
             ("deny", ["--deny"], (0, 0, "denied")),
             ("missing-file", ["--missing-file"], (1, 0, "missing_file"))]


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    results = []
    expected_files = {}
    with tempfile.TemporaryDirectory(prefix="learn-agent-r00-verify-") as temp:
        executable = str(Path(temp) / "agent-r00")
        command(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", executable])
        for name, flags, expected in SCENARIOS:
            # Run outside the website checkout to check source independence.
            process = subprocess.run([executable] + flags, cwd=temp, capture_output=True, text=True, check=True)
            output = process.stdout
            match = re.search(r"model_turns=(\d+) tool_requests=(\d+) read_attempts=(\d+) read_successes=(\d+) messages=(\d+) outcome=(\w+)", output)
            if not match:
                raise ValueError("Missing statistics: " + name)
            turns, requests, attempts, successes, messages = map(int, match.groups()[:5])
            outcome = match[6]
            if (turns, requests, messages) != (2, 1, 4) or (attempts, successes, outcome) != expected:
                raise ValueError("Unexpected scenario result: " + name)
            if outcome == "completed" and "README 里的启动命令是：cargo run" not in output:
                raise ValueError("Missing answer from fixture")
            if outcome != "completed" and "任务未完成：" not in output:
                raise ValueError("Failure was presented as completion")
            roles = re.findall(r"^消息 \d+ \| (\w+)", output, re.M)
            if roles != ["user", "assistant", "tool", "assistant"]:
                raise ValueError("Unexpected message ordering")
            if output.count("call_id=read-1") != 2:
                raise ValueError("Missing call/result correlation")
            expected_files[OUTPUT / ("r00-" + name + ".txt")] = output
            results.append(dict(name=name, model_turns=turns, tool_requests=requests,
                                read_attempts=attempts, read_successes=successes,
                                messages=messages, roles=roles, outcome=outcome,
                                stdout_sha256=hashlib.sha256(output.encode()).hexdigest(), exit_code=process.returncode))
    evidence = dict(scope="R00 standard-library wiring; scripted model; no HTTP or database",
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    rustc=command(["rustc", "--version"]).strip(), scenarios=results)
    # Toolchain identity is historical evidence, not a cross-machine check gate.
    if args.check and DATA.exists():
        evidence["rustc"] = json.loads(DATA.read_text())["rustc"]
    expected_files[DATA] = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    for path, content in expected_files.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit("Stale R00 evidence: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print("R00: normal, denied-before-read and missing-file scenarios passed; " + ("evidence checked" if args.check else "evidence saved"))


if __name__ == "__main__":
    main()
