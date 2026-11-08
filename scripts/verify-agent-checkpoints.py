"""Verify P01 with a real private PostgreSQL cluster and extracted-package replay."""
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

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"docs/public/learn-agent-rust/code/postgres-checkpoints"
DATA=ROOT/"scripts/data/learn-agent-rust/p01-results.json"
CHAPTER=ROOT/"docs/learn-agent-rust/postgres-checkpoints.md"
OUT=ROOT/"docs/public/learn-agent-rust/outputs"
ARCHIVE=ROOT/"docs/public/learn-agent-rust/postgres-checkpoints-lab.zip"
FILES=["Cargo.toml","Cargo.lock",".gitignore","README.md","lab.py","src/main.rs","src/state.rs","src/store.rs","src/driver.rs","src/tests.rs"]


def require(condition,message):
    if not condition:
        raise ValueError(message)


def command(args,cwd,env=None):
    p=subprocess.run([str(x) for x in args],cwd=cwd,env=env,capture_output=True,text=True,timeout=240)
    require(p.returncode==0,"Command failed: {}\n{}\n{}".format(args,p.stdout,p.stderr))
    return p.stdout


def package_bytes(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,content in sorted(files.items()):
            info=zipfile.ZipInfo("postgres-checkpoints-lab/"+name,(2026,1,1,0,0,0))
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
    with tempfile.TemporaryDirectory(prefix="agent-p01-") as directory:
        root=Path(directory)
        folder=root/"source"
        for name,content in files.items():
            path=folder/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
        env=dict(os.environ,CARGO_TARGET_DIR=str(root/"target"),RUSTFLAGS="-D warnings")
        command(["cargo","fmt","--","--check"],folder,env)
        tests=command(["cargo","test","--locked"],folder,env)
        require("10 passed; 0 failed" in tests,"Unexpected Rust test count")
        command(["cargo","clippy","--locked","--all-targets","--","-D","warnings"],folder,env)
        command(["cargo","build","--locked"],folder,env)
        print(command(["python3","lab.py","--binary",root/"target/debug/learn-agent-p01","--output",root/"results"],folder,env).strip(),flush=True)
        result=json.loads((root/"results/results.json").read_text())
        evidence=dict(result,files_sha256={name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
                      rustc=command(["rustc","--version"],folder).strip(),
                      host=command(["rustc","-vV"],folder).split("host: ")[1].splitlines()[0],contract_tests_passed=10,
                      scope="P01 application state machine, script model, real file tools and PostgreSQL 18; independent client processes, immediate server restart, CAS and uncertain actions; no framework Storage or external service integration")
        if args.check and DATA.exists():
            recorded=json.loads(DATA.read_text())
            for key in ("rustc","host"):
                evidence[key]=recorded[key]
            # Cross-platform verification requires major 18 and durability settings;
            # preserve the recorded patch label in the reproducible downloadable snapshot.
            require(int(evidence["libraries"]["server_version_num"])//10000==18,"Wrong PostgreSQL major")
            evidence["libraries"]["server_version_num"]=recorded["libraries"]["server_version_num"]
        serialized=(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n").encode()
        outputs={row["scenario"]:(root/"results"/(row["scenario"]+".txt")).read_bytes() for row in result["scenarios"]}
        artifacts[DATA]=serialized
        artifacts.update({OUT/("p01-"+name+".txt"):content for name,content in outputs.items()})
        archive=package_bytes(dict(files,**{"outputs/"+name+".txt":content for name,content in outputs.items()},**{"evidence.json":serialized}))
        artifacts[ARCHIVE]=archive
        extracted=root/"download"
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            z.extractall(extracted)
        download=extracted/"postgres-checkpoints-lab"
        second_env=dict(env,CARGO_TARGET_DIR=str(root/"download-target"))
        command(["cargo","build","--locked","--offline"],download,second_env)
        print(command(["python3","lab.py","--binary",root/"download-target/debug/learn-agent-p01","--output",root/"again"],download,second_env).strip(),flush=True)
        require(json.loads((root/"again/results.json").read_text())==result,"Extracted archive results differ")
        for name,content in outputs.items():
            require((root/"again"/(name+".txt")).read_bytes()==content,"Extracted output differs: "+name)
    chapter=CHAPTER.read_text()
    start,end="<!-- p01-results:start -->","<!-- p01-results:end -->"
    require(chapter.count(start)==1 and chapter.count(end)==1,"Missing chapter result table")
    table="| 场景 | 独立 Rust CLI 进程 | 验证结果 |\n| --- | --- | --- |\n"
    for row in result["scenarios"]:
        outcomes=sorted({s["result"].get("error") or ("exit="+str(s["result"]["code"]) if s["result"]["status"]=="process_exit" else "") for s in row["steps"]}-{ "" })
        table+="| `{}` | {} | {} |\n".format(row["scenario"],row["processes"]," / ".join("`"+s+"`" for s in outcomes) or "通过断言")
    before,rest=chapter.split(start)
    _,after=rest.split(end)
    artifacts[CHAPTER]=(before+start+"\n\n"+table.rstrip()+"\n\n"+end+after).encode()
    for filename,region in re.findall(r"<<< @/public/learn-agent-rust/code/postgres-checkpoints/(src/[\w.]+)#([\w-]+)",chapter):
        source=files[filename].decode()
        require(source.count("// region "+region+"\n")==1 and source.count("// endregion "+region+"\n")==1,"Missing source region "+region)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/p01-([\w-]+).txt",chapter):
        require(name in outputs,"Unknown output "+name)
    for path,content in artifacts.items():
        if args.check:
            require(path.exists() and path.read_bytes()==content,"Stale P01 artifact: "+str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
    print("P01: 10 Rust tests, Clippy, 25 real PostgreSQL scenarios, {} CLI processes per pass, extracted package replay; {}".format(sum(row["processes"] for row in result["scenarios"]),"artifacts checked" if args.check else "artifacts saved"))


if __name__=="__main__":
    main()
