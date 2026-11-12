"""Verify D01-D08 graph-flow labs, cross-process approval and extracted chapter downloads.

All default inputs are deterministic. Optional external model comparison is never
called here. HTTP fixtures test the comparison runner, not real model quality.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'docs/public/learn-agent-rust'
CASES = {
 'D01': {'single':'completed','workflow':'completed','adaptive':'completed','missing':'missing_evidence','forbidden':'permission_denied','budget':'budget_exhausted'},
 'D02': {'readme':'completed','cargo':'completed','unknown':'needs_input','missing':'missing_field','stale':'stale_artifact','budget':'budget_exhausted'},
 'D03': {'normal':'completed','reverse':'completed','failure':'branch_failed','duplicate':'member_mismatch','stale':'stale_result','missing':'member_mismatch','cancel':'cancelled','budget':'budget_exhausted'},
 'D04': {'normal':'completed','discover':'completed','cycle':'dependency_cycle','unknown':'unknown_dependency','repeat':'repeated_plan','budget':'budget_exhausted'},
 'D05': {'normal':'completed','three':'completed','failed_worker':'worker_failed','invalid_role':'invalid_role_or_permission','stale':'stale_handoff','depth':'delegation_depth','budget':'budget_exhausted'},
 'D06': {'normal':'completed','already_good':'completed','stale':'stale_feedback','malformed':'invalid_feedback','no_progress':'no_progress','new_error':'no_progress','budget':'budget_exhausted'},
 'D07': {'approve':'completed','clarify':'needs_approval','edit':'needs_approval','deny':'denied','stale':'stale_approval','duplicate':'duplicate_decision','budget':'budget_exhausted'},
 'D08': {'normal':'completed','discover':'completed','branch_failed':'branch_failed','stale_branch':'stale_result','missing_branch':'member_mismatch','stale_approval':'stale_approval','denied':'denied','no_progress':'no_progress','budget':'budget_exhausted'},
}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def require(value, message):
    if not value:
        raise AssertionError(message)


def command(args, cwd, env, code=0):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    require(result.returncode == code, 'Command failed: {}\n{}\n{}'.format(args, result.stdout, result.stderr))
    return result.stdout


def check_outputs(id, rows):
    require([r['scenario'] for r in rows] == list(CASES[id]), id + ': scenario coverage')
    by = {r['scenario']: r for r in rows}
    for name, expected in CASES[id].items():
        row = by[name]
        require(row['stop'] == expected, id + '/' + name + ': wrong business terminal')
        require(0 < row['used'] <= row['limit'], id + ': global budget exceeded')
        require(bool(row['trace']), id + ': no real graph nodes executed')
        if expected != 'completed':
            require('report' not in row['data'] or id in {'D01','D06','D08'}, id + ': premature report')
        if name == 'budget':
            require(row['used'] == 1 and len(row['trace']) == 1, id + ': action after exhausted budget')
    if id == 'D01':
        require(by['single']['data']['reads'] == 0 and by['adaptive']['data']['reads'] == 2, 'D01: strategy behavior')
    elif id == 'D02':
        require(by['cargo']['data']['report']['command'] == 'cargo test', 'D02: validated artifact')
        require('render' not in by['stale']['trace'], 'D02: stale data reached renderer')
    elif id == 'D03':
        require(by['normal']['data']['report'] == by['reverse']['data']['report'], 'D03: nondeterministic merge')
        require(by['normal']['data']['peak'] == 2 and by['cancel']['data']['joined'], 'D03: overlap/join')
    elif id == 'D04':
        require(by['discover']['data']['done'] == ['root','member'] and by['discover']['data']['plan']['revision'] == 2, 'D04: replan lost ledger')
        require(by['cycle']['data']['done'] == [] and by['unknown']['data']['done'] == [], 'D04: invalid plan executed')
    elif id == 'D05':
        require(len(by['three']['data']['results']) == 3, 'D05: dynamic worker count')
        require(by['normal']['data']['returned_from'] == 'license' and by['normal']['data']['controller'] == 'technical', 'D05: no control return')
        require(by['invalid_role']['data']['controller'] == 'technical', 'D05: invalid role took control')
    elif id == 'D06':
        require(by['normal']['data']['baseline']['sources'] == [] and by['normal']['data']['repairs'] == 1, 'D06: baseline lost')
        require(by['stale']['data']['candidate'] == by['stale']['data']['baseline'], 'D06: stale feedback edited candidate')
    elif id == 'D07':
        require(by['approve']['data']['effects'] == 1 and all(r['data']['effects'] == 0 for r in rows if r['stop'] != 'completed'), 'D07: invalid approval resumed')
    elif id == 'D08':
        require(by['discover']['data']['sources'] == ['member/README.md','root/README.md'], 'D08: missing member evidence')
        require(by['discover']['data']['joined'] and by['discover']['data']['repairs'] == 1, 'D08: composition skipped stages')
        require(all(r['data']['effects'] == 0 for r in rows if r['stop'] != 'completed'), 'D08: published without accepted evidence/approval')


def disk_checks(binary, source, env, work):
    calls = 0
    def call(path, action, *args, code=0):
        nonlocal calls
        calls += 1
        return command([binary, 'disk', path, action, *args], source, env, code)
    path = work / 'request.json'
    call(path, 'init')
    before = path.read_bytes()
    call(path, 'approve', '2', '1', code=2)
    require(path.read_bytes() == before, 'Unknown request saved')
    call(path, 'approve', '1', '1')
    call(path, 'edit', 'edited report')
    before = path.read_bytes()
    call(path, 'approve', '1', '1', code=2)
    call(path, 'resume', code=2)
    require(path.read_bytes() == before, 'Stale approval saved or resumed')
    call(path, 'approve', '1', '2')
    call(path, 'approve', '1', '2', code=2)
    call(path, 'resume')
    done = json.loads(call(path, 'show'))
    require(done['completed'] and done['content'] == 'edited report' and done['revision'] == 2, 'Wrong restored state')
    before = path.read_bytes()
    call(path, 'resume', code=2)
    require(path.read_bytes() == before, 'Terminal replay saved')
    denied = work / 'denied.json'
    call(denied, 'init'); call(denied, 'deny', '1', '1'); call(denied, 'resume', code=2)
    corrupt = work / 'corrupt.json'; corrupt.write_text('{broken')
    call(corrupt, 'show', code=2)
    require(corrupt.read_text() == '{broken', 'Corrupt state overwritten')
    return {'independent_cli_processes': calls, 'edit_invalidates_approval': True, 'duplicate_rejected': True,
            'unknown_identity_rejected': True, 'denied_cannot_resume': True, 'corrupt_preserved': True,
            'scope': 'single-writer local JSON state; atomic rename, no database/identity service/external publish'}


def check_binary(id, binary, source, env, work):
    work.mkdir(parents=True)
    output = command([binary, 'suite'], source, env)
    rows = [json.loads(line) for line in output.splitlines()]
    check_outputs(id, rows)
    extra = {}
    if id == 'D07':
        extra = disk_checks(binary, source, env, work)
    if id == 'D08':
        artifact = work / 'report.json'
        command([binary, 'discover', artifact], source, env)
        data = json.loads(artifact.read_text())
        require(data['effects'] == 1 and data['sources'] == ['member/README.md','root/README.md'], 'Actual report artifact')
        rejected = work / 'should-not-exist.json'
        command([binary, 'stale_approval', rejected], source, env)
        require(not rejected.exists(), 'Stale approval wrote report')
        spec = importlib.util.spec_from_file_location('pattern_model_compare', source / 'model_compare.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.self_test(work / 'http')
        report = json.loads((work / 'http/report.json').read_text())
        extra = {'actual_report_checked': True, 'stale_approval_no_file': True,
                 'http_fixture_tasks': report['attempted_tasks'], 'variants': list(module.VARIANTS),
                 'live_provider': {'status':'not_run','reason':'User will configure an OpenAI-compatible endpoint'},
                 'scope':'actual Rust graph; fixed decisions; real report file; HTTP comparison runner is a separate Python driver'}
    return rows, extra


def archive_bytes(slug, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo(slug + '/' + name, (2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16; archive.writestr(info,value)
    return buf.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--lesson',choices=list(CASES))
    args=parser.parse_args()
    lessons=[r for r in json.loads((ROOT/'scripts/learn-agent-rust-lessons.json').read_text())['lessons'] if r['id'] in CASES and (not args.lesson or r['id']==args.lesson)]
    env=dict(os.environ,RUSTUP_TOOLCHAIN='1.99.1',CARGO_TARGET_DIR=str(ROOT/'.cache/agent-patterns-target'))
    count=0
    with tempfile.TemporaryDirectory(prefix='agent-patterns-') as temp:
        temp=Path(temp)
        for lesson in lessons:
            id,slug=lesson['id'],lesson['slug'];source=PUBLIC/'code'/slug
            names=sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file() and not any(x in {'target','__pycache__'} for x in p.relative_to(source).parts))
            files={name:(source/name).read_bytes() for name in names}
            # Build copied sources, so successful compilation cannot depend on sibling paths.
            copied=temp/(id+'-source')
            for name,value in files.items():
                path=copied/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            for cmd in [['cargo','fmt','--check'],['cargo','test','--locked','--offline'],['cargo','clippy','--locked','--offline','--all-targets','--','-D','warnings'],['cargo','build','--locked','--offline']]:
                tested=command(cmd,copied,env)
                if cmd[1]=='test':require('4 passed; 0 failed' in tested,id+': tests missing')
            binary=Path(env['CARGO_TARGET_DIR'])/'debug'/('agent-'+id.lower()+'-lab')
            rows,extra=check_binary(id,binary,copied,env,temp/(id+'-runs'))
            data={'id':id,'scope':'real pinned graph-flow; deterministic scripted decisions; no real model quality claim',
                  'source_sha256':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()},
                  'rust_tests':4,'scenarios':len(rows),'results':rows,'additional':extra}
            out=encoded(rows)
            bundled=dict(files);bundled['outputs/suite.json']=out;bundled['evidence.json']=encoded(data)
            archive=archive_bytes(slug,bundled);archive_path=PUBLIC/(slug+'.zip')
            published=archive_path.read_bytes() if args.check and archive_path.exists() else archive
            extracted=temp/(id+'-download')
            with zipfile.ZipFile(io.BytesIO(published)) as z:z.extractall(extracted)
            downloaded=extracted/slug
            for name,value in bundled.items():require((downloaded/name).read_bytes()==value,id+': stale download '+name)
            download_env=dict(env,CARGO_TARGET_DIR=str(ROOT/'.cache/agent-patterns-download-target'))
            command(['cargo','build','--locked','--offline'],downloaded,download_env)
            replay,again=check_binary(id,Path(download_env['CARGO_TARGET_DIR'])/'debug'/binary.name,downloaded,download_env,temp/(id+'-repeat'))
            require(rows==replay and extra==again,id+': final archive replay differs')
            chapter=(ROOT/'docs/learn-agent-rust'/(slug+'.md')).read_text()
            imports=re.findall(r'<<< @/public/learn-agent-rust/code/'+re.escape(slug)+r'/([\w/.-]+)#([\w-]+)',chapter)
            require(len(imports)>=3,id+': missing source snippets')
            for filename,region in imports:
                text=files[filename].decode();prefix='# ' if filename.endswith('.py') else '// ';require(text.count(prefix+'region '+region+'\n')==text.count(prefix+'endregion '+region+'\n')==1,id+': bad region '+region)
            require('<<< @/public/learn-agent-rust/outputs/'+id.lower()+'-suite.json' in chapter,id+': missing actual output import')
            for path,content in {PUBLIC/'outputs'/(id.lower()+'-suite.json'):out,ROOT/'scripts/data/learn-agent-rust'/(id.lower()+'-results.json'):encoded(data),archive_path:archive}.items():
                if args.check:require(path.exists() and path.read_bytes()==content,'Stale artifact: '+str(path.relative_to(ROOT)))
                else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            count+=len(rows)
            print(id+': 4 Rust tests, '+str(len(rows))+' scenarios, Clippy and independent extracted archive replay passed',flush=True)
    print('Patterns: '+str(len(lessons))+' chapters / '+str(count)+' scenarios; sources and artifacts '+('checked' if args.check else 'saved')+'; live model NOT RUN')


if __name__=='__main__':main()
