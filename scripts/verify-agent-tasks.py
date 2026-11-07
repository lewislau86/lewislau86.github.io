"""Verify R12 with independent CLI processes, real files and killed children."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/task-system"
PUBLIC = ROOT / "docs/public/learn-agent-rust"
DATA = ROOT / "scripts/data/learn-agent-rust/r12-results.json"
ARCHIVE = PUBLIC / "task-system-lab.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/task-system.md"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/tasks.rs", "src/storage.rs", "src/tests.rs"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env):
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args, p.stdout, p.stderr))
    return p.stdout


class Lab:
    def __init__(self, binary, folder):
        self.binary, self.folder = str(binary), Path(folder)
        self.root = self.folder / "board"
        self.steps, self.lines, self.pids = [], [], set()

    def record(self, label, response):
        self.steps.append(dict(label=label, response=response))
        if response["status"] == "error":
            summary = "error={} committed={}".format(response["error"], str(response["committed"]).lower())
        else:
            summary = "revision={} ready={} reconcile={} tasks={}".format(
                response["revision"], ",".join(response["ready"]) or "-",
                ",".join(response["reconcile"]) or "-",
                ",".join("{}:{}#{}".format(t["id"], t["status"], t["attempts"])
                         for t in response["board"]["tasks"]) or "-")
        self.lines.extend([label, summary])

    def invoke(self, label, args, error=None, committed=False):
        p = subprocess.Popen([self.binary, str(self.root)] + [str(a) for a in args],
                             cwd=self.folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pids.add(p.pid)
        stdout, stderr = p.communicate(timeout=10)
        response = json.loads(stdout)
        require(not stderr and p.returncode == (1 if error else 0), "Wrong process exit: " + label)
        require(response["status"] == ("error" if error else "ok"), "Wrong status: " + label)
        if error:
            require(response["error"] == error and response["committed"] == committed, label + ": " + stdout)
        else:
            require(response["board"] == self.disk(), "Acknowledgement differs from actual file")
        self.record(label, response)
        return response

    def init(self):
        return self.invoke("init (new process)", ["init"])

    def show(self, error=None):
        return self.invoke("show (new process)", ["show"], error)

    def disk_bytes(self):
        p = self.root / "tasks.json"
        return p.read_bytes() if p.is_file() else None

    def disk(self):
        return json.loads(self.disk_bytes())

    def apply(self, op, error=None, expected=None, flag=None, committed=False):
        if expected is None:
            expected = self.disk()["revision"]
        before = self.disk_bytes()
        args = ["apply", expected, json.dumps(op, ensure_ascii=False)] + ([flag] if flag else [])
        result = self.invoke("apply {} {} expected={} (new process)".format(op["op"], op.get("id", "-"), expected),
                             args, error, committed)
        if error and not committed:
            require(self.disk_bytes() == before, "Rejected update changed snapshot bytes")
        require(not (self.root / ".tasks.pending").exists() or error == "pending_unavailable",
                "Owned pending file leaked")
        return result

    def add(self, name="readme", deps=None, error=None):
        return self.apply(dict(op="add", id=name, title="task " + name,
                               depends_on=deps or [], max_attempts=2), error)

    def start(self, name="readme", **kw):
        return self.apply(dict(op="start", id=name), **kw)

    def complete(self, name="readme", attempt=1, **kw):
        return self.apply(dict(op="complete", id=name, attempt=attempt, result="checked cargo run"), **kw)

    def fail(self, name="readme"):
        task = next(t for t in self.disk()["tasks"] if t["id"] == name)
        return self.apply(dict(op="fail", id=name, attempt=task["attempts"], error="verified retryable read failure"))

    def kill_at(self, flag, contention=False):
        before = self.disk_bytes()
        p = subprocess.Popen([self.binary, str(self.root), "apply", str(self.disk()["revision"]),
                              json.dumps(dict(op="start", id="readme")), flag],
                             cwd=self.folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.pids.add(p.pid)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(p.stdout, selectors.EVENT_READ)
                require(bool(selector.select(timeout=10)), "Barrier timeout")
            event = json.loads(p.stdout.readline())
            expected = "before_rename" if flag == "--pause-before-rename" else "after_commit"
            require(event == {"event": expected} and p.poll() is None, "Wrong barrier")
            self.steps.append(dict(label="kill barrier", response=event))
            self.lines.append("barrier={} (child still holds file lock)".format(expected))
            if contention:
                self.show("store_busy")
            p.kill()
            p.wait(timeout=10)
            require(p.returncode != 0 and not p.stderr.read(), "Child kill failed")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()
        self.lines.append("child killed and reaped; next process reopens store")
        if flag == "--pause-before-rename":
            require(self.disk_bytes() == before, "Precommit kill changed snapshot")
            require((self.root / ".tasks.pending").is_file(), "Candidate not preserved")
        else:
            require(self.disk()["revision"] == json.loads(before)["revision"] + 1, "Commit lost")
            require(not (self.root / ".tasks.pending").exists(), "Renamed candidate remained")


def scenarios(binary, directory):
    names = ["new-process-chain", "dependency-blocked", "dependency-cycle", "self-cycle",
             "missing-dependency", "duplicate-id", "illegal-transition", "stale-revision",
             "stale-attempt", "retry-budget", "single-executor", "running-restart",
             "save-before-rename", "save-after-rename", "crash-before-rename", "crash-after-commit",
             "corrupt-json", "unknown-schema", "invalid-state", "corrupt-cycle",
             "unknown-field", "size-limit", "pending-file", "invalid-store-file",
             "invalid-request", "missing-store"]
    rows, outputs = [], {}
    for name in names:
        folder = Path(directory) / name
        folder.mkdir()
        lab = Lab(binary, folder)
        point = ""
        if name == "missing-store":
            lab.show("store_missing")
            point = "store_missing"
        else:
            lab.init()
            lab.add()
            if name == "new-process-chain":
                lab.add("check", ["readme"])
                lab.add("guide", ["check"])
                require(lab.show()["ready"] == ["readme"], "Initial ready differs")
                for task in ["readme", "check", "guide"]:
                    lab.start(task)
                    active = lab.show()
                    require(active["reconcile"] == [task] and not active["ready"], "Running state lost")
                    lab.complete(task)
                final = lab.show()
                require(final["revision"] == 9 and all(t["status"] == "completed" for t in final["board"]["tasks"]), "Chain failed")
                point = "completed=3"
            elif name == "dependency-blocked":
                lab.add("guide", ["readme"])
                lab.start("guide", error="dependency_incomplete")
                point = "dependency_incomplete"
            elif name == "dependency-cycle":
                lab.add("check", ["readme"])
                lab.add("guide", ["check"])
                lab.apply(dict(op="set_dependencies", id="readme", depends_on=["guide"]), "dependency_cycle")
                point = "dependency_cycle"
            elif name == "self-cycle":
                lab.apply(dict(op="set_dependencies", id="readme", depends_on=["readme"]), "dependency_cycle")
                point = "dependency_cycle"
            elif name == "missing-dependency":
                lab.add("guide", ["missing"], error="dependency_missing")
                point = "dependency_missing"
            elif name == "duplicate-id":
                lab.add(error="duplicate_id")
                point = "duplicate_id"
            elif name == "illegal-transition":
                lab.complete(error="illegal_transition")
                point = "illegal_transition"
            elif name == "stale-revision":
                lab.start(expected=0, error="revision_conflict")
                point = "revision_conflict"
            elif name in ("stale-attempt", "retry-budget"):
                lab.start()
                lab.fail()
                lab.apply(dict(op="retry", id="readme"))
                lab.start()
                if name == "stale-attempt":
                    lab.complete(attempt=1, error="attempt_conflict")
                    point = "attempt_conflict"
                else:
                    lab.fail()
                    lab.apply(dict(op="retry", id="readme"), "attempt_limit")
                    require(lab.disk()["tasks"][0]["attempts"] == 2, "Attempts reset")
                    point = "attempt_limit"
            elif name == "single-executor":
                lab.add("other")
                lab.start()
                lab.start("other", error="executor_busy")
                lab.complete()
                lab.start("other")
                point = "single_running"
            elif name == "running-restart":
                lab.start()
                require(lab.show()["reconcile"] == ["readme"], "Running task disappeared")
                lab.start(error="illegal_transition")
                lab.fail()
                lab.apply(dict(op="retry", id="readme"))
                lab.start()
                require(lab.disk()["tasks"][0]["attempts"] == 2, "Explicit recovery reset attempts")
                point = "explicit_recovery_attempt=2"
            elif name == "save-before-rename":
                lab.start(flag="--fail-before-rename", error="injected_before_rename")
                require(lab.show()["revision"] == 1, "Old revision lost")
                lab.start()
                point = "old_snapshot_preserved"
            elif name == "save-after-rename":
                lab.start(flag="--fail-after-rename", error="durability_unknown", committed=True)
                current = lab.show()
                require(current["revision"] == 2 and current["reconcile"] == ["readme"], "Commit lost")
                lab.start(expected=1, error="revision_conflict")
                point = "new_snapshot_visible"
            elif name == "crash-before-rename":
                lab.kill_at("--pause-before-rename", contention=True)
                require(lab.show()["revision"] == 1, "Precommit snapshot changed")
                pending = lab.root / ".tasks.pending"
                require(json.loads(pending.read_bytes())["revision"] == 2, "Wrong candidate")
                lab.start(error="pending_unavailable")
                # Cleanup is confined to our own killed fixture after checking both files.
                pending.unlink()
                lab.lines.append("fixture cleanup: checked candidate revision=2; removed uncommitted pending")
                lab.start()
                point = "kill_before_commit"
            elif name == "crash-after-commit":
                lab.kill_at("--pause-after-commit")
                current = lab.show()
                require(current["revision"] == 2 and current["reconcile"] == ["readme"], "Running commit lost")
                lab.start(error="illegal_transition")
                point = "kill_after_commit"
            elif name in ("corrupt-json", "unknown-schema", "invalid-state", "corrupt-cycle",
                          "unknown-field", "size-limit", "invalid-store-file"):
                value = lab.disk()
                expected = "corrupt_store"
                if name == "corrupt-json":
                    payload = b'{"schema":1,"revision":'
                elif name == "size-limit":
                    payload, expected = b" " * 65537, "size_limit"
                elif name == "invalid-store-file":
                    (lab.root / "tasks.json").unlink()
                    (lab.root / "tasks.json").mkdir()
                    payload, expected = None, "invalid_store_file"
                else:
                    if name == "unknown-schema":
                        value["schema"], expected = 2, "schema_version"
                    elif name == "invalid-state":
                        value["tasks"][0]["status"], expected = "completed", "invalid_state"
                    elif name == "corrupt-cycle":
                        value["tasks"][0]["depends_on"], expected = ["readme"], "dependency_cycle"
                    else:
                        value["unexpected"] = True
                    payload = (json.dumps(value) + "\n").encode()
                if payload is not None:
                    (lab.root / "tasks.json").write_bytes(payload)
                lab.show(expected)
                require(lab.disk_bytes() == payload, "Bad store was replaced")
                if payload is None:
                    require((lab.root / "tasks.json").is_dir(), "Invalid store path changed")
                point = expected
            elif name == "pending-file":
                pending = lab.root / ".tasks.pending"
                marker = b"owned fixture; preserve\n"
                pending.write_bytes(marker)
                lab.start(error="pending_unavailable")
                require(pending.read_bytes() == marker, "Existing pending file removed")
                point = "pending_preserved"
            elif name == "invalid-request":
                lab.apply(dict(op="start", id="readme", owner="ignored?"), "invalid_request")
                point = "invalid_request"
        require(len(lab.pids) == len(lab.steps), "CLI process identity reused")
        raw, snapshot = lab.disk_bytes(), None
        if raw:
            try:
                snapshot = json.loads(raw)
            except json.JSONDecodeError:
                pass
        output = ("\n".join(lab.lines) + "\n").encode()
        row = dict(name=name, processes=len(lab.pids), outcome=point, snapshot=snapshot,
                   snapshot_sha256=hashlib.sha256(raw).hexdigest() if raw else None,
                   steps=lab.steps, output_sha256=hashlib.sha256(output).hexdigest())
        rows.append(row)
        outputs[name] = output
    return rows, outputs


def package_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("task-system-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def chapter_artifact(rows):
    chapter = CHAPTER.read_text()
    start, end = "<!-- r12-results:start -->", "<!-- r12-results:end -->"
    require(chapter.count(start) == 1 and chapter.count(end) == 1, "Missing R12 result markers")
    table = ["| 场景 | 独立进程 | 验证结果 |", "| --- | --- | --- |"]
    table.extend("| `{}` | {} | `{}` |".format(r["name"], r["processes"], r["outcome"]) for r in rows)
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    return (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    with tempfile.TemporaryDirectory(prefix="agent-r12-") as directory:
        folder = Path(directory) / "source"
        for name, content in files.items():
            p = folder / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(Path(directory) / "target"), RUSTFLAGS="-D warnings")
        command(["cargo", "fmt", "--", "--check"], folder, env)
        tests_output = command(["cargo", "test", "--locked", "--", "--test-threads=1"], folder, env)
        tests = re.findall(r"^test tests::(\w+) \.\.\. ok$", tests_output, re.M)
        require(len(tests) == 14 and "14 passed; 0 failed" in tests_output, "Rust tests failed")
        command(["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"], folder, env)
        command(["cargo", "build", "--locked"], folder, env)
        runs = Path(directory) / "runs"
        runs.mkdir()
        rows, outputs = scenarios(Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r12", runs)
        environment = dict(rustc=command(["rustc", "--version"], folder, env).strip(),
                           host=command(["rustc", "-vV"], folder, env).split("host: ")[1].splitlines()[0])
        if args.check and DATA.exists():
            environment = json.loads(DATA.read_text())["environment"]
        evidence = dict(scope="R12 single-executor task metadata; real local files, independent CLI processes and killed child barriers; no model or external task execution",
                        files_sha256={name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
                        environment=environment, regression_tests=tests, scenarios=rows)
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
        package = dict(files)
        package.update({"outputs/" + name + ".txt": content for name, content in outputs.items()})
        package["evidence.json"] = serialized
        archive = package_bytes(package)
        published = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else archive
        extracted = Path(directory) / "download"
        with zipfile.ZipFile(io.BytesIO(published)) as z:
            z.extractall(extracted)
        download_env = dict(env, CARGO_TARGET_DIR=str(Path(directory) / "download-target"))
        command(["cargo", "build", "--locked", "--offline"], extracted / "task-system-lab", download_env)
        repeated = Path(directory) / "repeat"
        repeated.mkdir()
        again_rows, again_outputs = scenarios(Path(download_env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r12", repeated)
        require(rows == again_rows and outputs == again_outputs, "Published archive behavior differs")
    artifacts = {DATA: serialized, ARCHIVE: archive, CHAPTER: chapter_artifact(rows)}
    artifacts.update({PUBLIC / "outputs" / ("r12-" + name + ".txt"): content for name, content in outputs.items()})
    chapter = artifacts[CHAPTER].decode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/task-system/(src/[\w.]+)#([\w-]+)", chapter):
        source = files[filename].decode()
        require(source.count("// region " + region + "\n") == 1 and source.count("// endregion " + region + "\n") == 1, "Invalid region " + region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r12-([\w-]+).txt", chapter):
        require(name in outputs, "Unverified output " + name)
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R12 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R12: {} scenarios / {} independent CLI processes, 14 Rust tests, Clippy and published archive rerun passed; {}".format(
        len(rows), sum(r["processes"] for r in rows), "artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
