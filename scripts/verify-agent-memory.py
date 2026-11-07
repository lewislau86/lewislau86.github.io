"""R09: verify durable facts using separate CLI processes and an extracted download."""
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
SOURCE = ROOT / "docs/public/learn-agent-rust/code/memory"
OUT = ROOT / "docs/public/learn-agent-rust/outputs"
DATA = ROOT / "scripts/data/learn-agent-rust/r09-results.json"
CHAPTER = ROOT / "docs/learn-agent-rust/memory.md"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/memory-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", ".gitignore", "README.md", "src/main.rs"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env=None):
    p = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args, p.stdout, p.stderr))
    return p.stdout


class Lab:
    def __init__(self, binary, folder):
        self.binary, self.folder = binary, Path(folder)
        self.root = self.folder / "store"
        self.lines, self.steps = [], []

    def invoke(self, label, args, status, error=None):
        p = subprocess.run([str(self.binary)] + [str(a) for a in args], cwd=self.folder,
                           capture_output=True, text=True, timeout=10)
        result = json.loads(p.stdout)
        require(result["status"] == status, label + ": " + p.stdout)
        require(p.returncode == (1 if status == "error" else 0), "Wrong exit status")
        require(not p.stderr, "Unexpected stderr")
        if error:
            require(result.get("error") == error, label + ": unexpected error")
        self.lines.extend([label, p.stdout.strip()])
        self.steps.append({"label": label, "status": status, "error": result.get("error"),
                           "revision": result.get("revision"), "fact": result.get("fact")})
        return result

    def apply(self, quote="请记住：reply_language=中文", expected=0, status="saved", error=None,
              session="session-A", scope="project-a", role="user", fail=False):
        message = self.folder / "message.txt"
        message.write_text(quote + "\n", encoding="utf-8")
        args = ["apply", self.root, scope, session, "1", str(expected), role, "--message", message]
        if fail:
            args += ["--fail-before-rename"]
        return self.invoke("apply " + session + " expected=" + str(expected), args, status, error)

    def recall(self, scope="project-a", status="found", error=None):
        return self.invoke("recall new-process " + scope,
                           ["recall", self.root, scope, "reply_language"], status, error)

    def snapshot(self):
        path = self.root / "memory.json"
        return path.read_bytes() if path.exists() else None

    def seed(self):
        self.apply()
        return json.loads(self.snapshot())

    def corrupt(self, value):
        self.root.mkdir(exist_ok=True)
        (self.root / "memory.json").write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())

    def reject_unchanged(self, **kwargs):
        before = self.snapshot()
        self.apply(**kwargs)
        require(self.snapshot() == before, "Rejected write changed durable bytes")
        require(not (self.root / ".memory.lock").exists(), "Owned lock leaked")
        require(not (self.root / ".memory.pending").exists(), "Owned temporary file leaked")


