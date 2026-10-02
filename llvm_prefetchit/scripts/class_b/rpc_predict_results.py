#!/usr/bin/env python3
"""Summarize frozen RPC stages, audit restoration and publish compact evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import tarfile
import time

import dense_build as b
from rpc_route_study import load
from temporal_path_confirm import cleanup, arm_paths

TAG='class_b_rpc_predict_20261002'
PHASES=('screen','confirmation','coverage_screen','production_confirmation')


def summarize(root):
    assert load(root/'all_measurements_complete.json')['valid']
    candidate=load(root/'production_selection.json')['nominee'];phases={}
    for phase in PHASES:
        e=load(root/phase/'evaluation.json')
        phases[phase]=dict(trials=e['trials'],comparisons=e['e2e'],
            absolute={n:dict(rps=v['rps'],util_pct=v['util_pct'],**v['e2e']) for n,v in e['absolute'].items()})
    c=phases['production_confirmation']['comparisons'][candidate]['full']
    promoted=c['inverse_rps']['speedup_ci95'][0]>1 and c['stack_cpu']['cost_reduction_pct']>=-.5 and c['p99_ms']['cost_reduction_pct']>=-2
    nop=phases['production_confirmation']['comparisons'][candidate][candidate+'_nop']
    decision=dict(candidate=candidate,selected=candidate if promoted else 'full',promoted=promoted,
        prefetch_increment_positive_ci=nop['inverse_rps']['speedup_ci95'][0]>1,
        epoch=time.time(),rule='Frozen nominee only: positive lower individual paired-log t95 throughput bound versus full plus CPU <=+0.5%, p99 <=+2%. Exact-layout NOP is a separate attribution test.',
        nop_scope='Additional reply hints only; incoming RPC hints remain active.' if candidate.startswith('reply') else 'All newly added incoming-RPC hints; incumbent hints remain active.')
    baseline={}
    for phase in PHASES:
        rows=load(root/phase/'rows.json');baseline[phase]={}
        for name in ('original','full'):
            values=[r['achieved_rps'] for r in rows if r['arm']==name]
            if values:baseline[phase][name]=dict(values=values,cv_pct=100*statistics.stdev(values)/statistics.mean(values))
    report=dict(candidate=candidate,decision=decision,phases=phases,baseline_variation=baseline,
        pmu=load(root/'analysis/pmu_summary.json'),residuals=load(root/'analysis/residuals.json'),
        prepared={n:load(root/'prepared_candidates.json')[n]['builds'] for n in ('lean','wide','reply','reply_it0')},
        limits='All endpoint effects use fresh stacks and clean ROIs. Phases are not pooled. PMU windows and PEBS profiles are descriptive independent diagnostics; raw L2 code reads and retired L2 misses are different populations. No BTB occupancy, prefetch completion, or exact hint-to-fetch latency is measured.')
    b.save(root/'final_decision.json',decision);b.save(root/'analysis/report.json',report)
    arms=load(root/'arms.json');keep=[arms['original'],arms['full']]
    if promoted:keep += [arms[candidate],arms[candidate+'_nop']]
    rejected=[n for n in ('early','late','split','nop','lean','wide','reply','reply_it0') if not promoted or n!=candidate]
    # Some winning variants reference binaries stored in a parent variant's
    # folder. Protection is by resolved measured path, never just folder name.
    cleanup(root,rejected,keep,'final_rejected_cleanup.json')
    print(json.dumps(dict(decision=decision,absolute=phases['production_confirmation']['absolute']),indent=2))


def audit(root):
    assert load(root/'all_measurements_complete.json')['valid'];decision=load(root/'final_decision.json')
    checks=[];platforms=[]
    for name in ('platform_before.json','hwp_before.json'):
        for before in sorted(root.rglob(name)):
            after=before.with_name(name.replace('_before','_restored'))
            assert after.exists() and load(before)==load(after),before
            checks.append(dict(before=str(before.relative_to(root)),restored=True))
            if name=='platform_before.json':platforms.append(before.parent.parent)
    assert checks
    latest=max(set(platforms),key=lambda p:(p/'command.json').stat().st_mtime);expected={}
    for cpu in load(latest/'command.json')['cpus']:
        for path,value in load(latest/f'cpu{cpu}/platform_before.json').items():expected.setdefault(path,value)
    current=[dict(path=p,expected=v,actual=Path(p).read_text().strip()) for p,v in expected.items()]
    assert all(r['expected']==r['actual'] for r in current)
    project='codex-b-fullset-media';owned={}
    for label,cmd in [('containers',['docker','ps','-aq']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:
        owned[label]=subprocess.check_output(cmd+['--filter','label=com.docker.compose.project='+project],text=True).splitlines()
    assert not any(owned.values())
    modules={n:Path('/sys/module',n).exists() for n in ('wake_prefetch','prefetchit')};assert not any(modules.values())
    quality=[]
    for phase in PHASES:
        for row in load(root/phase/'rows.json'):
            result=load(Path(row['output'])/'result.json');info=load(Path(row['output'])/'load/load.json')
            assert row['valid'] and result['valid'] and info['mapping_preserved'] and not info['steady_errors']
            quality.append(dict(phase=phase,block=row['block'],arm=row['arm'],steady_errors=info['steady_errors'],mapping_preserved=True))
    smoke=[]
    for path in sorted((root/'smoke').glob('*/result.json')):
        result=load(path);assert result['valid'];smoke.append(str(path.relative_to(root)))
    profiles=[]
    for directory in ('profiles','mongo_profiles'):
        for path in sorted((root/directory).glob('*/complete.json')):
            result=load(path);assert result['valid'];profiles.extend(result['captures'])
    for capture in profiles:
        path=Path(capture);assert (path/'observations.json.gz').exists()
        assert not (path/'perf.data').exists() and not (path/'events.txt').exists()
        quality_row=load(path/'timeline.json')['quality'];assert quality_row['complete_sample_pct']>99
    arms=load(root/'arms.json');keep=[arms['original'],arms['full']]
    if decision['promoted']:keep += [arms[decision['candidate']],arms[decision['candidate']+'_nop']]
    protected=set().union(*(arm_paths(a) for a in keep))
    hashes=load(root/'production_confirmation/protocol.json')['binary_hashes'];retained=[]
    for path in (root/'builds').rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        with path.open('rb') as stream:elf=stream.read(4)==b'\x7fELF'
        if elf:
            assert path.resolve() in protected,path
            digest=b.sha(path);assert hashes[str(path)]==digest
            retained.append(dict(path=str(path),bytes=path.stat().st_size,sha256=digest))
    previous=load(Path('/storage/prefetchit/class_b_rpc_future_20261001/tests_nested.json'))
    for path,digest in previous['sources'].items():assert b.sha(b.REPO/path)==digest
    b.save(root/'final_restoration_audit.json',dict(valid=True,epoch=time.time(),platform_comparisons=checks,
        latest_platform=str(latest),current_sysfs=current,owned_resources=owned,modules=modules,
        endpoint_quality=quality,smokes=smoke,profile_captures=profiles,retained_generated_elves=retained,
        unchanged_previously_tested_native_sources=previous,
        free_bytes={'root':shutil.disk_usage('/').free,'storage':shutil.disk_usage(root).free}))
    print(dict(clean_trials=len(quality),smokes=len(smoke),captures=len(profiles),restored_records=len(checks),retained_elves=len(retained)))


def publish(root):
    assert load(root/'final_restoration_audit.json')['valid'];assert (root/'report.md').exists()
    destination=b.REPO/'llvm_prefetchit/migration/evidence'/TAG;destination.mkdir(parents=True,exist_ok=False)
    for path in Path(__file__).parent.glob('rpc_predict_*.py'):
        snapshot=root/'source_versions'/(b.sha(path)+'.py')
        if not snapshot.exists():snapshot.write_bytes(path.read_bytes())
    selected=[];records={};local=[]
    excluded={'requests.json.gz','observations.json.gz','perf.data','events.txt','samples.txt','work_state.json'}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():continue
        rel=str(path.relative_to(root))
        if path.name in excluded:
            if path.name=='observations.json.gz':local.append(dict(path=rel,bytes=path.stat().st_size,sha256=b.sha(path)))
            continue
        if path.suffix not in ('.json','.csv','.log','.txt','.py','.s','.ld','.asm'):continue
        with path.open('rb') as stream:
            if stream.read(4)==b'\x7fELF':continue
        selected.append(path);records[rel]=dict(bytes=path.stat().st_size,sha256=b.sha(path))
    archive=destination/'records.tar.gz'
    with tarfile.open(archive,'w:gz') as output:
        for path in selected:output.add(path,arcname=str(path.relative_to(root)),recursive=False)
    with tarfile.open(archive) as source:
        assert set(source.getnames())==set(records)
        for member in source:
            data=source.extractfile(member).read();assert len(data)==records[member.name]['bytes']
            assert hashlib.sha256(data).hexdigest()==records[member.name]['sha256']
    assert archive.stat().st_size<90*2**20
    b.save(destination/'records_manifest.json',records);b.save(destination/'local_profiles.json',dict(root=str(root),files=local))
    for name in ('final_decision.json','final_restoration_audit.json','reply_it0_predeclared.json','reply_predeclared.json','wide_predeclared.json'):
        shutil.copyfile(root/name,destination/name)
    shutil.copyfile(root/'analysis/report.json',destination/'report.json')
    figures={}
    for path in sorted((root/'analysis').glob('*.png'))+sorted((root/'analysis').glob('*.svg')):
        target=b.REPO/'docs/figures'/(TAG+'_'+path.name);shutil.copyfile(path,target)
        figures[str(target.relative_to(b.REPO))]=dict(bytes=target.stat().st_size,sha256=b.sha(target))
    report=b.REPO/'docs'/(TAG+'.md');shutil.copyfile(root/'report.md',report)
    b.save(destination/'manifest.json',dict(source=str(root),archived_records=len(records),archive_bytes=archive.stat().st_size,
        archive_sha256=b.sha(archive),verified_archive=True,figures=figures,report_sha256=b.sha(report),
        exclusions='No generated ELF/object/build bulk, benchmark datasets, raw/decoded trace text, request lists, credentials or unrelated process identities. Compact PEBS observations remain local with hashes.'))
    print(dict(evidence=str(destination),archived_records=len(records),archive_bytes=archive.stat().st_size))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['summarize','audit','publish']);parser.add_argument('root',type=Path)
    args=parser.parse_args();globals()[args.action](args.root)
