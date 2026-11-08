"""R17: atomic claims, lease fencing, process takeover and local business replay."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import sqlite3
import subprocess
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/public/learn-agent-rust/code/autonomous-workers"
CHAPTER = ROOT / "docs/learn-agent-rust/autonomous-workers.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r17-results.json"
OUT = ROOT / "docs/public/learn-agent-rust/outputs"
ARCHIVE = ROOT / "docs/public/learn-agent-rust/autonomous-workers-lab.zip"
FILES = ["Cargo.toml", "Cargo.lock", ".gitignore", "README.md", "src/main.rs", "src/queue.rs", "src/effects.rs", "src/tests.rs"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def command(args, cwd, env=None):
    p = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    require(p.returncode == 0, "Command failed: {}\n{}\n{}".format(args, p.stdout, p.stderr))
    return p.stdout


class Lab:
    def __init__(self, binary, folder):
        self.binary, self.folder = binary, Path(folder)
        self.db = self.folder / "tasks.db"
        self.ledger = self.folder / "business.db"
        self.processes, self.steps, self.lines, self.children = 0, [], [], []

    def argv(self, value, fault=None, ledger=False):
        return [str(self.binary), str(self.ledger if ledger else self.db), encode(value)] + ([fault] if fault else [])

    def record(self, label, result):
        self.lines.extend([label, encode(result)])
        self.steps.append(result)

    def call(self, value, error=None, fault=None, exit_code=None, ledger=False, record=True):
        self.processes += 1
        p = subprocess.run(self.argv(value, fault, ledger), cwd=self.folder, capture_output=True, text=True, timeout=15)
        require(not p.stderr, "Unexpected stderr: " + p.stderr)
        if exit_code:
            require(p.returncode == exit_code and not p.stdout, "Wrong injected exit")
            result = {"status":"process_exit", "code":exit_code}
        else:
            require(p.returncode == (1 if error else 0), "Wrong exit: " + p.stdout)
            result = json.loads(p.stdout)
            require(result.get("error") == error, "Wrong error: " + p.stdout)
        if record:
            normalized = dict(value)
            if "ledger" in normalized:
                normalized["ledger"] = "BUSINESS"
            label = ("BUSINESS " if ledger else "TASKS ") + encode(normalized) + (" " + fault if fault else "")
            self.record(label, result)
        return result

    def seed(self, max_claims=3):
        self.call({"op":"init"})
        self.call({"op":"add", "id":"report", "title":"整理日报", "max_claims":max_claims})

    def claim(self, owner="worker-a", now=100, ttl=10, **kwargs):
        return self.call({"op":"claim", "owner":owner, "now":now, "ttl":ttl}, **kwargs)

    def renew(self, owner="worker-a", token=1, now=105, ttl=10, **kwargs):
        return self.call({"op":"renew", "id":"report", "owner":owner, "token":token, "now":now, "ttl":ttl}, **kwargs)

    def complete(self, owner="worker-a", token=1, now=109, result="已核对", **kwargs):
        return self.call({"op":"complete", "id":"report", "owner":owner, "token":token, "now":now, "result":result}, **kwargs)

    def show(self):
        return self.call({"op":"show"})

    def sql(self, query, params=()):
        with sqlite3.connect(self.db, timeout=0) as db:
            return db.execute(query, params).fetchall()

    def state(self):
        return {"meta":self.sql("SELECT * FROM meta"), "tasks":self.sql("SELECT * FROM tasks ORDER BY id")}

    def gate(self, value, fault="--gate"):
        self.processes += 1
        p = subprocess.Popen(self.argv(value, fault), cwd=self.folder, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(p)
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            require(selector.select(timeout=15), "Checkpoint timeout")
            event = json.loads(p.stdout.readline())
        require(event == {"event":"updated_uncommitted" if fault=="--hold" else "ready"}, "Wrong checkpoint")
        return p

    def finish(self, p, error=None, release=True, record=True):
        stdout, stderr = p.communicate(input="x" if release else None, timeout=15)
        result = json.loads(stdout)
        require(not stderr and p.returncode == (1 if error else 0) and result.get("error")==error, "Bad resumed process: " + stdout + stderr)
        if record:
            self.record("验证器：释放已到达检查点的独立进程", result)
        return result

    def cleanup(self):
        for p in self.children:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=5)


def scenarios(binary, directory):
    names = ["normal", "restart-takeover", "renewal", "expiry-boundary", "late-renewal", "stale-live-process",
             "same-name", "claim-budget", "selection", "empty", "clock-regression", "invalid-input",
             "duplicate-id", "task-limit", "rollback", "exit-before-commit", "exit-after-commit",
             "held-write-lock", "race-four", "effect-replay", "effect-dedupe", "system-clock",
             "corrupt-store", "schema-version", "missing-store"]
    rows, outputs = [], {}
    for name in names:
        folder = Path(directory) / name
        folder.mkdir()
        lab = Lab(binary, folder)
        metrics = {}
        try:
            if name not in ("empty", "corrupt-store", "schema-version", "missing-store"):
                lab.seed(max_claims=2 if name=="claim-budget" else 3)
            if name == "normal":
                lab.claim(); lab.complete()
                require(lab.show()["tasks"][0]["state"]=="done", "Not completed")
                require(lab.claim(now=110)["status"]=="empty", "Completed task reclaimed")
                lab.complete(now=110, error="lease_rejected")
            elif name == "restart-takeover":
                lab.claim()
                # Every invocation exits; the next owner is a NEW process on the same file.
                require(lab.claim("worker-b",109)["status"]=="empty", "Early takeover")
                require(lab.claim("worker-b",110)["task"]["token"]==2, "No new generation")
                lab.complete("worker-b",2,111)
                metrics = {"first_token":1,"takeover_token":2,"first_deadline":110,"takeover_now":110}
            elif name == "renewal":
                lab.claim(); renewed=lab.renew()
                require(renewed["task"]["token"]==1 and renewed["task"]["lease_until"]==115,"Wrong renewal")
                require(lab.claim("worker-b",110)["status"]=="empty","Renewal ignored")
                require(lab.claim("worker-b",115)["task"]["token"]==2,"Renewed expiry wrong")
            elif name == "expiry-boundary":
                lab.claim()
                before=lab.state()
                lab.complete(now=110,error="lease_rejected")
                require(lab.state()==before,"Rejected expiry mutated state")
                lab.claim("worker-b",110)
            elif name == "late-renewal":
                lab.claim(); before=lab.state()
                lab.renew(now=110,error="lease_rejected")
                lab.renew(now=105,ttl=5,error="lease_rejected")
                lab.renew(owner="other",now=105,error="lease_rejected")
                require(lab.state()==before,"Rejected renewal mutated state")
            elif name == "stale-live-process":
                lab.claim()
                old=lab.gate({"op":"complete","id":"report","owner":"worker-a","token":1,"now":111,"result":"旧执行者恢复"})
                lab.record("验证器：旧完成进程已就绪，尚未进入写事务", {"status":"checkpoint","old_process_alive":old.poll() is None})
                lab.claim("worker-b",110)
                before=lab.state()
                lab.finish(old,error="lease_rejected")
                require(lab.state()==before,"Old process overwrote new owner")
                lab.complete("worker-b",2,111)
                metrics={"old_process_rejected":True,"final_token":2}
            elif name == "same-name":
                lab.claim(); lab.claim("worker-a",110)
                before=lab.state()
                lab.complete(token=1,now=111,error="lease_rejected")
                lab.renew(token=1,now=111,error="lease_rejected")
                require(lab.state()==before,"Same-name stale token accepted")
                lab.complete(token=2,now=111)
            elif name == "claim-budget":
                lab.claim(); lab.claim("worker-b",110)
                require(lab.claim("worker-c",120)["status"]=="empty","Unbounded attempts")
                task=lab.show()["tasks"][0]
                require(task["state"]=="running" and task["token"]==task["max_claims"]==2,"Lost exhausted evidence")
            elif name == "selection":
                lab.call({"op":"add","id":"aaa","title":"先读取说明","max_claims":1})
                require(lab.claim()["task"]["id"]=="aaa","Selection not ordered")
                require(lab.claim("worker-b")["task"]["id"]=="report","Active task selected twice")
                require(lab.claim("worker-c")["status"]=="empty","Extra task")
            elif name == "empty":
                lab.call({"op":"init"}); require(lab.claim()["status"]=="empty","Empty board claimed")
                require(lab.show()["last_now"]==100,"Empty scan clock not committed")
            elif name == "clock-regression":
                lab.claim(); before=lab.state()
                lab.claim(now=99,error="clock_regression")
                lab.renew(now=99,error="clock_regression")
                require(lab.state()==before,"Clock regressed")
                lab.renew(now=105)
            elif name == "invalid-input":
                before=lab.state()
                for value,error in [({"op":"show","extra":1},"invalid_command"),
                    ({"op":"claim","owner":"../a","now":100,"ttl":10},"invalid_owner"),
                    ({"op":"claim","owner":"a","now":100,"ttl":0},"invalid_ttl"),
                    ({"op":"claim","owner":"a","now":100,"ttl":3601},"invalid_ttl"),
                    ({"op":"claim","owner":"a","now":-1,"ttl":10},"invalid_time"),
                    ({"op":"claim","owner":"a","now":4000000000,"ttl":1},"time_limit"),
                    ({"op":"add","id":"new","title":" ","max_claims":1},"invalid_task")]:
                    lab.call(value,error=error)
                require(lab.state()==before,"Invalid command mutated state")
                lab.claim(); before=lab.state()
                lab.complete(result="中"*171,error="invalid_result")
                lab.complete(token=0,error="invalid_credential")
                lab.complete(owner="other",error="lease_rejected")
                require(lab.state()==before,"Invalid completion mutated state")
            elif name == "duplicate-id":
                lab.claim(); lab.complete(); before=lab.state()
                lab.call({"op":"add","id":"report","title":"另一个业务","max_claims":3},error="duplicate_id")
                require(lab.state()==before,"Task identity reused")
            elif name == "task-limit":
                for i in range(31):
                    lab.call({"op":"add","id":"t"+str(i),"title":"task","max_claims":1})
                before=lab.state()
                lab.call({"op":"add","id":"overflow","title":"task","max_claims":1},error="task_limit")
                require(lab.state()==before and len(before["tasks"])==32,"Task bound failed")
            elif name == "rollback":
                before=lab.state()
                lab.claim(fault="--fail-before-commit",error="injected_failure")
                require(lab.state()==before,"Normal error did not roll back")
                require(lab.claim()["task"]["token"]==1,"Rollback consumed token")
            elif name == "exit-before-commit":
                before=lab.state()
                lab.claim(fault="--exit-before-commit",exit_code=73)
                require(lab.state()==before,"Process exit did not roll back")
                lab.show(); require(lab.claim()["task"]["token"]==1,"Exit consumed token")
            elif name == "exit-after-commit":
                lab.claim(fault="--exit-after-commit",exit_code=74)
                snapshot=lab.show()
                require(snapshot["tasks"][0]["token"]==1 and snapshot["last_now"]==100,"Committed receipt lost")
                require(lab.claim("worker-b",100)["status"]=="empty","Committed lease ignored")
                require(lab.claim("worker-b",110)["task"]["token"]==2,"No eventual takeover")
            elif name == "held-write-lock":
                p=lab.gate({"op":"claim","owner":"worker-a","now":100,"ttl":10},"--hold")
                snapshot=lab.show()
                require(snapshot["tasks"][0]["state"]=="pending" and snapshot["last_now"]==0,"Dirty read")
                lab.claim("worker-b",error="store_busy")
                lab.finish(p)
                require(lab.claim("worker-b")["status"]=="empty","Concurrent second owner")
            elif name == "race-four":
                workers=[lab.gate({"op":"claim","owner":"worker-"+str(i),"now":100,"ttl":10}) for i in range(4)]
                require(len({p.pid for p in workers})==4 and all(p.poll() is None for p in workers),"Not four live processes")
                for p in workers:
                    p.stdin.write("x"); p.stdin.flush()
                results=[]
                for p in workers:
                    stdout,stderr=p.communicate(timeout=15)
                    result=json.loads(stdout)
                    require(not stderr,"Race stderr")
                    require((p.returncode==0 and result["status"] in ("claimed","empty")) or
                            (p.returncode==1 and result.get("error")=="store_busy"),"Bad race result")
                    results.append(result)
                winners=[i for i,r in enumerate(results) if r["status"]=="claimed"]
                require(len(winners)==1,"Not exactly one winner")
                owner,token=lab.sql("SELECT owner,token FROM tasks")[0]
                require(owner=="worker-"+str(winners[0]) and token==1,"Race state differs from winner")
                for i in range(4):
                    require(lab.claim("worker-"+str(i),record=False)["status"]=="empty","Retry claimed active task")
                metrics={"live_processes":4,"first_round_claimed":1,"first_round_other_empty_or_busy":3,"retry_empty":4,"persisted_token":1}
                lab.record("验证器摘要：四个真实进程均到达门闩后放行；胜者名字与 busy/empty 分布由调度决定",dict(status="race_verified",**metrics))
            elif name in ("effect-replay","effect-dedupe"):
                dedupe=name=="effect-dedupe"
                def work(owner, now, **kwargs):
                    return lab.call({"op":"work","owner":owner,"now":now,"ttl":10,"ledger":str(lab.ledger),"dedupe":dedupe},**kwargs)
                work("worker-a",100,fault="--exit-after-effect",exit_code=75)
                require(lab.show()["tasks"][0]["state"]=="running","Crash marked task complete")
                first=lab.call({"op":"effects"},ledger=True)
                require(len(first["reports"])==1,"No committed external effect")
                result=work("worker-b",110)
                require(result["claim"]["task"]["token"]==2 and result["completion"]["task"]["state"]=="done","Replay worker failed")
                effects=lab.call({"op":"effects"},ledger=True)
                reports=1 if dedupe else 2
                require(len(effects["calls"])==2 and len(effects["reports"])==reports,"Replay count wrong")
                with sqlite3.connect(lab.ledger) as db:
                    require(db.execute("SELECT count(*) FROM reports").fetchone()[0]==reports,"Business file disagrees")
                metrics={"calls":2,"reports":reports,"queue_token":2,"operation":"report:report"}
            elif name == "system-clock":
                # Omit now: verify the actual clock, retaining deterministic assertions only.
                start=int(time.time())
                result=lab.call({"op":"claim","owner":"worker-a","ttl":60},record=False)
                end=int(time.time())
                require(start<=result["now"]<=end,"Did not use actual clock")
                require(result["task"]["lease_until"]==result["now"]+60,"Real-clock deadline wrong")
                result2=lab.call({"op":"complete","id":"report","owner":"worker-a","token":1,"result":"已核对"},record=False)
                require(result["now"]<=result2["now"]<=int(time.time()),"Real completion clock wrong")
                require(lab.sql("SELECT state FROM tasks")==[("done",)],"Real-clock completion lost")
                metrics={"within_host_clock_bounds":True,"lease_seconds":60,"completed":True}
                lab.record("验证器摘要：省略 now，逐次核对实际 Unix 秒与主机调用前后边界",dict(status="system_clock_verified",**metrics))
            elif name == "corrupt-store":
                lab.db.write_bytes(b"invalid sqlite file")
                before=lab.db.read_bytes()
                lab.call({"op":"show"},error="store_error")
                require(lab.db.read_bytes()==before,"Corrupt store overwritten")
            elif name == "schema-version":
                lab.call({"op":"init"})
                with sqlite3.connect(lab.db) as db:
                    db.execute("PRAGMA user_version=9")
                lab.call({"op":"show"},error="schema_version")
            elif name == "missing-store":
                lab.call({"op":"show"},error="store_error")
                require(not lab.db.exists(),"Read created missing store")
            else:
                raise ValueError(name)
        finally:
            lab.cleanup()
        output=("\n".join(lab.lines)+"\n").encode()
        outputs[name]=output
        rows.append({"name":name,"processes":lab.processes,"metrics":metrics,"steps":lab.steps,
                     "stdout_sha256":hashlib.sha256(output).hexdigest()})
    return rows,outputs


def package_bytes(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,content in sorted(files.items()):
            info=zipfile.ZipInfo("autonomous-workers-lab/"+name,(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,content)
    return stream.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    files={name:(SOURCE/name).read_bytes() for name in FILES}
    artifacts={}
    with tempfile.TemporaryDirectory(prefix="agent-r17-") as directory:
        folder=Path(directory)/"source"
        for name,content in files.items():
            path=folder/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
        env=dict(os.environ,CARGO_TARGET_DIR=str(Path(directory)/"target"),RUSTFLAGS="-D warnings")
        command(["cargo","fmt","--","--check"],folder,env)
        tests=command(["cargo","test","--locked"],folder,env)
        require("12 passed; 0 failed" in tests,"Unexpected test count")
        command(["cargo","clippy","--locked","--all-targets","--","-D","warnings"],folder,env)
        command(["cargo","build","--locked"],folder,env)
        binary=Path(env["CARGO_TARGET_DIR"])/"debug/learn-agent-r17"
        runs=Path(directory)/"runs"
        runs.mkdir()
        rows,outputs=scenarios(binary,runs)
        evidence={"scope":"R17 real single-host SQLite and CLI processes; fixture seconds plus actual system-clock smoke test; local separate business DB; no model, multi-host service or R12/R16 integration",
                  "files_sha256":{name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
                  "rustc":command(["rustc","--version"],folder).strip(),
                  "host":command(["rustc","-vV"],folder).split("host: ")[1].splitlines()[0],
                  "libraries":json.loads(command([binary,"versions"],folder)),"contract_tests_passed":12,"scenarios":rows}
        if args.check and DATA.exists():
            recorded=json.loads(DATA.read_text())
            for key in ("rustc","host"):
                evidence[key]=recorded[key]
        serialized=(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n").encode()
        artifacts[DATA]=serialized
        archive=package_bytes(dict(files,**{"outputs/"+name+".txt":content for name,content in outputs.items()},**{"evidence.json":serialized}))
        artifacts[ARCHIVE]=archive
        artifacts.update({OUT/("r17-"+name+".txt"):content for name,content in outputs.items()})
        extracted=Path(directory)/"download"
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            z.extractall(extracted)
        download_env=dict(env,CARGO_TARGET_DIR=str(Path(directory)/"download-target"))
        command(["cargo","build","--locked","--offline"],extracted/"autonomous-workers-lab",download_env)
        again=Path(directory)/"again"
        again.mkdir()
        repeated_rows,repeated_outputs=scenarios(Path(download_env["CARGO_TARGET_DIR"])/"debug/learn-agent-r17",again)
        require(repeated_rows==rows and repeated_outputs==outputs,"Extracted download behavior differs")
    chapter=CHAPTER.read_text()
    start,end="<!-- r17-results:start -->","<!-- r17-results:end -->"
    require(chapter.count(start)==1 and chapter.count(end)==1,"Missing result table markers")
    table="| 场景 | 独立 CLI 进程 | 拒绝 / 退出 / 核对摘要 |\n| --- | --- | --- |\n"
    for row in rows:
        results=sorted({step.get("error") or ("exit="+str(step["code"]) if step["status"]=="process_exit" else
                       step["status"] if step["status"].endswith("verified") else "") for step in row["steps"]}-{ "" })
        table+="| `{}` | {} | {} |\n".format(row["name"],row["processes"]," / ".join("`"+r+"`" for r in results) or "通过")
    before,rest=chapter.split(start)
    _,after=rest.split(end)
    artifacts[CHAPTER]=(before+start+"\n\n"+table.rstrip()+"\n\n"+end+after).encode()
    for filename,region in re.findall(r"<<< @/public/learn-agent-rust/code/autonomous-workers/(src/[\w.]+)#([\w-]+)",chapter):
        source=files[filename].decode()
        require(source.count("// region "+region+"\n")==1 and source.count("// endregion "+region+"\n")==1,"Invalid source region "+region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r17-([\w-]+).txt",chapter):
        require(name in outputs,"Unverified output "+name)
    for path,content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes()==content,"Stale R17 artifact: "+str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
    print("R17: {} scenarios / {} independent CLI processes, 12 Rust tests, Clippy and extracted archive replay passed; {}".format(
        len(rows),sum(row["processes"] for row in rows),"artifacts checked" if args.check else "artifacts saved"))


if __name__=="__main__":
    main()