def scenarios(binary, directory):
    rows, outputs = [], {}
    names = ["empty", "new-process", "update", "stale", "repeat", "scope", "forget",
             "no-intent", "tool-origin", "unknown-key", "corrupt", "truncated", "schema",
             "revision-gap", "forged-record", "unknown-field", "lock", "pending", "save-failure",
             "size-limit", "event-limit", "invalid-cli"]
    for name in names:
        folder = Path(directory) / name
        folder.mkdir()
        lab = Lab(binary, folder)
        if name == "empty":
            require(lab.recall(status="missing")["revision"] == 0, "Nonempty new store")
            require(not lab.root.exists(), "Read created store")
        elif name == "new-process":
            lab.seed()
            found = lab.recall()
            require(found["fact"]["action"] == {"kind":"set", "value":"中文"}, "Wrong fact")
            require(found["fact"]["source"]["session"] == "session-A", "Missing provenance")
        elif name == "update":
            lab.seed()
            lab.apply("请记住：reply_language=English", 1, session="session-C")
            found = lab.recall()
            require(found["fact"]["revision"] == 2 and found["fact"]["source"]["session"] == "session-C", "Wrong update")
            require(found["fact"]["action"]["value"] == "English", "Stale value recalled")
            require(len(json.loads(lab.snapshot())["events"]) == 2, "Lost audit history")
        elif name == "stale":
            lab.seed()
            lab.reject_unchanged(quote="请记住：reply_language=English", status="error", error="revision_conflict", session="session-C")
            require(lab.recall()["fact"]["action"]["value"] == "中文", "Conflict lost original")
        elif name == "repeat":
            lab.seed()
            before = lab.snapshot()
            lab.apply(expected=1, status="unchanged", session="session-B")
            require(lab.snapshot() == before, "Duplicate altered bytes or source")
        elif name == "scope":
            lab.seed()
            lab.recall(scope="project-b", status="missing")
            lab.apply("请记住：reply_language=English", 1, scope="project-b", session="session-B")
            require(lab.recall()["fact"]["action"]["value"] == "中文", "Scope overwrite")
            require(lab.recall(scope="project-b")["fact"]["action"]["value"] == "English", "Missing second scope")
        elif name == "forget":
            lab.seed()
            lab.recall()
            lab.apply("请记住：reply_language=English", 1, session="session-C")
            lab.recall()
            lab.apply("请忘记：reply_language", 2, session="session-D")
            require(lab.recall(status="missing")["revision"] == 3, "Delete revision lost")
            require(len(json.loads(lab.snapshot())["events"]) == 3, "Tombstone erased audit trail")
            lab.reject_unchanged(quote="请忘记：reply_language", expected=3, status="error", error="fact_missing")
        elif name in ("no-intent", "tool-origin", "unknown-key"):
            kwargs = {"no-intent":dict(quote="今天先使用中文" , error="no_memory_intent"),
                      "tool-origin":dict(role="tool", error="untrusted_origin"),
                      "unknown-key":dict(quote="请记住：api_key=secret", error="unknown_key")}[name]
            lab.reject_unchanged(status="error", **kwargs)
        elif name in ("corrupt", "truncated", "schema", "revision-gap", "forged-record", "unknown-field"):
            record = lab.seed()
            error = "corrupt_store"
            if name == "corrupt":
                record = b"not-json"
            elif name == "truncated":
                record = lab.snapshot()[:30]
            elif name == "schema":
                record["schema"] = 2
                error = "unsupported_schema"
            elif name == "revision-gap":
                record["events"][0]["revision"] = 2
                error = "invalid_revision"
            elif name == "forged-record":
                record["events"][0]["action"]["value"] = "English"
                error = "invalid_record"
            else:
                record["extra"] = True
            lab.corrupt(record)
            before = lab.snapshot()
            lab.recall(status="error", error=error)
            lab.reject_unchanged(expected=1, status="error", error=error)
            require(lab.snapshot() == before, "Corrupt file overwritten")
        elif name in ("lock", "pending"):
            lab.seed()
            blocked = lab.root / (".memory.lock" if name == "lock" else ".memory.pending")
            blocked.write_text("owned by another run")
            before = lab.snapshot()
            lab.apply("请记住：reply_language=English", 1, status="error",
                      error="store_busy" if name == "lock" else "pending_unavailable")
            require(lab.snapshot() == before and blocked.read_text() == "owned by another run", "Touched foreign resource")
            if name == "pending":
                require(not (lab.root / ".memory.lock").exists(), "Owned lock leaked")
        elif name == "save-failure":
            lab.seed()
            lab.reject_unchanged(quote="请记住：reply_language=English", expected=1,
                                 status="error", error="injected_before_rename", fail=True)
            require(lab.recall()["fact"]["action"]["value"] == "中文", "Failed save replaced fact")
        elif name == "size-limit":
            lab.corrupt(b" " * 65_537)
            lab.recall(status="error", error="size_limit")
            lab.reject_unchanged(status="error", error="size_limit")
        elif name == "event-limit":
            a = {"scope":"project-a", "key":"reply_language", "action":{"kind":"set", "value":"中文"},
                 "source":{"session":"session-A", "turn":1, "role":"user", "quote":"请记住：reply_language=中文"}}
            lab.corrupt({"schema":1, "events":[dict(a, revision=i+1) for i in range(64)]})
            lab.reject_unchanged(quote="请记住：reply_language=English", expected=64, status="error", error="event_limit")
            require(lab.recall()["revision"] == 64, "Limit damaged readable state")
        elif name == "invalid-cli":
            lab.invoke("invalid command", ["unknown"], "error", "usage")
            lab.invoke("extra argument", ["recall", lab.root, "project-a", "reply_language", "extra"], "error", "usage")
        text = "\n".join(lab.lines) + "\n"
        outputs[name] = text.encode()
        rows.append(dict(name=name, processes=len(lab.steps), steps=lab.steps,
                         stdout_sha256=hashlib.sha256(text.encode()).hexdigest()))
    return rows, outputs


