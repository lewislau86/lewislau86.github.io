"""R14: real SQLite, independent processes, fixed-clock scheduling and exit fault points."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/scheduling"
CHAPTER = ROOT / "docs/learn-agent-rust/scheduling.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r14-results.json"
OUT = ROOT / "docs/public/learn-agent-rust/outputs"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/scheduling-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", ".gitignore", "README.md", "src/main.rs", "src/scheduler.rs"]
START, DUE = "2026-11-07T00:59:00Z", "2026-11-07T01:00:00Z"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(args, cwd, env=None):
    p = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args, p.stdout, p.stderr))
    return p.stdout


class Lab:
    def __init__(self, binary, folder):
        self.binary, self.folder = binary, Path(folder)
        self.db = self.folder / "schedule.db"
        self.steps, self.lines = [], []

    def invoke(self, args, status=None, error=None, exit_code=None):
        p = subprocess.run([str(self.binary)] + [str(a) for a in args], cwd=self.folder,
                           capture_output=True, text=True, timeout=15)
        label = " ".join("DB" if str(a) == str(self.db) else str(a) for a in args)
        require(not p.stderr, label + ": unexpected stderr: " + p.stderr)
        if exit_code:
            require(p.returncode == exit_code and not p.stdout, "Exit fault failed: " + label)
            result = {"status":"process_exit", "code":exit_code}
        else:
            require(p.returncode == (1 if error else 0), label + ": wrong exit code " + p.stdout)
            result = json.loads(p.stdout)
            require(result["status"] == ("error" if error else status), label + ": wrong status")
            if error:
                require(result.get("error") == error, label + ": wrong error: " + p.stdout)
        self.lines.extend([label, json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))])
        self.steps.append(result)
        return result

    def init(self):
        return self.invoke(["init", self.db], "initialized")

    def add(self, start=START, zone="Asia/Shanghai", hhmm="09:00", policy="coalesce", name="report", error=None):
        return self.invoke(["add", self.db, name, zone, hhmm, policy, "--start", start], "added", error)

    def tick(self, now=DUE, fault=None, error=None, exit_code=None):
        return self.invoke(["tick", self.db, now] + ([fault] if fault else []), "committed", error, exit_code)

    def show(self):
        return self.invoke(["show", self.db], "snapshot")

    def sql(self, query, params=()):
        with sqlite3.connect(self.db) as db:
            return db.execute(query, params).fetchall()

    def count(self):
        return self.sql("SELECT count(*) FROM tasks")[0][0]

    def seed(self, **kwargs):
        self.init()
        self.add(**kwargs)


def scenarios(binary, directory):
    names = ["normal", "restart", "coalesce", "skip", "grace", "grace-expired", "not-due",
             "dst-gap", "dst-fold", "rollback", "exit-before-commit", "exit-after-commit",
             "duplicate-identity", "clock-regression", "window-limit", "rollback-all", "busy",
             "duplicate-schedule", "invalid-config", "invalid-time", "missing", "corrupt", "schema",
             "invalid-cursor", "queue-limit", "invalid-cli", "real-clock-poll"]
    rows, outputs = [], {}
    for name in names:
        folder = Path(directory) / name
        folder.mkdir()
        lab = Lab(binary, folder)
        if name == "normal":
            lab.seed()
            require(lab.tick("2026-11-07T00:59:59Z")["reports"][0]["inserted"] == 0, "Early trigger")
            require(lab.tick()["reports"][0]["inserted"] == 1, "Missing due trigger")
            require(lab.tick()["reports"][0]["inserted"] == 0, "Duplicate tick")
            state = lab.show()
            require(len(state["tasks"]) == 1 and state["tasks"][0]["due"] == DUE, "Wrong durable occurrence")
            require(state["tasks"][0]["state"] == "queued", "Task was executed")
        elif name == "restart":
            lab.seed()
            lab.tick()
            first = lab.show()["tasks"][0]
            lab.tick("2026-11-08T01:00:00Z")
            tasks = lab.show()["tasks"]
            require(len(tasks) == 2 and tasks[0] == first, "Restart lost or duplicated original")
        elif name in ("coalesce", "skip"):
            lab.seed(start="2026-11-06T00:59:00Z", policy=name)
            result = lab.tick("2026-11-08T01:05:00Z")["reports"][0]
            require(result["due_count"] == 3, "Wrong missed count")
            require(result["inserted"] == (1 if name == "coalesce" else 0), "Wrong misfire policy")
            require(result["discarded"] == (2 if name == "coalesce" else 3), "Wrong discard count")
            state = lab.show()
            require(len(state["tasks"]) == result["inserted"], "Queue differs from report")
            if name == "coalesce":
                require(state["tasks"][0]["due"] == "2026-11-08T01:00:00Z", "Did not pick latest")
        elif name in ("grace", "grace-expired"):
            lab.seed(policy="skip")
            report = lab.tick("2026-11-07T01:01:" + ("00Z" if name == "grace" else "01Z"))["reports"][0]
            require(report["inserted"] == (1 if name == "grace" else 0), "Incorrect inclusive grace")
            lab.show()
        elif name == "not-due":
            lab.seed()
            require(lab.tick("2026-11-07T00:59:59Z")["reports"][0]["due_count"] == 0, "Future trigger emitted")
            require(not lab.show()["tasks"], "Early queue item")
        elif name == "dst-gap":
            mapping = lab.invoke(["resolve", "America/New_York", "2026-03-08", "02:30"], "resolved")
            require(mapping["mapping"] == "gap" and mapping["chosen"] is None, "Gap not detected")
            lab.seed(start="2026-03-08T05:00:00Z", zone="America/New_York", hhmm="02:30")
            require(lab.tick("2026-03-09T03:59:59Z")["reports"][0]["due_count"] == 0, "Gap triggered")
            require(not lab.show()["tasks"], "Gap queue item")
        elif name == "dst-fold":
            mapping = lab.invoke(["resolve", "America/New_York", "2026-11-01", "01:30"], "resolved")
            require(mapping["utc"] == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"], "Unexpected tzdb fold")
            lab.seed(start="2026-11-01T04:00:00Z", zone="America/New_York", hhmm="01:30")
            require(lab.tick("2026-11-01T05:30:00Z")["reports"][0]["inserted"] == 1, "Earlier fold absent")
            require(lab.tick("2026-11-01T06:30:00Z")["reports"][0]["inserted"] == 0, "Fold duplicated")
            require(len(lab.show()["tasks"]) == 1, "Fold queue count")
        elif name in ("rollback", "exit-before-commit"):
            lab.seed()
            before = lab.show()
            if name == "rollback":
                lab.tick(fault="--fail-after-insert", error="injected_after_insert")
            else:
                lab.tick(fault="--exit-after-insert", exit_code=73)
            require(lab.show() == before, "Uncommitted insertion or cursor survived")
            require(lab.tick()["reports"][0]["inserted"] == 1, "Restart did not retry")
            require(len(lab.show()["tasks"]) == 1, "Recovery lost occurrence")
        elif name == "exit-after-commit":
            lab.seed()
            lab.tick(fault="--exit-after-commit", exit_code=74)
            state = lab.show()
            require(len(state["tasks"]) == 1 and state["schedules"][0]["cursor"] == DUE, "Commit not durable")
            require(lab.tick()["reports"][0]["inserted"] == 0, "Lost acknowledgment duplicated task")
            require(lab.show() == state, "Replay changed durable state")
        elif name == "duplicate-identity":
            lab.seed()
            lab.tick()
            # Fault fixture: roll back only the cursor, retaining the existing queue row.
            lab.sql("UPDATE schedules SET cursor_utc=?", (1794013140,))
            require(lab.tick()["reports"][0]["inserted"] == 0, "Unique identity bypassed")
            require(len(lab.show()["tasks"]) == 1, "Duplicate identity stored")
        elif name in ("clock-regression", "window-limit"):
            lab.seed()
            before = lab.show()
            lab.tick("2026-11-07T00:58:59Z" if name == "clock-regression" else "2026-12-09T01:00:00Z",
                     error="clock_regression" if name == "clock-regression" else "scan_window_limit")
            require(lab.show() == before, "Rejected scan changed state")
        elif name == "rollback-all":
            lab.seed(name="a-valid")
            lab.add(name="z-future", start="2026-11-07T02:00:00Z")
            before = lab.show()
            lab.tick(error="clock_regression")
            require(lab.show() == before, "Partial multi-schedule commit")
        elif name == "busy":
            lab.seed()
            before = lab.show()
            with sqlite3.connect(lab.db, timeout=0) as locker:
                locker.execute("BEGIN IMMEDIATE")
                lab.tick(error="store_busy")
            require(lab.show() == before, "Busy attempt mutated state")
            lab.tick()
            require(len(lab.show()["tasks"]) == 1, "Busy retry lost trigger")
        elif name == "duplicate-schedule":
            lab.seed()
            before = lab.show()
            lab.add(zone="UTC", error="duplicate_schedule")
            require(lab.show() == before, "Immutable config overwritten")
        elif name == "invalid-config":
            lab.init()
            before = lab.show()
            lab.add(zone="No/SuchZone", error="invalid_timezone")
            lab.add(hhmm="25:00", error="invalid_local_time")
            lab.add(name="../report", error="invalid_id")
            lab.add(policy="all", error="invalid_misfire")
            require(lab.show() == before, "Invalid config saved")
        elif name == "invalid-time":
            lab.seed()
            before = lab.show()
            for timestamp, error in [("2026-11-07T01:00:00", "invalid_timestamp"),
                                     ("2026-11-07T01:00:00.1Z", "unsupported_timestamp"),
                                     ("1999-01-01T00:00:00Z", "unsupported_timestamp")]:
                lab.tick(timestamp, error=error)
            require(lab.show() == before, "Invalid time changed state")
        elif name == "missing":
            lab.invoke(["show", lab.db], error="database_error")
            require(not lab.db.exists(), "Missing database silently created")
        elif name == "corrupt":
            lab.db.write_bytes(b"not a SQLite database")
            before = lab.db.read_bytes()
            lab.tick(error="database_error")
            require(lab.db.read_bytes() == before, "Corrupt data overwritten")
        elif name == "schema":
            lab.seed()
            lab.sql("PRAGMA user_version=2")
            before = lab.db.read_bytes()
            lab.tick(error="unsupported_schema")
            require(lab.db.read_bytes() == before, "Unsupported schema mutated")
        elif name == "invalid-cursor":
            lab.seed()
            lab.sql("UPDATE schedules SET cursor_utc=9223372036854775807")
            lab.tick(error="invalid_cursor")
            lab.invoke(["show", lab.db], error="invalid_cursor")
            require(lab.count() == 0, "Invalid cursor created task")
        elif name == "queue-limit":
            lab.seed()
            with sqlite3.connect(lab.db) as db:
                db.executemany("INSERT INTO tasks VALUES (?,?,?,'daily_report','queued')",
                    [("report@" + str(1793500000+i), "report", 1793500000+i) for i in range(4096)])
            cursor = lab.sql("SELECT cursor_utc FROM schedules")
            lab.tick(error="queue_limit")
            require(lab.count() == 4096 and lab.sql("SELECT cursor_utc FROM schedules") == cursor, "Queue limit failed rollback")
        elif name == "invalid-cli":
            lab.seed()
            before = lab.show()
            lab.invoke(["init", lab.db], error="database_exists")
            lab.invoke(["unknown"], error="usage")
            lab.invoke(["tick", lab.db, DUE, "--unknown"], error="usage")
            lab.invoke(["add", lab.db, "other", "UTC", "09:00", "coalesce", "--wrong", START], error="usage")
            lab.invoke(["run", lab.db, "0"], error="invalid_ticks")
            require(lab.show() == before, "Invalid CLI mutated database")
        elif name == "real-clock-poll":
            lab.init()
            lab.invoke(["run", lab.db, "2"], "polling_stopped")
            require(not lab.show()["tasks"], "Empty schedule emitted task")
        output = ("\n".join(lab.lines) + "\n").encode()
        outputs[name] = output
        try:
            count = lab.count() if lab.db.exists() else None
        except sqlite3.DatabaseError:
            count = None
        rows.append({"name":name, "processes":len(lab.steps), "queued":count,
            "steps":lab.steps, "stdout_sha256":hashlib.sha256(output).hexdigest()})
    return rows, outputs


def package_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("scheduling-lab/" + name, (2026,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name:(SOURCE/name).read_bytes() for name in FILES}
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="agent-r14-") as directory:
        folder = Path(directory) / "source"
        for name, content in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        env = dict(os.environ, CARGO_TARGET_DIR=str(Path(directory)/"target"), RUSTFLAGS="-D warnings")
        command(["cargo","fmt","--","--check"], folder, env)
        tests = command(["cargo","test","--locked"], folder, env)
        require("10 passed; 0 failed" in tests, "Unexpected test count")
        command(["cargo","clippy","--locked","--all-targets","--","-D","warnings"], folder, env)
        command(["cargo","build","--locked"], folder, env)
        binary = Path(env["CARGO_TARGET_DIR"])/"debug/learn-agent-r14"
        runs = Path(directory)/"runs"
        runs.mkdir()
        rows, outputs = scenarios(binary, runs)
        evidence = {"scope":"R14 fixed-clock scans, named timezones, real SQLite transactions and separate CLI processes; bounded real-clock poll; no Agent or task execution",
            "files_sha256":{name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
            "rustc":command(["rustc","--version"],folder).strip(),
            "host":command(["rustc","-vV"],folder).split("host: ")[1].splitlines()[0],
            "libraries":json.loads(command([binary,"versions"],folder)), "contract_tests_passed":10,"scenarios":rows}
        if args.check and DATA.exists():
            recorded = json.loads(DATA.read_text())
            for key in ("rustc","host"):
                evidence[key] = recorded[key]
        serialized = (json.dumps(evidence, ensure_ascii=False, indent=2)+"\n").encode()
        artifacts[DATA] = serialized
        package = dict(files, **{"outputs/"+name+".txt":content for name,content in outputs.items()})
        package["evidence.json"] = serialized
        archive = package_bytes(package)
        artifacts[ARCHIVE] = archive
        artifacts.update({OUT/("r14-"+name+".txt"):content for name,content in outputs.items()})
        extracted = Path(directory)/"download"
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            z.extractall(extracted)
        download_env = dict(env, CARGO_TARGET_DIR=str(Path(directory)/"download-target"))
        command(["cargo","build","--locked","--offline"], extracted/"scheduling-lab", download_env)
        again = Path(directory)/"again"
        again.mkdir()
        repeated_rows, repeated_outputs = scenarios(Path(download_env["CARGO_TARGET_DIR"])/"debug/learn-agent-r14", again)
        require(repeated_rows == rows and repeated_outputs == outputs, "Extracted download behavior differs")
    chapter = CHAPTER.read_text()
    start, end = "<!-- r14-results:start -->", "<!-- r14-results:end -->"
    require(chapter.count(start)==1 and chapter.count(end)==1, "Missing result table markers")
    table = "| 场景 | 独立 CLI 进程 | 最终排队数 | 故障 / 拒绝 |\n| --- | --- | --- | --- |\n"
    for row in rows:
        faults = sorted(set(step.get("error") or ("exit="+str(step["code"]) if step["status"]=="process_exit" else "") for step in row["steps"]) - {""})
        table += "| `{}` | {} | {} | {} |\n".format(row["name"],row["processes"],row["queued"] if row["queued"] is not None else "—", " / ".join("`"+f+"`" for f in faults) or "—")
    before,rest=chapter.split(start)
    _,after=rest.split(end)
    artifacts[CHAPTER]=(before+start+"\n\n"+table.rstrip()+"\n\n"+end+after).encode()
    for filename,region in re.findall(r"<<< @/public/learn-agent-rust/code/scheduling/(src/[\w.]+)#([\w-]+)",chapter):
        source=files[filename].decode()
        require(source.count("// region "+region+"\n")==1 and source.count("// endregion "+region+"\n")==1,"Invalid source region "+region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r14-([\w-]+).txt",chapter):
        require(name in outputs,"Unverified output "+name)
    for path,content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes()==content,"Stale R14 artifact: "+str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
    print("R14: {} scenarios / {} independent CLI processes, 10 Rust tests, Clippy and extracted archive replay passed; {}".format(
        len(rows),sum(row["processes"] for row in rows),"artifacts checked" if args.check else "artifacts saved"))


if __name__=="__main__":
    main()
