"""Run P05 local fixtures; verify actual files, counters, feedback and terminal routes."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

SOURCE = b"apples=7\npears=11\n"
VALID = SOURCE + b"total=18\n"
DUPLICATE = b"apples=7\napples=7\npears=11\ntotal=18\n"
# Expected protocol outcomes are independent of the Rust scenario implementation.
# reason, verified, episodes, calls, tool attempts, byte reservations, normal returns, reads, writes
CASES = {
    "normal": ("goal_satisfied", True, 1, 3, 2, len(VALID), 1, 1, 1),
    "false-final": ("no_progress", False, 2, 2, 0, 0, 2, 0, 0),
    "continue-success": ("goal_satisfied", True, 2, 5, 3, len(SOURCE)+len(VALID), 2, 1, 2),
    "wrong-total": ("goal_satisfied", True, 2, 5, 3, 2*len(VALID), 2, 1, 2),
    "no-progress": ("no_progress", False, 3, 7, 4, 3*len(SOURCE), 3, 1, 3),
    "episode-limit": ("episode_limit", False, 2, 5, 3, 2*len(SOURCE), 2, 1, 2),
    "model-budget": ("model_budget", False, 2, 3, 2, len(SOURCE), 1, 1, 1),
    "tool-budget": ("tool_budget", False, 2, 4, 2, len(SOURCE), 1, 1, 1),
    "byte-budget": ("byte_budget", False, 2, 4, 3, len(SOURCE), 1, 1, 1),
    "cancelled-after-read": ("cancelled", False, 1, 1, 1, 0, 0, 1, 0),
    "explicit-handoff": ("explicit_handoff", False, 1, 2, 1, 0, 0, 1, 0),
    "missing-source": ("input_blocked", False, 0, 0, 0, 0, 0, 0, 0),
    "malformed-source": ("input_blocked", False, 0, 0, 0, 0, 0, 0, 0),
    "denied-path": ("policy_denied", False, 1, 2, 2, 0, 0, 1, 0),
    "tool-write-failed": ("tool_write_failed", False, 1, 2, 2, len(VALID), 0, 1, 0),
    "model-error": ("model_error", False, 1, 2, 1, 0, 0, 1, 0),
    "valid-then-model-error": ("model_error", True, 1, 3, 2, len(VALID), 0, 1, 1),
    "invalid-report": ("no_progress", False, 2, 5, 3, 2*len(DUPLICATE), 2, 1, 2),
    "changed-source": ("goal_blocked", False, 1, 3, 2, len(VALID), 1, 1, 1),
    "already-satisfied": ("already_satisfied", True, 0, 0, 0, 0, 0, 0, 0),
    "missing-final": ("invalid_response", True, 1, 3, 2, len(VALID), 0, 1, 1),
    "exact-budget": ("goal_satisfied", True, 1, 3, 2, len(VALID), 1, 1, 1),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def invoke(binary, name, folder, error=None):
    process = subprocess.run([str(binary), name, str(folder)], capture_output=True, text=True, timeout=15)
    require(not process.stderr, process.stderr)
    require(process.returncode == (2 if error else 0), process.stdout)
    result = json.loads(process.stdout)
    if error:
        require(result == {"error": error}, "Wrong CLI error")
    return result


def check_case(binary, name, folder):
    result = invoke(binary, name, folder)
    reason, verified, episodes, calls, tools, byte_count, returns, reads, writes = CASES[name]
    require(result["reason"] == reason, name + " reason")
    require(result["goal_verified"] == verified, name + " verification")
    completed = reason in ("goal_satisfied", "already_satisfied")
    require(result["status"] == ("completed" if completed else "needs_human"), name + " status")
    require(result["used"] == dict(episodes=episodes, model_calls=calls, tools=tools, write_bytes=byte_count), name + " ledger")
    require((result["normal_returns"], result["reads"], result["writes"]) == (returns, reads, writes), name + " effects")
    for key, count in result["used"].items():
        require(count <= result["limits"][key], name + " over budget")
    require(json.loads((folder / "result.json").read_text()) == result, "Saved result differs")
    handoff = folder / "handoff.json"
    require(handoff.exists() != completed, name + " handoff presence")
    if not completed:
        body = json.loads(handoff.read_text())
        require(body["reason"] == reason and body["usage"] == result["used"] and body["verdict"] == result["verdict"], name + " handoff content")
        require(body["contract"] == result["contract"], name + " frozen contract in handoff")
    if name not in ("missing-source", "malformed-source"):
        require(result["contract"] == dict(source=SOURCE.decode(), expected=dict(apples=7, pears=11, total=18)), name + " frozen contract")
    else:
        require(result["contract"] is None, name + " cannot prepare invalid goal")
    require(not (folder / "report.tmp").exists(), name + " temporary write leaked")
    require(not (folder.parent / "escape.txt").exists(), "Forbidden path was written")
    trace = result["trace"]
    require(trace[0]["phase"] == "prepare" and trace[-1]["phase"] == "terminal", name + " fixed flow")
    require(sum(e["phase"] == "model" for e in trace) == calls, name + " model count")
    evaluations = [e for e in trace if e["phase"] == "evaluate"]
    require(len(evaluations) == episodes, name + " evaluate each episode")
    require([e["episode"] for e in evaluations] == list(range(1, episodes+1)), name + " episode ordering")
    require(sum(e["phase"] == "tool" and e["name"] == "write_report" for e in trace) == writes, name + " write receipts")
    artifact = folder / "report.txt"
    actual = artifact.read_bytes() if artifact.is_file() else None
    if verified:
        require(actual == VALID, name + " actual goal artifact")
    elif name in ("continue-success", "wrong-total", "normal", "exact-budget"):
        raise ValueError("Expected completion")
    elif name in ("no-progress", "episode-limit", "model-budget", "tool-budget", "byte-budget"):
        require(actual == SOURCE, name + " preserve partial output")
    elif name == "invalid-report":
        require(actual == DUPLICATE and result["verdict"]["score"] == 0, "Malformed report must not gain score")
    elif name == "changed-source":
        require(actual == VALID and (folder / "source.txt").read_bytes() == b"apples=8\npears=11\n", "Input conflict evidence")
    elif name != "tool-write-failed":
        require(actual is None, name + " unexpected output")
    if name in ("continue-success", "wrong-total"):
        expected_feedback = ["missing:total"] if name == "continue-success" else ["wrong:total"]
        require(evaluations[0]["verdict"]["feedback"] == expected_feedback, "Repair feedback")
        require(evaluations[1]["verdict"]["kind"] == "satisfied", "Repair result")
        require(sum(e["phase"] == "continue" for e in trace) == 1, "One continuation")
    if name == "no-progress":
        require([e["verdict"]["score"] for e in evaluations] == [2, 2, 2], "Rewrites cannot fake progress")
    if name == "changed-source":
        require(result["verdict"]["kind"] == "blocked", "Changed input needs decision")
    if name not in ("missing-source", "malformed-source", "changed-source"):
        require((folder / "source.txt").read_bytes() == SOURCE, "Input unexpectedly changed")
    return result


def run(binary, directory):
    directory.mkdir(parents=True)
    results, outputs = [], {}
    for name in CASES:
        result = check_case(binary, name, directory / name)
        trace = result["trace"]
        summary = {key: result[key] for key in ("status", "reason", "goal_verified", "normal_returns", "used", "reads", "writes")}
        summary["evaluations"] = [{key: e[key] for key in ("episode", "normal", "verdict")} for e in trace if e["phase"] == "evaluate"]
        artifact = directory / name / "report.txt"
        summary["report"] = artifact.read_text() if artifact.is_file() else None
        summary["handoff_saved"] = (directory / name / "handoff.json").is_file()
        outputs[name] = ("SCENARIO " + name + "\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode()
        results.append(result)
    # Negative CLI cases must not overwrite an existing workspace or initialize unknown fixtures.
    existing = directory / "existing"
    existing.mkdir()
    (existing / "sentinel.txt").write_text("keep me")
    invoke(binary, "normal", existing, "workspace_must_be_new")
    require(list(existing.iterdir()) == [existing / "sentinel.txt"] and (existing / "sentinel.txt").read_text() == "keep me", "Existing files were touched")
    unknown = directory / "unknown"
    invoke(binary, "not-a-scenario", unknown, "unknown_scenario")
    require(not unknown.exists(), "Unknown scenario created files")
    return dict(scenarios=results, cli_processes=len(CASES)+2, rejected_cli=["existing_workspace", "unknown_scenario"]), outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="p05-fixtures-") as directory:
        result, outputs = run(args.binary.resolve(), Path(directory) / "cases")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    for name, content in outputs.items():
        (args.output / (name+".txt")).write_bytes(content)
    print("P05: {} scenarios / {} CLI processes; file, ledger, feedback and handoff assertions passed".format(len(CASES), result["cli_processes"]))


if __name__ == "__main__":
    main()