def package_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("memory-lab/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="agent-r09-") as directory:
        folder = Path(directory) / "source"
        folder.mkdir()
        for name, content in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(Path(directory) / "target"), RUSTFLAGS="-D warnings")
        command(["cargo", "fmt", "--", "--check"], folder, env)
        tests = command(["cargo", "test", "--locked"], folder, env)
        require("8 passed; 0 failed" in tests, "Unexpected contract tests")
        command(["cargo", "build", "--locked"], folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r09"
        runs = Path(directory) / "runs"
        runs.mkdir()
        rows, outputs = scenarios(binary, runs)
        evidence = dict(scope="R09 deterministic extraction; JSON event history; real disk; separate CLI processes; no LLM or framework integration",
                        source_sha256=hashlib.sha256(files["src/main.rs"]).hexdigest(),
                        files_sha256={name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
                        rustc=command(["rustc", "--version"], folder).strip(),
                        host=command(["rustc", "-vV"], folder).split("host: ")[1].splitlines()[0],
                        contract_tests_passed=8, scenarios=rows)
        if args.check and DATA.exists():
            recorded = json.loads(DATA.read_text())
            for key in ("rustc", "host"):
                evidence[key] = recorded[key]
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
        artifacts[DATA] = serialized
        package = dict(files, **{"outputs/" + name + ".txt":content for name,content in outputs.items()})
        package["evidence.json"] = serialized
        archive = package_bytes(package)
        artifacts[ARCHIVE] = archive
        for name, content in outputs.items():
            artifacts[OUT / ("r09-" + name + ".txt")] = content
        # Compile the exact generated archive, then repeat every scenario outside the checkout.
        extracted = Path(directory) / "download"
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            z.extractall(extracted)
        download_env = dict(env, CARGO_TARGET_DIR=str(Path(directory) / "download-target"))
        command(["cargo", "build", "--locked", "--offline"], extracted / "memory-lab", download_env)
        download_binary = Path(download_env["CARGO_TARGET_DIR"]) / "debug/learn-agent-r09"
        again = Path(directory) / "again"
        again.mkdir()
        repeated_rows, repeated_outputs = scenarios(download_binary, again)
        require(repeated_rows == rows and repeated_outputs == outputs, "Extracted download behavior differs")
    chapter = CHAPTER.read_text()
    start, end = "<!-- r09-results:start -->", "<!-- r09-results:end -->"
    require(chapter.count(start) == 1 and chapter.count(end) == 1, "Missing R09 results markers")
    table = "| 场景 | 独立 CLI 进程 | 最后结果 |\n| --- | --- | --- |\n"
    for row in rows:
        last = row["steps"][-1]
        table += "| `{}` | {} | `{}` |\n".format(row["name"], row["processes"], last["error"] or last["status"])
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    artifacts[CHAPTER] = (before + start + "\n\n" + table.rstrip() + "\n\n" + end + after).encode()
    source = files["src/main.rs"].decode()
    for region in re.findall(r"<<< @/public/learn-agent-rust/code/memory/src/main.rs#([\w-]+)", chapter):
        require(source.count("// region " + region + "\n") == 1 and source.count("// endregion " + region + "\n") == 1, "Invalid code region " + region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r09-([\w-]+).txt", chapter):
        require(name in outputs, "Unverified output import " + name)
    for path, content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale R09 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R09: {} scenarios / {} separate CLI processes, 8 Rust tests, all scenarios repeated from extracted archive; {}".format(
        len(rows), sum(row["processes"] for row in rows), "artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
