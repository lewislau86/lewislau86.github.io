"""P02: independent client/provider processes, two SQLite DBs and real crash/replay evidence."""
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
PUBLIC = ROOT / "docs/public/learn-agent-rust"
SOURCE = PUBLIC / "code/side-effect-reliability"
CHAPTER = ROOT / "docs/learn-agent-rust/side-effect-reliability.md"
DATA = ROOT / "scripts/data/learn-agent-rust/p02-results.json"
ARCHIVE = PUBLIC / "side-effect-reliability.zip"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".gitignore", "README.md",
         "src/main.rs", "src/client.rs", "src/provider.rs", "src/tests.rs"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, cwd, env):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    require(p.returncode == 0, str(args) + "\n" + p.stdout + p.stderr)
    return p.stdout


def request(tenant="course", operation_id="review-42", title="Review Rust timeout handling"):
    return dict(tenant=tenant, operation_id=operation_id, title=title)


class Lab:
    def __init__(self, binary, folder):
        self.binary = binary
        self.folder = Path(folder)
        self.local = self.folder / "client.sqlite"
        self.remote = self.folder / "provider.sqlite"
        self.lines, self.steps = [], []

    def call(self, *args, error=None, code=None):
        p = subprocess.run([str(self.binary)] + [str(a) for a in args], cwd=self.folder,
                           capture_output=True, text=True, timeout=15)
        expected = code if code is not None else 10 if error else 0
        require(p.returncode == expected, f'{args}: code={p.returncode} {p.stdout} {p.stderr}')
        if code is not None:
            require(not p.stdout and "injected_exit=" in p.stderr, "Expected an injected process exit")
            value = dict(process_exit=code)
        else:
            require(not p.stderr, f'Unexpected stderr: {p.stderr}')
            value = json.loads(p.stdout)
            if error:
                require(value == dict(error=error), f'{args}: {value} != {error}')
        normalized = ["CLIENT_DB" if str(a) == str(self.local) else "PROVIDER_DB" if str(a) == str(self.remote) else str(a) for a in args]
        self.steps.append(dict(command=normalized, result=value, exit_code=p.returncode))
        self.lines.append("$ " + " ".join(normalized))
        self.lines.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return value

    def prepare(self, payload=None, mode="key", now=0, fault="none", **expected):
        return self.call("prepare", self.local, json.dumps(payload or request(), separators=(",", ":")), mode, now, fault, **expected)

    def send(self, recover=False, tenant="course", operation_id="review-42", now=1, fault="none", **expected):
        return self.call("recover" if recover else "dispatch", self.local, self.remote, tenant, operation_id, now, fault, **expected)

    def apply(self, payload=None, mode="key", now=1, fault="none", **expected):
        return self.call("apply", self.remote, json.dumps(payload or request(), separators=(",", ":")), mode, now, fault, **expected)

    def sql(self, db, query, params=()):
        with sqlite3.connect(db) as connection:
            return connection.execute(query, params).fetchall()

    def snapshot(self):
        local = self.call("inspect-client", self.local)
        remote = self.call("inspect-provider", self.remote)
        # Inspect actual databases independently of the Rust report serializer.
        require(self.sql(self.remote, "SELECT count(*) FROM tickets")[0][0] == remote["ticket_count"], "Provider count mismatch")
        require(self.sql(self.local, "SELECT count(*) FROM checkpoints")[0][0] == local["checkpoints"], "Checkpoint count mismatch")
        require(local["actions"] == len(local["outbox"]), "Intent/outbox not atomic")
        require(local["completed_actions"] == local["checkpoints"], "Checkpoint/action not atomic")
        for tenant, operation_id, payload, digest in self.sql(self.remote, "SELECT tenant,operation_id,request,digest FROM tickets"):
            require(sha(payload.encode()) == digest, "Provider payload hash mismatch")
            parsed = json.loads(payload)
            require(parsed["tenant"] == tenant and parsed["operation_id"] == operation_id, "Provider identity mismatch")
        for tenant, operation_id, raw in self.sql(self.local, "SELECT tenant,operation_id,receipt FROM checkpoints"):
            receipt = json.loads(raw)
            matches = [r for r in remote["tickets"] if r == receipt]
            require(len(matches) == 1, "Checkpoint has no unique real business receipt")
            require(receipt["request"]["tenant"] == tenant and receipt["request"]["operation_id"] == operation_id, "Wrong checkpoint identity")
        return local, remote


