"""Run P01 against a private PostgreSQL 18 cluster; no existing database is touched."""
import argparse
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def command(args, env=None):
    p = subprocess.run([str(x) for x in args], env=env, capture_output=True, text=True, timeout=60)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args[0], p.stdout, p.stderr))
    return p.stdout


class Cluster:
    def __init__(self):
        configured = os.environ.get("P01_PG_BIN")
        executable = shutil.which("postgres")
        self.bin = Path(configured) if configured else Path(executable).resolve().parent if executable else None
        require(self.bin is not None and all((self.bin / name).is_file() for name in ("postgres", "initdb", "pg_ctl", "psql")),
                "PostgreSQL 18 tools missing; set P01_PG_BIN to their bin directory")
        self.directory = Path(tempfile.mkdtemp(prefix="p01-pg-", dir="/tmp"))
        self.data, self.socket = self.directory / "data", self.directory / "sock"
        self.socket.mkdir(mode=0o700)
        self.started = False
        self.env = dict(os.environ, P01_DATABASE_URL="host={} port=55431 user=p01 dbname=postgres connect_timeout=3".format(self.socket))

    def start(self):
        command([self.bin / "pg_ctl", "-D", self.data, "-l", self.directory / "server.log", "-w", "-t", "15", "-o",
                 "-k {} -h '' -p 55431 -c fsync=on -c synchronous_commit=on -c full_page_writes=on".format(self.socket), "start"])
        self.started = True

    def stop(self, mode="fast"):
        command([self.bin / "pg_ctl", "-D", self.data, "-w", "-t", "15", "-m", mode, "stop"])
        self.started = False

    def sql(self, sql):
        return command([self.bin / "psql", self.env["P01_DATABASE_URL"], "-XAt", "-v", "ON_ERROR_STOP=1", "-c", sql]).strip()

    def __enter__(self):
        try:
            version = command([self.bin / "postgres", "--version"])
            require(" 18." in version, "This lab requires PostgreSQL major 18")
            command([self.bin / "initdb", "-D", self.data, "-U", "p01", "--auth-local=trust", "--auth-host=reject", "--no-locale", "-E", "UTF8"])
            self.start()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *unused):
        try:
            if self.started:
                self.stop()
        finally:
            # Only this invocation's freshly created data directory.
            shutil.rmtree(self.directory)


