"""P04: real PostgreSQL drills on TWO disposable clusters; no existing database."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time


def require(value, message):
    if not value:
        raise ValueError(message)


def command(args, env=None):
    p = subprocess.run([str(x) for x in args], env=env, capture_output=True, text=True, timeout=90)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args[0], p.stdout, p.stderr))
    return p.stdout.strip()


class Cluster:
    def __init__(self):
        executable = shutil.which("postgres")
        configured = os.environ.get("P04_PG_BIN")
        self.bin = Path(configured) if configured else Path(executable).resolve().parent if executable else None
        names = ("postgres", "initdb", "pg_ctl", "psql", "pg_dump", "pg_restore")
        require(self.bin and all((self.bin / n).is_file() for n in names), "Set P04_PG_BIN to PostgreSQL 18 server bin directory")
        self.directory = Path(tempfile.mkdtemp(prefix="p04-pg-", dir="/tmp"))
        self.data, self.socket = self.directory / "data", self.directory / "sock"
        self.socket.mkdir(mode=0o700)
        self.started = False
        self.dsn = "host={} port=55434 user=p04 dbname=postgres connect_timeout=2".format(self.socket)
        self.env = dict(os.environ, P04_DATABASE_URL=self.dsn)

    def __enter__(self):
        try:
            require(" 18." in command([self.bin / "postgres", "--version"]), "PostgreSQL major 18 required")
            command([self.bin / "initdb", "-D", self.data, "-U", "p04", "--auth-local=trust", "--auth-host=reject", "--no-locale", "-E", "UTF8"])
            command([self.bin / "pg_ctl", "-D", self.data, "-l", self.directory / "server.log", "-w", "-t", "20", "-o",
                     "-k {} -h '' -p 55434 -c fsync=on -c synchronous_commit=on -c full_page_writes=on".format(self.socket), "start"])
            self.started = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def stop(self):
        command([self.bin / "pg_ctl", "-D", self.data, "-w", "-t", "20", "-m", "immediate", "stop"])
        self.started = False

    def sql(self, query):
        return command([self.bin / "psql", self.dsn, "-XAt", "-v", "ON_ERROR_STOP=1", "-c", query])

    def __exit__(self, *unused):
        try:
            if self.started:
                self.stop()
        finally:
            shutil.rmtree(self.directory)


def run(binary, output):
    output.mkdir(parents=True, exist_ok=True)
    rows, children = [], []
    process_count = 0

    def call(cluster, value, error=None):
        nonlocal process_count
        process_count += 1
        p = subprocess.run([str(binary), json.dumps(value)], env=cluster.env, capture_output=True, text=True, timeout=20)
        require(not p.stderr, "CLI stderr: " + p.stderr)
        result = json.loads(p.stdout)
        require(p.returncode == (1 if error else 0) and result.get("error") == error, "Wrong CLI result: " + p.stdout)
        return result

    def row(name, **details):
        rows.append(dict(scenario=name, passed=True, **details))

    def worker(cluster, owner):
        nonlocal process_count
        process_count += 1
        p = subprocess.Popen([str(binary), json.dumps(dict(op="worker", owner=owner))], env=cluster.env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        children.append(p)
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            require(selector.select(timeout=15), "Worker claim timeout")
            claimed = json.loads(p.stdout.readline())["claimed"]
        return p, claimed

    def expired(cluster):
        deadline = time.monotonic() + 12
        while cluster.sql("SELECT deadline<=clock_timestamp() FROM lease") != "t":
            require(time.monotonic() < deadline, "Lease did not expire")
            time.sleep(0.04)

    try:
        with Cluster() as source, Cluster() as destination:
            libraries = {"postgres_major": 18, "server_version_num": source.sql("SHOW server_version_num"),
                         "fsync": source.sql("SHOW fsync"), "synchronous_commit": source.sql("SHOW synchronous_commit"),
                         "full_page_writes": source.sql("SHOW full_page_writes")}
            call(source, dict(op="init"))
            base = dict(op="read", credential="fixture-reader-a", tenant="a", id="session", reader=1)
            r = call(source, base)
            require(r["payload"] == dict(next="review", spent=3), "Old snapshot changed")
            row("old-session", version=r["version"], spent=r["payload"]["spent"])
            call(source, dict(base, reader=2))
            row("new-reader-old-session", readable=True)
            call(source, dict(base, credential="admin", role="approver"), "Unauthenticated")
            row("untrusted-identity", error="Unauthenticated")
            call(source, dict(base, tenant="b"), "TenantDenied")
            row("tenant-isolation", error="TenantDenied", private_spent=source.sql("SELECT payload->>'spent' FROM sessions WHERE tenant='b'"))
            approval = dict(op="approve", credential="fixture-reader-a", tenant="a", id="action", revision=7)
            call(source, approval, "RoleDenied")
            require(source.sql("SELECT approved FROM approvals") == "f", "Denied actor changed approval")
            row("approval-role", error="RoleDenied", approved=False)
            call(source, dict(approval, credential="fixture-approver-b"), "TenantDenied")
            row("approval-tenant", error="TenantDenied")
            approval["credential"] = "fixture-approver-a"
            call(source, dict(approval, revision=6), "ApprovalConflict")
            row("approval-revision", error="ApprovalConflict")
            call(source, approval)
            call(source, approval, "ApprovalConflict")
            require(source.sql("SELECT count(*) FROM approvals WHERE approved") == "1", "Duplicate approval")
            row("approval-once", accepted=1, replay_error="ApprovalConflict")

            require(not call(source, dict(op="health"))["ready"], "Schema v1 ready")
            source.sql("UPDATE sessions SET version=99 WHERE tenant='a'")
            call(source, dict(op="migrate"), "UnmigratableSession")
            require(source.sql("SELECT schema FROM settings") == "1", "Unsupported migration changed schema")
            source.sql("UPDATE sessions SET version=1 WHERE tenant='a'")
            row("migration-unsupported", error="UnmigratableSession", schema=1)
            call(source, dict(op="migrate", fail=True), "MigrationInjected")
            require(source.sql("SELECT schema FROM settings") == "1", "Schema rollback failed")
            require(source.sql("SELECT count(*) FROM information_schema.columns WHERE table_name='sessions' AND column_name='workflow'") == "0", "DDL rollback failed")
            require(source.sql("SELECT count(*) FROM sessions WHERE version=1 AND NOT payload ? 'status'") == "2", "Data rollback failed")
            row("migration-rollback", schema=1, old_sessions=2, workflow_columns=0)
            call(source, dict(op="migrate"))
            r = call(source, dict(base, reader=2))
            require(r == dict(version=2, payload=dict(next="review", spent=3, status="paused")), "Migration lost state")
            require(source.sql("SELECT count(*) FROM sessions WHERE version=2 AND workflow='review-v2'") == "2", "Partial migration")
            row("migration-forward", schema=2, migrated_sessions=2, spent=r["payload"]["spent"], status=r["payload"]["status"])
            require(call(source, dict(op="migrate"))["replayed"], "Migration not idempotent")
            row("migration-replay", replayed=True)
            call(source, base, "IncompatibleSnapshot")
            row("old-reader-rejected", error="IncompatibleSnapshot", saved_version=2)
            source.sql("UPDATE sessions SET version=99 WHERE tenant='a'")
            call(source, dict(base, reader=2), "IncompatibleSnapshot")
            source.sql("UPDATE sessions SET version=2 WHERE tenant='a'")
            row("future-version", error="IncompatibleSnapshot")

            require(not call(source, dict(op="health"))["ready"], "Unapproved ready")
            call(source, dict(op="admit", id="unapproved"), "NotReady")
            source.sql("UPDATE settings SET approved=true")
            for change, reset in [("release='unknown'", "release='p04-v2'"), ("draining=true", "draining=false"), ("recovery=true", "recovery=false")]:
                source.sql("UPDATE settings SET " + change)
                require(not call(source, dict(op="health"))["ready"], "Gate ignored: " + change)
                call(source, dict(op="admit", id="gated"), "NotReady")
                source.sql("UPDATE settings SET " + reset)
            require(call(source, dict(op="health"))["ready"], "Healthy release unready")
            row("readiness-gates", schema=True, operator_approval=True, release=True, drain=True, recovery=True)

            def submit(i):
                before = time.perf_counter_ns()
                # Concurrent subprocess calls are counted after joining, not via shared mutation.
                p = subprocess.run([str(binary), json.dumps(dict(op="admit", id="load-" + str(i)))],
                                   env=source.env, capture_output=True, text=True, timeout=20)
                r = json.loads(p.stdout)
                require(not p.stderr and ((p.returncode == 0 and r == {"admitted": True}) or
                        (p.returncode == 1 and r == {"error": "Overloaded"})), "Unexpected load result")
                return i, r, (time.perf_counter_ns() - before) / 1e6

            with ThreadPoolExecutor(max_workers=12) as pool:
                burst = list(pool.map(submit, range(12)))
            process_count += len(burst)
            accepted = [i for i, r, _ in burst if r.get("admitted")]
            saturated = call(source, dict(op="health"))
            require(len(accepted) == 4 and saturated == dict(live=True, ready=True, active=4, capacity=4,
                    admitted=4, rejected=8, finished=0), "Admission counters differ")
            require(source.sql("SELECT count(*) FROM jobs WHERE state='running'") == "4", "SQL admission mismatch")
            row("load-burst", attempted=12, accepted=4, rejected=8, active=4, capacity=4, ready=True)
            call(source, dict(op="admit", id="load-" + str(accepted[0])), "DuplicateRequest")
            row("duplicate-admission", error="DuplicateRequest", active=4)
            source.sql("UPDATE settings SET draining=true")
            call(source, dict(op="admit", id="during-drain"), "NotReady")
            for i in accepted:
                call(source, dict(op="finish", id="load-" + str(i)))
            call(source, dict(op="finish", id="load-" + str(accepted[0])), "AlreadyFinishedOrMissing")
            h = call(source, dict(op="health"))
            require(h["active"] == 0 and h["finished"] == 4 and not h["ready"], "Drain accounting failed")
            row("drain-and-finish", active=0, finished=4, rejected_new=True, duplicate_finish_rejected=True)
            source.sql("UPDATE settings SET draining=false")
            # Normalize nondeterministic winners; preserve exact logical records for backup comparison.
            source.sql("UPDATE jobs SET id='completed-' || rn FROM (SELECT id old,row_number() OVER(ORDER BY id) rn FROM jobs) n WHERE jobs.id=n.old")

            p, epoch = worker(source, "crashed")
            require(epoch == 1, "Wrong initial epoch")
            p.kill()
            p.communicate(timeout=10)
            require(p.returncode < 0 and source.sql("SELECT count(*) FROM results") == "0", "Worker death not observed")
            call(source, dict(op="claim", owner="too-early"), "LeaseBusy")
            expired(source)
            require(call(source, dict(op="claim", owner="replacement"))["epoch"] == 2, "No takeover")
            call(source, dict(op="commit", owner="replacement", epoch=2))
            require(source.sql("SELECT owner||':'||epoch FROM results") == "replacement:2", "Takeover result mismatch")
            row("worker-death-takeover", killed=True, early_error="LeaseBusy", takeover_epoch=2, committed=1)
            source.sql("TRUNCATE results; UPDATE lease SET owner=NULL,epoch=0,deadline=NULL")
            p, epoch = worker(source, "paused")
            expired(source)
            require(call(source, dict(op="claim", owner="replacement"))["epoch"] == epoch + 1, "No new fence")
            stdout, stderr = p.communicate(input="commit\n", timeout=15)
            require(p.returncode == 1 and not stderr and json.loads(stdout) == {"error": "Fenced"}, "Stale worker wrote")
            call(source, dict(op="commit", owner="replacement", epoch=2))
            require(source.sql("SELECT count(*) FROM results") == "1", "Duplicate result after fencing")
            row("stale-worker-fenced", stale_error="Fenced", takeover_epoch=2, committed=1)

            # Block admission and verify zero in-flight jobs before a logical snapshot.
            source.sql("UPDATE settings SET recovery=true")
            require(source.sql("SELECT active FROM settings") == "0", "Backup has active jobs")
            backup = output / "backup.dump"
            command([source.bin / "pg_dump", "--dbname", source.dsn, "--format=custom", "--no-owner", "--no-privileges", "--file", backup])
            baseline = source.sql("SELECT jsonb_build_object('sessions',(SELECT jsonb_agg(to_jsonb(s) ORDER BY tenant,id) FROM sessions s), 'jobs',(SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j), 'results',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM results r), 'approvals',(SELECT jsonb_agg(to_jsonb(a) ORDER BY tenant,id) FROM approvals a), 'settings',(SELECT to_jsonb(c) FROM settings c), 'lease',(SELECT to_jsonb(l) FROM lease l))")
            row("backup-snapshot", in_flight=0, sessions=2, completed_jobs=4, results=1, restore_blocked_by_default=True)
            source.sql("UPDATE settings SET recovery=false")
            call(source, dict(op="admit", id="after-backup"))
            call(source, dict(op="finish", id="after-backup"))
            require(source.sql("SELECT count(*) FROM jobs") == "5", "Post-backup commit absent")
            source.stop()
            h = call(source, dict(op="health"))
            require(h == dict(live=True, ready=False, reason="DatabaseUnavailable"), "Outage health invalid")
            row("database-outage", live=True, ready=False, reason="DatabaseUnavailable")

            damaged = output / "damaged.dump"
            damaged.write_bytes(b"not a postgres archive")
            failed = subprocess.run([str(destination.bin / "pg_restore"), "--dbname", destination.dsn, str(damaged)],
                                    capture_output=True, text=True, timeout=20)
            require(failed.returncode != 0, "Damaged backup accepted")
            require(call(destination, dict(op="health")) == dict(live=True, ready=False, reason="SchemaUnavailable"), "Empty restore marked ready")
            row("corrupt-backup", restore_failed=True, ready=False)
            start = time.perf_counter_ns()
            command([destination.bin / "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", "--dbname", destination.dsn, backup])
            restored = destination.sql("SELECT jsonb_build_object('sessions',(SELECT jsonb_agg(to_jsonb(s) ORDER BY tenant,id) FROM sessions s), 'jobs',(SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j), 'results',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM results r), 'approvals',(SELECT jsonb_agg(to_jsonb(a) ORDER BY tenant,id) FROM approvals a), 'settings',(SELECT to_jsonb(c) FROM settings c), 'lease',(SELECT to_jsonb(l) FROM lease l))")
            require(json.loads(restored) == json.loads(baseline), "Restored logical state differs")
            require(not call(destination, dict(op="health"))["ready"], "Restore skipped recovery gate")
            call(destination, dict(op="admit", id="before-reconcile"), "NotReady")
            require(destination.sql("SELECT count(*) FROM jobs WHERE id='after-backup'") == "0", "Unexpected post-backup record")
            destination.sql("UPDATE settings SET recovery=false")
            require(call(destination, dict(op="health"))["ready"], "Restore remains unready")
            recovery_ms = (time.perf_counter_ns() - start) / 1e6
            row("restore-separate-cluster", source_stopped=True, logical_state_equal=True, missing_post_backup_commits=1, ready_after_local_checks=True)
            latencies = sorted(x[2] for x in burst)
            measurements = dict(latency_definition="one subprocess start to admission reply; accepted and rejected combined; 12 concurrent submissions, no completion until all replies",
                                sample_count=12, p50_ms=round(latencies[math.ceil(.50 * 12)-1], 3),
                                p95_ms=round(latencies[math.ceil(.95 * 12)-1], 3),
                                restore_check_ms=round(recovery_ms, 3),
                                recovery_definition="pg_restore start to local SQL checks and readiness; excludes detection, provisioning, routing and remote reconciliation")
    finally:
        for p in children:
            if p.poll() is None:
                p.kill()
                p.communicate(timeout=5)
    result = dict(libraries=libraries, scenarios=rows, cli_processes=process_count)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "measurements.json").write_text(json.dumps(measurements, ensure_ascii=False, indent=2) + "\n")
    for r in rows:
        (output / (r["scenario"] + ".txt")).write_text(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print("P04: {} scenarios passed; {} independent Rust CLI processes; two private PostgreSQL clusters".format(len(rows), process_count))
    print(json.dumps(measurements, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(__file__).resolve().parent / "target/debug/learn-agent-p04")
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    run(args.binary.resolve(), args.output.resolve())