def scenarios(binary, directory):
    names = ["normal", "naive-retry", "response-lost-reconcile", "response-lost-replay", "exit-before-send",
             "provider-rollback", "outbox-rollback", "prepare-committed", "response-received-local-lost",
             "ack-without-checkpoint", "checkpoint-rollback", "checkpoint-committed", "intent-conflict",
             "provider-conflict", "new-operation-id", "tenant-scope", "concurrent-provider", "retry-budget",
             "expired-key-unsafe", "expired-client-stop", "expired-reconcile", "no-key-reconcile",
             "no-key-empty", "ambiguous-reconcile", "incomplete-query", "query-unavailable", "receipt-mismatch",
             "corrupt-intent", "clock-regression"]
    reports, outputs = [], {}
    for name in names:
        folder = Path(directory) / name
        folder.mkdir()
        lab = Lab(binary, folder)
        expected_tickets, expected_checkpoints = 1, 1
        if name == "normal":
            lab.prepare()
            lab.send()
            lab.send(recover=True, now=2)
        elif name == "naive-retry":
            lab.apply(mode="none", fault="after-commit", code=82)
            lab.apply(mode="none")
            expected_tickets, expected_checkpoints = 2, 0
        elif name in ("response-lost-reconcile", "response-lost-replay", "expired-reconcile", "no-key-reconcile"):
            lab.prepare(mode="none" if name == "no-key-reconcile" else "key")
            lab.send(fault="provider-after-commit", error="outcome_unknown")
            require(lab.sql(lab.local, "SELECT state FROM outbox") == [("unknown",)], "Lost response was acknowledged")
            require(lab.sql(lab.remote, "SELECT count(*) FROM tickets")[0][0] == 1, "Provider commit lost")
            if name == "expired-reconcile":
                lab.call("expire", lab.remote, 101)
            lab.send(recover=name != "response-lost-replay", now=101 if name == "expired-reconcile" else 2)
        elif name in ("exit-before-send", "provider-rollback", "response-received-local-lost", "ack-without-checkpoint", "checkpoint-rollback", "checkpoint-committed"):
            lab.prepare()
            fault, exit_code = {
                "exit-before-send": ("before-send", 83),
                "provider-rollback": ("provider-before-commit", None),
                "response-received-local-lost": ("after-response", 84),
                "ack-without-checkpoint": ("after-ack", 87),
                "checkpoint-rollback": ("before-checkpoint-commit", 85),
                "checkpoint-committed": ("after-checkpoint-commit", 86),
            }[name]
            if exit_code:
                lab.send(fault=fault, code=exit_code)
            else:
                lab.send(fault=fault, error="outcome_unknown")
            before = lab.call("inspect-client", lab.local)
            expected_before = "completed" if name == "checkpoint-committed" else "acked" if name in ("ack-without-checkpoint", "checkpoint-rollback") else "unknown"
            require(before["outbox"][0]["state"] == expected_before, name + " wrong fault boundary")
            require(before["checkpoints"] == int(name == "checkpoint-committed"), "Uncommitted checkpoint leaked")
            lab.send(recover=True, now=2)
        elif name == "outbox-rollback":
            for fault, code in [("between-local-writes", 80), ("before-prepare-commit", 81)]:
                lab.prepare(fault=fault, code=code)
                before = lab.call("inspect-client", lab.local)
                require(before["actions"] == before["checkpoints"] == len(before["outbox"]) == 0, "Partial local intent survived")
            lab.prepare()
            lab.send()
        elif name == "prepare-committed":
            lab.prepare(fault="after-prepare-commit", code=82)
            require(lab.prepare(now=99)["prepared"] is False, "Prepare duplicated")
            require(lab.sql(lab.local, "SELECT safe_until FROM outbox")[0][0] == 100, "Retry window moved")
            lab.send(now=1)
        elif name == "intent-conflict":
            lab.prepare()
            lab.prepare(request(title="Changed task"), error="local_intent_conflict")
            lab.prepare(mode="none", error="local_intent_conflict")
            lab.send()
        elif name == "provider-conflict":
            lab.apply()
            lab.apply(request(title="Changed task"), error="idempotency_conflict")
            expected_checkpoints = 0
        elif name in ("new-operation-id", "tenant-scope"):
            second = request(operation_id="review-43") if name == "new-operation-id" else request(tenant="another")
            for r in [request(), second]:
                lab.prepare(r)
                lab.send(tenant=r["tenant"], operation_id=r["operation_id"])
            expected_tickets = expected_checkpoints = 2
        elif name == "concurrent-provider":
            # Initialize before spawning, so the concurrency test targets transactions rather than schema creation.
            lab.call("inspect-provider", lab.remote)
            children = [subprocess.Popen([str(binary), "apply", str(lab.remote), json.dumps(request(), separators=(",", ":")), "key", "1", "none"],
                                         cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
            receipts = []
            for child in children:
                out, err = child.communicate(timeout=15)
                require(child.returncode == 0 and not err, "Concurrent provider failed: " + err + out)
                receipts.append(json.loads(out)["receipt"])
            require(all(r == receipts[0] for r in receipts), "Concurrent calls created distinct tickets")
            lab.lines.append("four provider processes: identical receipt; one ticket")
            lab.steps.append(dict(concurrent_processes=4, same_receipt=True))
            expected_checkpoints = 0
        elif name == "retry-budget":
            lab.prepare()
            for now in (1, 2, 3):
                lab.send(now=now, fault="before-send", code=83)
            lab.send(now=4, error="attempt_budget")
            expected_tickets = expected_checkpoints = 0
        elif name == "expired-key-unsafe":
            lab.apply(fault="after-commit", code=82)
            lab.call("expire", lab.remote, 101)
            lab.apply(now=101)
            expected_tickets, expected_checkpoints = 2, 0
        elif name == "expired-client-stop":
            lab.prepare()
            lab.send(fault="provider-after-commit", error="outcome_unknown")
            lab.call("expire", lab.remote, 101)
            lab.send(now=100, error="retry_window_expired")
            expected_checkpoints = 0
        elif name == "no-key-empty":
            lab.prepare(mode="none")
            lab.send(fault="before-send", code=83)
            lab.send(recover=True, now=2, error="manual_reconciliation_required")
            expected_tickets = expected_checkpoints = 0
        elif name == "ambiguous-reconcile":
            lab.prepare(mode="none")
            lab.send(fault="provider-after-commit", error="outcome_unknown")
            lab.apply(mode="none")
            lab.send(recover=True, now=2, error="reconciliation_ambiguous")
            expected_tickets, expected_checkpoints = 2, 0
        elif name in ("incomplete-query", "query-unavailable"):
            lab.prepare(mode="none")
            lab.send(fault="provider-after-commit", error="outcome_unknown")
            lab.send(recover=True, now=2, fault="query-hidden" if name == "incomplete-query" else "query-unavailable",
                     error="reconciliation_incomplete" if name == "incomplete-query" else "reconciliation_unavailable")
            expected_checkpoints = 0
        elif name == "receipt-mismatch":
            lab.prepare()
            lab.send(fault="bad-receipt", error="receipt_mismatch")
            require(lab.sql(lab.local, "SELECT state,receipt FROM outbox") == [("unknown", None)], "Forged receipt acknowledged")
            lab.send(recover=True, now=2)
        elif name == "corrupt-intent":
            lab.prepare()
            lab.sql(lab.local, "UPDATE outbox SET digest='bad'")
            lab.send(error="corrupt_intent")
            expected_tickets = expected_checkpoints = 0
        elif name == "clock-regression":
            lab.prepare()
            lab.send(now=5, fault="before-send", code=83)
            lab.send(now=4, error="clock_regression")
            lab.send(now=6)
        else:
            raise AssertionError(name)
        local, remote = lab.snapshot()
        require(remote["ticket_count"] == expected_tickets and local["checkpoints"] == expected_checkpoints, name + " final counts")
        if name == "response-lost-replay":
            require(remote["committed_apply_calls"] == 2 and local["outbox"][0]["attempts"] == 2, "Replay was not a real second request")
        if name == "concurrent-provider":
            require(remote["committed_apply_calls"] == 4, "Concurrent calls missing")
        if name in ("no-key-empty", "incomplete-query", "query-unavailable", "ambiguous-reconcile", "expired-client-stop", "retry-budget"):
            require(local["outbox"][0]["state"] == "unknown", name + " lost uncertainty")
        if name == "no-key-empty":
            require(remote["committed_apply_calls"] == 0, "Non-idempotent unknown request resent")
        if name == "normal":
            require(remote["committed_apply_calls"] == 1, "Checkpoint replay resent request")
        summary = "scenario={} tickets={} checkpoints={} attempts={} apply_commits={} queries={}\n".format(
            name, remote["ticket_count"], local["checkpoints"], sum(r["attempts"] for r in local["outbox"]),
            remote["committed_apply_calls"], remote["query_calls"])
        summary += "local_state={}\n".format(",".join(r["state"] for r in local["outbox"]) or "no_intent")
        output = (summary + "\n" + "\n".join(lab.lines) + "\n").encode()
        outputs[name] = output
        reports.append(dict(scenario=name, local=local, provider=remote, steps=lab.steps, stdout_sha256=sha(output)))
    return reports, outputs


def pack(files):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo("side-effect-reliability/" + name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return content.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = {name: (SOURCE / name).read_bytes() for name in FILES}
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / ".cache/learn-agent-p02-target")
    with tempfile.TemporaryDirectory(prefix="p02-source-") as directory:
        with zipfile.ZipFile(io.BytesIO(pack(files))) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "side-effect-reliability"
        run(["cargo", "fmt", "--check"], folder, env)
        tests = run(["cargo", "test", "--locked", "--quiet"], folder, env)
        match = re.search(r"test result: ok\. (\d+) passed; 0 failed;", tests)
        require(match is not None, tests)
        run(["cargo", "clippy", "--locked", "--all-targets", "--quiet", "--", "-D", "warnings"], folder, env)
        run(["cargo", "build", "--locked", "--offline", "--quiet"], folder, env)
        binary = Path(env["CARGO_TARGET_DIR"]) / "debug/learn-agent-p02"
        reports, outputs = scenarios(binary, directory)
        demo = json.loads(run([binary], folder, env))
        require(demo["workspace_removed"] and demo["provider"]["ticket_count"] == demo["after_recovery"]["checkpoints"] == 1, "Default demo failed")
        demo_output = (json.dumps(demo, ensure_ascii=False, indent=2) + "\n").encode()
        rustc = run(["rustc", "--version"], folder, env).strip()
    if args.check and DATA.exists():
        rustc = json.loads(DATA.read_text())["rustc"]
    evidence = dict(scope="P02; independent local CLI client/provider processes, separate SQLite databases, committed business tickets, checkpoint exit faults; no HTTP, model, graph-flow, PostgreSQL or physical power-loss test",
                    rustc=rustc, tests_passed=int(match[1]), source_sha256={name: sha(data) for name, data in files.items()}, scenarios=reports)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets = {DATA: serialized, PUBLIC / "outputs/p02-demo.txt": demo_output}
    for name, output in outputs.items():
        targets[PUBLIC / "outputs" / f"p02-{name}.txt"] = output
        files[f"outputs/{name}.txt"] = output
    files["evidence.json"], files["outputs/demo.txt"] = serialized, demo_output
    targets[ARCHIVE] = pack(files)
    with tempfile.TemporaryDirectory(prefix="p02-download-") as directory:
        with zipfile.ZipFile(io.BytesIO(targets[ARCHIVE])) as archive:
            archive.extractall(directory)
        folder = Path(directory) / "side-effect-reliability"
        run(["cargo", "build", "--locked", "--offline", "--quiet"], folder, env)
        actual_reports, actual_outputs = scenarios(binary, directory)
        require(actual_reports == reports and actual_outputs == outputs, "Final archive changed experiment results")
        require(json.loads(run([binary], folder, env)) == demo, "Download demo changed")
    chapter = CHAPTER.read_text()
    start, end = "<!-- p02-results:start -->", "<!-- p02-results:end -->"
    require(chapter.count(start) == chapter.count(end) == 1, "Missing P02 result markers")
    table = ["| 场景 | 服务工单 | 本地检查点 | apply 提交 / 对账查询 | 最终 Outbox 状态 |", "| --- | --- | --- | --- | --- |"]
    for r in reports:
        p, c = r["provider"], r["local"]
        table.append("| `{}` | {} | {} | {} / {} | {} |".format(r["scenario"], p["ticket_count"], c["checkpoints"], p["committed_apply_calls"], p["query_calls"], ", ".join("`" + row["state"] + "`" for row in c["outbox"]) or "无意图"))
    before, rest = chapter.split(start)
    _, after = rest.split(end)
    targets[CHAPTER] = (before + start + "\n\n" + "\n".join(table) + "\n\n" + end + after).encode()
    for filename, region in re.findall(r"<<< @/public/learn-agent-rust/code/side-effect-reliability/([^#\s]+)#([\w-]+)", chapter):
        source = (SOURCE / filename).read_text()
        require(source.count("// region " + region + "\n") == source.count("// endregion " + region + "\n") == 1, region)
    for path, content in targets.items():
        if args.check:
            require(path.exists() and path.read_bytes() == content, "Stale P02 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f'P02: {len(reports)} scenarios, {match[1]} Rust tests, Clippy, independent SQL verification, process exits, offline demo and all final-download scenarios passed; ' + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