class Lab:
    def __init__(self, binary, cluster, root, name):
        self.binary, self.cluster, self.name = binary, cluster, name
        self.folder = Path(root) / name
        self.folder.mkdir()
        (self.folder / "README.md").write_text("启动：cargo run\n")
        (self.folder / "Cargo.toml").write_text('[package]\nname = "demo"\n')
        self.processes, self.steps, self.children = 0, [], []
        self.revision = 0

    def argv(self, value, fault=None):
        return [str(self.binary), compact(value)] + ([fault] if fault else [])

    def call(self, value, error=None, fault=None, exit_code=None, record=True):
        self.processes += 1
        p = subprocess.run(self.argv(value, fault), env=self.cluster.env, capture_output=True, text=True, timeout=15)
        require(not p.stderr, "Unexpected CLI stderr: " + p.stderr)
        if exit_code:
            require(p.returncode == exit_code and not p.stdout, "Wrong injected exit: " + p.stdout)
            result = {"status":"process_exit", "code":exit_code}
        else:
            result = json.loads(p.stdout)
            require(p.returncode == (1 if error else 0) and result.get("error") == error, "Wrong CLI result: " + p.stdout)
        if record:
            normalized = dict(value)
            if "workspace" in normalized:
                normalized["workspace"] = "WORKSPACE"
            self.steps.append({"command":normalized, "fault":fault, "result":result})
        return result

    def create(self, granularity="tool", profile="read_only"):
        return self.call({"op":"create", "id":self.name, "profile":profile, "granularity":granularity})

    def step(self, **kwargs):
        result = self.call({"op":"step", "id":self.name, "expected":self.revision, "workspace":str(self.folder)}, **kwargs)
        if result["status"] == "stepped":
            self.revision = result["revision"]
        return result

    def show(self, **kwargs):
        return self.call({"op":"show", "id":self.name}, **kwargs)

    def sync(self):
        result = self.show()
        self.revision = result["revision"]
        return result

    def history(self):
        return self.call({"op":"history", "id":self.name})["checkpoints"]

    def save(self, state, expected=0, save_id="save-a", **kwargs):
        return self.call({"op":"save", "id":self.name, "expected":expected, "save_id":save_id, "state":state}, **kwargs)

    def counts(self):
        raw = self.cluster.sql("SELECT (SELECT count(*) FROM p01_checkpoints WHERE session_id='{}'),revision FROM p01_sessions WHERE session_id='{}'".format(self.name,self.name))
        return tuple(map(int,raw.split("|")))

    def gate(self, value, fault="--gate"):
        self.processes += 1
        p = subprocess.Popen(self.argv(value,fault), env=self.cluster.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(p)
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout,selectors.EVENT_READ)
            require(selector.select(timeout=15),"Process checkpoint timeout")
            event = json.loads(p.stdout.readline())
        require(event == {"event":"updated_uncommitted" if fault=="--hold" else "ready"},"Wrong gate event")
        return p

    def finish(self, p, error=None, release=True):
        stdout,stderr=p.communicate(input="x" if release else None,timeout=15)
        result=json.loads(stdout)
        require(not stderr and p.returncode==(1 if error else 0) and result.get("error")==error,"Wrong resumed process: "+stdout+stderr)
        return result

    def cleanup(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


def scenarios(binary, cluster, folder):
    names=["normal", "tool-granularity", "batch-granularity", "resume-next-tool", "model-reply-window",
           "tool-result-window", "batch-first-tool-window", "external-effect-window", "save-failure", "exit-before-commit",
           "exit-after-commit", "save-identity", "revision-conflict", "race-three", "lock-and-reader", "database-restart",
           "server-crash-uncommitted", "format-version", "workflow-version", "corrupt-state", "invalid-budget",
           "message-pairing", "tool-failure", "duplicate-session", "missing-session"]
    rows=[]
    for name in names:
        lab=Lab(binary,cluster,folder,name)
        metrics={}
        try:
            if name!="missing-session":
                initial=lab.create("batch" if name in ("batch-granularity","batch-first-tool-window") else "tool",
                                   "effect" if name=="external-effect-window" else "read_only")["state"]
            if name=="normal":
                for _ in range(4):
                    result=lab.step()
                require(result["state"]["phase"]=="done" and lab.revision==8,"Did not complete")
                state=lab.show()["state"]
                require([m.get("call_id") for m in state["messages"] if m["role"]=="tool"]==["read-1","read-2"],"Bad message pairing")
                history=lab.history()
                require([h["revision"] for h in history]==list(range(9)),"Missing intermediate checkpoints")
                require(lab.counts()==(9,8),"History and latest differ")
                require(lab.step()["revision"]==8,"Done state executed again")
                metrics={"revision":8,"checkpoints":9,"model_turns":2,"tool_dispatches":2,"messages":5}
            elif name in ("tool-granularity","batch-granularity"):
                lab.step(); result=lab.step()
                state=result["state"]
                cursor=1 if name=="tool-granularity" else 2
                require(state["cursor"]==cursor and state["tool_dispatches"]==cursor,"Wrong tool boundary")
                metrics={"after_tool_step_cursor":cursor,"tool_results":sum(m["role"]=="tool" for m in state["messages"]),"revision":4}
            elif name=="resume-next-tool":
                lab.step(); lab.step()
                (lab.folder/"README.md").unlink()
                result=lab.step()
                require(result["state"]["cursor"]==2,"Did not resume second tool")
                result=lab.step()
                require(result["state"]["phase"]=="done","Saved first result lost")
                metrics={"first_file_removed":True,"completed":True,"tool_dispatches":2}
            elif name=="model-reply-window":
                lab.step(fault="--exit-after-model",exit_code=76)
                snapshot=lab.sync()
                require(snapshot["state"]["phase"]=="model_in_flight" and len(snapshot["state"]["messages"])==1,"Model reply persisted too early")
                result=lab.step()
                require(result["state"]["phase"]=="reconcile" and result["state"]["model_turns"]==1,"Model automatically replayed")
                metrics={"phase":"reconcile","uncertain":"model","model_turns":1}
            elif name in ("tool-result-window","batch-first-tool-window","external-effect-window","save-failure","tool-failure"):
                lab.step()
                if name not in ("batch-first-tool-window",):
                    lab.step()
                if name=="tool-failure":
                    (lab.folder/"Cargo.toml").unlink()
                    lab.step(error="tool_failed")
                elif name=="save-failure":
                    lab.step(fault="--fail-before-commit",error="injected_failure")
                else:
                    lab.step(fault="--exit-after-action",exit_code=75)
                snapshot=lab.sync(); state=snapshot["state"]
                cursor=0 if name=="batch-first-tool-window" else 1
                require(state["phase"]=="tool_in_flight" and state["cursor"]==cursor and state["tool_dispatches"]==2,"In-flight state or budget lost")
                require(sum(m["role"]=="tool" for m in state["messages"])==cursor,"Unsaved result leaked into DB")
                result=lab.step()
                require(result["state"]["phase"]=="reconcile" and result["state"]["tool_dispatches"]==2,"Unsafe replay or reset budget")
                metrics={"phase":"reconcile","saved_tool_results":cursor,"reserved_dispatches":2}
                if name=="external-effect-window":
                    before=(lab.folder/"audit.log").read_bytes()
                    require(before==b"report delivered\n","External action missing or duplicated")
                    lab.step()
                    require((lab.folder/"audit.log").read_bytes()==before,"Reconciliation repeated action")
                    metrics.update({"external_log_lines":1,"saved_append_results":0})
            elif name in ("exit-before-commit","exit-after-commit"):
                code=73 if name=="exit-before-commit" else 74
                lab.save(initial,fault="--"+name,exit_code=code)
                snapshot=lab.sync()
                revision=0 if code==73 else 1
                require(snapshot["revision"]==revision and lab.counts()==(revision+1,revision),"Wrong commit boundary")
                reply=lab.save(initial)
                require(reply["revision"]==1 and reply["replayed"]==(code==74),"Retry saved twice")
                require(lab.counts()==(2,1),"Retry duplicated history")
                metrics={"exit_code":code,"revision_after_exit":revision,"retry_replayed":reply["replayed"],"final_checkpoints":2}
            elif name=="save-identity":
                lab.save(initial)
                require(lab.save(initial)["replayed"],"Same identity not replayed")
                different=dict(initial,granularity="batch")
                lab.save(different,error="save_identity_conflict")
                lab.save(initial,expected=1,save_id="save-b")
                require(lab.save(initial)["revision"]==1,"Old receipt should reference original revision")
                require(lab.counts()==(3,2),"History changed on receipt retry")
                metrics={"same_identity_receipt":1,"current_revision":2,"checkpoints":3}
            elif name=="revision-conflict":
                lab.save(initial)
                lab.save(initial,save_id="save-b",error="revision_conflict")
                lab.call({"op":"step","id":name,"expected":0,"workspace":str(lab.folder)},error="revision_conflict")
                require(lab.counts()==(2,1),"Stale writer overwrote state")
            elif name=="race-three":
                workers=[lab.gate({"op":"save","id":name,"expected":0,"save_id":"race-"+str(i),"state":initial}) for i in range(3)]
                require(len({p.pid for p in workers})==3 and all(p.poll() is None for p in workers),"Race processes not live")
                for p in workers:
                    p.stdin.write("x");p.stdin.flush()
                results=[]
                for p in workers:
                    stdout,stderr=p.communicate(timeout=15)
                    result=json.loads(stdout)
                    require(not stderr and (p.returncode==0 and result["status"]=="saved" or p.returncode==1 and result.get("error") in ("store_busy","revision_conflict")),"Bad race reply")
                    results.append(result)
                require(sum(r["status"]=="saved" for r in results)==1 and lab.counts()==(2,1),"Race did not have one winner")
                metrics={"live_writers":3,"committed_writers":1,"busy_or_conflict":2,"checkpoints":2}
            elif name=="lock-and-reader":
                held=lab.gate({"op":"save","id":name,"expected":0,"save_id":"held","state":initial},"--hold")
                require(lab.show()["revision"]==0 and lab.counts()==(1,0),"Reader saw uncommitted data")
                lab.save(initial,save_id="contender",error="store_busy")
                reply=lab.finish(held)
                require(reply["revision"]==1 and lab.counts()==(2,1),"Held write lost")
                metrics={"reader_revision_during_write":0,"revision_after_commit":1}
            elif name=="database-restart":
                lab.step(); lab.step()
                before=lab.show()
                cluster.stop("immediate");cluster.start()
                require(lab.show()==before,"Committed data lost after server restart")
                lab.step(); result=lab.step()
                require(result["state"]["phase"]=="done","Did not resume after server recovery")
                metrics={"immediate_stop":True,"resumed_cursor":1,"final_revision":8}
            elif name=="server-crash-uncommitted":
                held=lab.gate({"op":"save","id":name,"expected":0,"save_id":"held","state":initial},"--hold")
                cluster.stop("immediate");cluster.start()
                lab.finish(held,error="store_unavailable")
                require(lab.show()["revision"]==0 and lab.counts()==(1,0),"Server retained uncommitted row")
                lab.save(initial)
                metrics={"revision_after_recovery":0,"checkpoints_after_retry":2}
            elif name in ("format-version","workflow-version","corrupt-state"):
                assignment={"format-version":"format_version=2","workflow-version":"workflow_version='p01-v2'",
                            "corrupt-state":"state='{}'::jsonb"}[name]
                cluster.sql("UPDATE p01_sessions SET {} WHERE session_id='{}'".format(assignment,name))
                expected={"format-version":"format_version","workflow-version":"workflow_version","corrupt-state":"corrupt_state"}[name]
                lab.show(error=expected)
                lab.call({"op":"step","id":name,"expected":0,"workspace":str(lab.folder)},error=expected)
                require(lab.counts()==(1,0),"Unsupported state mutated")
            elif name in ("invalid-budget","message-pairing"):
                invalid=json.loads(json.dumps(initial))
                if name=="invalid-budget":
                    invalid["model_turns"]=3; code="invalid_budget"
                else:
                    invalid["messages"].append({"role":"tool","call_id":"orphan","content":"bad"});code="message_pairing"
                lab.save(invalid,error=code)
                require(lab.show()["state"]==initial and lab.counts()==(1,0),"Invalid state accepted")
            elif name=="duplicate-session":
                lab.call({"op":"create","id":name,"profile":"read_only","granularity":"tool"},error="duplicate_session")
                require(lab.counts()==(1,0),"Duplicate created partial history")
            elif name=="missing-session":
                lab.show(error="session_missing")
            else:
                raise ValueError(name)
            summary={"scenario":name,"processes":lab.processes,"metrics":metrics,"passed":True}
            rows.append(dict(summary,steps=lab.steps))
        finally:
            lab.cleanup()
    return rows


def run(binary, output):
    with tempfile.TemporaryDirectory(prefix="p01-work-") as folder, Cluster() as cluster:
        require(int(cluster.sql("SHOW server_version_num"))//10000==18,"Wrong server major")
        command([binary,compact({"op":"init"})],cluster.env)
        versions=json.loads(command([binary,compact({"op":"versions"})],cluster.env))
        require(all(versions[key]=="on" for key in ("fsync","synchronous_commit","full_page_writes")),"Durability settings disabled")
        rows=scenarios(binary,cluster,folder)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/"results.json").write_text(json.dumps({"libraries":versions,"scenarios":rows},ensure_ascii=False,indent=2)+"\n")
    for row in rows:
        # This is an assertion summary, not raw Rust stdout. Full replies are in results.json.
        summary={key:value for key,value in row.items() if key!="steps"}
        (output/(row["scenario"]+".txt")).write_text("验证器核对摘要（真实 PostgreSQL 与独立 CLI 进程）\n"+json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("P01: {} scenarios / {} Rust CLI processes; private PostgreSQL stopped and removed".format(len(rows),sum(row["processes"] for row in rows)))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.binary.resolve(),args.output)
