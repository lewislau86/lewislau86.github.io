"""Verify three real graph-flow labs and replay every independently extracted chapter archive."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
LABS = [('G01','graph-state-routing','graph-state-lab',4),
        ('G02','graph-pause-resume','graph-resume-lab',4),
        ('G03','graph-parallel-subgraphs','graph-parallel-lab',6)]
NAMES = ['.gitignore','Cargo.toml','Cargo.lock','rust-toolchain.toml','README.md','src/main.rs']


def run(command, cwd, env, code=0):
    p = subprocess.run([str(c) for c in command],cwd=cwd,env=env,text=True,capture_output=True,timeout=120)
    if p.returncode != code:
        raise RuntimeError('Unexpected exit {}: {}\n{}\n{}'.format(p.returncode,command,p.stdout,p.stderr))
    return p.stdout if code == 0 else p.stderr


def check_resume(binary, source, env, work):
    outputs={}
    calls=0
    def call(db,*args,code=0):
        nonlocal calls
        calls+=1
        return run([binary,db,*args],source,env,code)
    def init(db):
        return call(db,'init')+call(db,'step')+call(db,'step')
    db=work/'approved.db'; normal=init(db)
    # Waiting re-enters approve, with no decision or report yet.
    normal+=call(db,'step')
    normal+=call(db,'approve','1','yes')+call(db,'step')+call(db,'step')
    normal+=call(db,'step')+call(db,'show')
    assert 'status=waiting cursor=approve' in normal
    assert 'status=already_completed' in normal and 'render_visits=1' in normal
    assert 'draft_visits=1 approval_visits=3' in normal
    outputs['g02-approved.txt']=normal
    with sqlite3.connect(db) as sql:
        version,body=sql.execute('SELECT version,body FROM sessions').fetchone()
        data=json.loads(body)
        assert version == data['version'] and data['current_task_id']=='render'
        assert data['context']['data']['report']=='upgrade report: review complete'
        assert data['context']['data']['terminal'] is True
    denied=work/'denied.db'; text=init(denied)
    text+=call(denied,'approve','1','no')+call(denied,'step')+call(denied,'step')+call(denied,'show')
    assert 'cursor=reject' in text and 'render_visits=0 report=none' in text
    outputs['g02-denied.txt']=text
    stale=work/'stale.db';init(stale)
    with sqlite3.connect(stale) as sql: before=sql.execute('SELECT body FROM sessions').fetchone()[0]
    assert 'stale approval' in call(stale,'approve','0','yes',code=2)
    with sqlite3.connect(stale) as sql: assert before==sql.execute('SELECT body FROM sessions').fetchone()[0]
    call(stale,'approve','1','yes')
    assert 'already submitted' in call(stale,'approve','1','yes',code=2)
    outputs['g02-approval-refusals.txt']='stale_revision=rejected_without_save\nduplicate_decision=rejected\n'
    conflict=work/'conflict.db';call(conflict,'init')
    outputs['g02-conflict.txt']=call(conflict,'conflict')
    # Mutate stored records independently to check graph/schema/cursor and row identity validation.
    for name in ['graph','schema','cursor','row-version','corrupt']:
        bad=work/(name+'.db');call(bad,'init')
        with sqlite3.connect(bad) as sql:
            body=sql.execute('SELECT body FROM sessions').fetchone()[0]; data=json.loads(body)
            if name=='graph': data['graph_id']='release-review-v2'
            if name=='schema': data['context']['data']['schema']=2
            if name=='cursor': data['current_task_id']='unknown'
            if name=='row-version': data['version']=999
            sql.execute('UPDATE sessions SET body=?',[('{broken' if name=='corrupt' else json.dumps(data))])
        refusal=call(bad,'step',code=2)
        assert refusal.strip()
        with sqlite3.connect(bad) as sql:
            persisted=sql.execute('SELECT body FROM sessions').fetchone()[0]
            assert persisted==('{broken' if name=='corrupt' else json.dumps(data))
    outputs['g02-invalid-snapshots.txt']='graph_version=rejected\nstate_schema=rejected\nunknown_cursor=rejected\nrow_version_mismatch=rejected\ncorrupt_json=rejected\n'
    return outputs,dict(scenarios=10,independent_cli_processes=calls,scope='real SQLite SessionStorage and FlowRunner; single business executor; fixed CLI approval')


def verify(lesson,source,work):
    id,slug,binary_name,tests=lesson
    work.mkdir(parents=True)
    env=dict(os.environ,RUSTUP_TOOLCHAIN='1.99.1',CARGO_TARGET_DIR=str(ROOT/'.cache/agent-orchestration-target'))
    for cmd in [['cargo','fmt','--check'],['cargo','test','--locked','--offline'],
                ['cargo','clippy','--locked','--offline','--all-targets','--','-D','warnings'],['cargo','build','--locked','--offline']]:
        run(cmd,source,env)
    binary=ROOT/'.cache/agent-orchestration-target/debug'/binary_name
    if id=='G02': return check_resume(binary,source,env,work)
    scenarios=['normal','direct','exhausted','probes'] if id=='G01' else ['normal','failure','collision','subgraph','timeout']
    outputs={id.lower()+'-'+scenario+'.txt':run([binary,scenario],source,env) for scenario in scenarios}
    all_text='\n'.join(outputs.values())
    checks=(['outcome=accepted repairs=1 calls=5','outcome=accepted repairs=1 calls=2',
             'outcome=needs_human repairs=2','probe=dangling_edge rejected=true',
             'probe=no_edge status=paused cursor=a','probe=bad_goto rejected=true mutation_retained=true',
             'probe=cycle chained_limit_rejected=true','first_matching=b','clone_shares=true serialized_snapshot_isolated=true','malformed_rejected=true']
            if id=='G01' else ['child_end_ignored=true both_started=true',
                               'sibling_result_retained=true merge_ran=false',
                               'shared_counter=1 expected_sum=2 lost_update=true',
                               'child_scratch_exported=false explicit_contract=true','graph_task_timeout=true'])
    for text in checks: assert text in all_text,text+'\n'+all_text
    run([binary,'unknown'],source,env,2)
    return outputs,dict(scenarios=len(scenarios),cli_refusals=1,scope='real graph-flow; deterministic business rules; no model provider')


def archive_bytes(slug,files):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,value in sorted(files.items()):
            info=zipfile.ZipInfo(slug+'/'+name,(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,value)
    return buffer.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for lesson in LABS:
        id,slug,_,tests=lesson;source=PUBLIC/'code'/slug
        # First populate dependencies (also on a clean CI host); both source and
        # independently extracted packages are then compiled and replayed offline.
        run(['cargo','fetch','--locked'],source,dict(os.environ,RUSTUP_TOOLCHAIN='1.99.1'))
        files={name:(source/name).read_bytes() for name in NAMES}
        content=archive_bytes(slug,files);archive=PUBLIC/(slug+'.zip')
        if args.check: assert archive.read_bytes()==content,'Archive stale: '+slug
        with tempfile.TemporaryDirectory(prefix='agent-graph-') as temp:
            work=Path(temp);outputs,record=verify(lesson,source,work/'source')
            with zipfile.ZipFile(io.BytesIO(content)) as z: z.extractall(work/'extracted')
            replay,replay_record=verify(lesson,work/'extracted'/slug,work/'replay')
            assert outputs==replay and record==replay_record
        evidence=dict(schema_version=1,rust='1.99.1',graph_revision='9bbca193f20a8c4ba23289621549ecb3d35fee64',rust_tests=tests,archive_replayed=True,**record,
                      files_sha256={n:hashlib.sha256(b).hexdigest() for n,b in files.items()},
                      outputs_sha256={n:hashlib.sha256(v.encode()).hexdigest() for n,v in outputs.items()})
        targets={PUBLIC/'outputs'/n:v.encode() for n,v in outputs.items()}
        targets[archive]=content
        targets[ROOT/'scripts/data/learn-agent-rust'/(id.lower()+'-results.json')]=(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n').encode()
        for path,value in targets.items():
            if args.check: assert path.read_bytes()==value,'Stale: '+str(path)
            else: path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        print(f'{id}: {tests} Rust tests, source and extracted archive replay passed',flush=True)
    print('Graph orchestration verified: G01/G02/G03, real graph-flow routing, SQLite resume and parallel/subgraph boundaries')


if __name__=='__main__': main()
