#!/usr/bin/env python3
"""Serial full-stack tests of switch-age IT0 bursts plus ordinary-path T1."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time
import backend_study
import balanced_backend
import dense_build as b
import fullset as h
from backend_prefetch import bind_mongodb,audit_backends
from e2e_lbr import remove_generated
from fullset_study import summarize
from mechanism_report import evaluate
from privilege_frontend import DECODE_EVENTS
from hybrid_prepare import prepare,sparse

MODULE=Path('/storage/prefetchit/class_b_dominator_20260927/kernel_build/prefetchit_sched_clock.ko')
LATE_EVENTS='cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_LATE_SWPF,config1=0xa/u,branches:u,branch-misses:u'


def mapped_clock(pid,settings):
    from call_stub_prefetch import Elf
    exe=Path(f'/proc/{pid}/exe');elf=Elf(exe.read_bytes())
    aux=dict(struct.iter_unpack('<QQ',Path(f'/proc/{pid}/auxv').read_bytes()))
    bias=aux[3]-next(p[3] for p in elf.ph if p[0]==6)
    start=bias+settings['clock_va'];end=start+settings['array_bytes']
    lines=Path(f'/proc/{pid}/maps').read_text().splitlines();matching=[]
    for line in lines:
        fields=line.split();a,z=[int(v,16) for v in fields[0].split('-')]
        if a==start and z==end:
            assert fields[1]=='r--s' and fields[-1]=='/dev/prefetchit_sched_clock';matching.append(line)
    assert len(matching)==1,'Missing read-only clock mapping'
    with Path(f'/proc/{pid}/mem').open('rb',buffering=0) as mem:
        mem.seek(start);clock=mem.read(settings['array_bytes'])
        mem.seek(bias+settings['state_va']);state=mem.read(settings['array_bytes'])
        mem.seek(bias+settings['site_stats_va']);sites=mem.read(settings['site_stats_bytes'])
    assert len(clock)==len(state)==262144 and all(struct.unpack_from('<Q',clock,i*64+56)[0]==2 for i in range(4096))
    status={line.split(':')[0]:line.split(':',1)[1].strip() for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith(('Uid:','Gid:'))}
    counts=[0]*8;active=[]
    assert len(sites)==settings['site_stats_bytes']
    site_counts={}
    for group in settings['site_groups']:
        values=struct.unpack_from('<4Q',sites,group['index']*settings['site_stride'])
        if any(values):site_counts[str(group['index'])]=values
    for cpu in range(4096):
        values=struct.unpack_from('<8Q',state,cpu*64)
        if any(values):
            slot=struct.unpack_from('<8Q',clock,cpu*64)
            active.append(dict(cpu=cpu,state=values,clock=slot))
            for i in range(1,8):counts[i]+=values[i]
    return dict(pid=pid,bias=bias,mapping=matching[0],identity=status,active=active,sites=site_counts,
        diagnostic=bool(settings.get('diagnostic')),counts=dict(checks=counts[1],bursts=counts[2],late=counts[3],
            observed_races=counts[4],burst_age_ticks_sum=counts[5],
            burst_age_ticks_max=max((v['state'][6] for v in active),default=0),early_half_bursts=counts[7]),
        interpretation='Counters exist only in the separate diagnostic ELF; production records only the last seen epoch. These are attempted gate outcomes, not successful cache fills.')


@contextmanager
def environment(out,spec):
    enabled=spec.get('hybrid',False);loaded=False;old_save=h.media.save
    module=Path(spec.get('module',MODULE));shim=Path(spec['shim']) if enabled else None
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        assert not Path('/sys/module/prefetchit_sched_clock').exists()
        if enabled:
            b.space(out.parent)
            subprocess.run(['insmod',str(module),'dense_us=10','medium_us=20','sparse_us=40'],check=True);loaded=True
            # Timestamps only, no task IDs/pointers. Keep MongoDB's original uid.
            os.chmod('/dev/prefetchit_sched_clock',0o444)
            def save(path,data):
                if path==out/'compose.json':
                    for name,service in data['services'].items():
                        if not name.endswith('-mongodb'):continue
                        service.setdefault('volumes',[]).append(str(shim)+':/opt/prefetchit/hybrid_map.so:ro')
                        service.setdefault('devices',[]).append('/dev/prefetchit_sched_clock:/dev/prefetchit_sched_clock:r')
                        env=service.setdefault('environment',{})
                        assert isinstance(env,dict) and 'LD_PRELOAD' not in env
                        env['LD_PRELOAD']='/opt/prefetchit/hybrid_map.so'
                old_save(path,data)
            h.media.save=save
        yield
    finally:
        h.media.save=old_save
        try:
            if loaded:subprocess.run(['rmmod','prefetchit_sched_clock'],check=True)
        finally:
            out.mkdir(parents=True,exist_ok=True)
            b.save(out/'clock_restoration.json',dict(enabled=enabled,unloaded=not Path('/sys/module/prefetchit_sched_clock').exists(),
                module_sha256=b.sha(module) if enabled else None,shim_sha256=b.sha(shim) if enabled else None,
                device_permissions='Read-only 0444 for unchanged MongoDB uid; device removed on module unload.' if enabled else None))


def audit(stack,out,binary):
    runtime=audit_backends(stack,out,binary)
    record_path=Path(str(binary)+'.json')
    if str(binary).endswith('.nop') and not record_path.exists():record_path=Path(str(binary)[:-4]+'.json')
    if record_path.exists():
        settings=json.loads(record_path.read_text()).get('hybrid')
        if settings:
            b.save(out/'hybrid_mapping.json',{name:mapped_clock(row['pid'],settings) for name,row in runtime.items()})
    return runtime


def trial(spec):
    out=Path(spec['out']);backend_study.audit_backends=audit
    with environment(out,spec):balanced_backend.trial(spec)


def diagnostic(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out);stack=client=None
    b.save(out/'protocol.json',dict(spec,scope='Separate first-gate age and lifecycle check. No performance inference from this counter-instrumented ELF.'))
    with environment(out,spec):
        try:
            with bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
            runtime=audit(stack,out,spec['mongo_binary'])
            settings=json.loads(Path(spec['mongo_binary']+'.json').read_text())['hybrid'];assert settings['diagnostic']
            before={name:mapped_clock(row['pid'],settings) for name,row in runtime.items()}
            client=balanced_backend.start_client(out,25,spec['seed'],warmup=0)
            assert client.wait(timeout=70)==0;client=None;stack.check()
            after={name:mapped_clock(row['pid'],settings) for name,row in runtime.items()}
            delta={name:{key:after[name]['counts'][key]-before[name]['counts'][key] for key in ['checks','bursts','late','observed_races','burst_age_ticks_sum','early_half_bursts']} for name in runtime}
            site_delta={name:{index:[after[name]['sites'].get(index,[0]*4)[i]-before[name]['sites'].get(index,[0]*4)[i] for i in range(4)]
                for index in set(before[name]['sites'])|set(after[name]['sites'])} for name in runtime}
            assert all(delta[name]['checks']>100 and delta[name]['bursts']>10 for name in ['user-review-mongodb','movie-review-mongodb','review-storage-mongodb'])
            b.save(out/'result.json',dict(valid=True,before=before,after=after,delta=delta,site_delta=site_delta,
                load=json.loads((out/'load/load.json').read_text()),window_us=10,
                timing='Age starts at sched_switch selection, not at first user instruction. Slots use invariant TSC ticks; half-window split is <5us versus 5..10us.'))
        except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
        finally:
            h.c.stop(client)
            if stack is not None:stack.close()
            h.old.compact(out)


def tests(root):
    prior_paths=[root.parent/'balanced_callpath/native_test_sources.json',*sorted(root.parent.glob('hybrid_native_preflight*/native_test_sources.json'))]
    for prior in prior_paths:
        if not prior.exists():continue
        record=json.loads(prior.read_text())
        if record['passed'] and all(b.sha(path)==digest for path,digest in record['sha256'].items()):
            b.save(root/'native_tests_reused.json',dict(source=str(prior),sha256=b.sha(prior),
                result='Reused passing native tests of the exact unchanged source images from a completed serial preflight.'))
            return
    work=root/'native_test_work';b.space(root)
    try:
        b.run(['taskset','-c','84',b.REPO/'profiling/.venv/bin/python','-m','pytest','-q','--basetemp',work,
            b.REPO/'llvm_prefetchit/tests/test_call_stub_prefetch.py',
            b.REPO/'llvm_prefetchit/tests/test_callpath_instruction_hint.py'],root/'native_tests.log')
    finally:
        paths=[p for p in work.rglob('*') if p.is_file() and not p.is_symlink()]
        b.save(root/'native_fixture_sources.json',{str(p.relative_to(work)):p.read_text() for p in paths if p.suffix in ['.c','.cc','.s','.ld','.json']})
        remove_generated(paths,root/'native_test_cleanup.json','Native ABI, flags, return-address, opcode and unwind tests completed; sources, audits, output and hashes retained.')
        links=[p for p in work.rglob('*') if p.is_symlink()]
        b.save(root/'native_test_symlink_cleanup.json',[dict(path=str(p),target=os.readlink(p)) for p in links])
        for path in links:path.unlink()
        for path in sorted([p for p in work.rglob('*') if p.is_dir() and not p.is_symlink()],key=lambda p:len(p.parts),reverse=True):path.rmdir()
        if work.exists():work.rmdir()


def campaign(parent,blocks=3):
    assert (parent/'balanced_callpath/complete.json').exists(),'Run serially after existing balanced confirmation'
    root=parent/'hybrid_switch';root.mkdir(exist_ok=False);b.space(root)
    tests(root)
    prepared=prepare(parent,root/'prepared')
    shim=root/'hybrid_map.so';source=b.REPO/'llvm_prefetchit/kernel/sched_clock/hybrid_map.c'
    shim_prior=parent/'hybrid_native_preflight/shim_build.json'
    reuse=json.loads(shim_prior.read_text()) if shim_prior.exists() else None
    if reuse and b.sha(source)==reuse['source_sha256'] and b.sha(reuse['binary'])==reuse['sha256']:
        shim=Path(reuse['binary']);b.save(root/'shim_reused.json',dict(record=str(shim_prior),sha256=b.sha(shim_prior)))
    else:
        b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',source,'-o',shim],root/'shim_build.log')
        b.run(['readelf','--version-info',shim],root/'shim_versions.log')
        # Entrypoint and shell inherit the shim but have no reserved sections.
        b.run(['/usr/bin/env','LD_PRELOAD='+str(shim),'/bin/true'],root/'shim_passthrough.log')
    native=json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    from dense_causes import counters
    b.run(['perf','stat','-x,','-o',root/'late_preflight.csv','-e',LATE_EVENTS,'-a','-C','84','--','sleep','.2'],root/'late_preflight.log')
    assert counters(root/'late_preflight.csv')['fully_scheduled']
    common=dict(overrides=native,extra_events={'decode':DECODE_EVENTS,'late':LATE_EVENTS},stat_s=3,shim=str(shim),module=str(MODULE))
    arms={
        'original':dict(common,mongo_binary=prepared['reference']),
        'cost75':dict(common,mongo_binary=prepared['cost75']['binary'],controls=['original']),
        'hybrid_nop':dict(common,mongo_binary=prepared['nop'],hybrid=True,controls=['original']),
        'early_t1':dict(common,mongo_binary=prepared['early_t1'],hybrid=True,controls=['original','hybrid_nop','cost75']),
        'hybrid_it0':dict(common,mongo_binary=prepared['hybrid'],hybrid=True,controls=['original','hybrid_nop','cost75','early_t1'])}
    b.save(root/'protocol.json',dict(blocks=blocks,seedbase=85001,arms=arms,source_sha256=b.sha(__file__),
        shim_sha256=b.sha(shim),module_sha256=b.sha(MODULE),prepared=prepared,
        qualification='Separate native ABI tests and real-module full-stack diagnostic precede fresh C4 timing. Same 50s warmup, 60s ROI, balanced persistent connections and three-second post-ROI PMU windows as the preceding controlled campaign.',
        timing='First observed cost75 call within 0..10us from incoming-task selection, at most eight IT0 hints. Later ordinary calls issue the existing T1 list. No timer or scheduler code injection of IT0.',
        late_event='FRONTEND_RETIRED.LATE_SWPF records demand instruction-cache misses overlapping an ongoing PREFETCHIT0/1-triggered fetch. Nonzero counts demonstrate some late overlap; zero does not establish absence of hint execution, timely success, or an empty fetch queue. Source: https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/',
        gate_refinement='Before any E2E timing, use only first diagnostic gate counts to retain at most 64 canonical groups covering up to 90% of observed first bursts. Plain T1 remains at the other cost75 calls. A different-seed diagnostic checks this sparse policy; no reselection from the second diagnostic or timing results.',
        selection='Three exploratory paired blocks, fixed order and reverse order, no performance-based retries/exclusions. Assess E2E speedup, mean/p99 and whole/pool CPU cost with retired L2 and speculative L2I separately.'))
    spec=dict(common,out=str(root/'diagnostic'),hybrid=True,mongo_binary=prepared['diagnostic'],seed=84901)
    manifest=root/'diagnostic_spec.json';b.save(manifest,spec)
    h.platform(root/'diagnostic',['python3',Path(__file__),'diagnostic',manifest])
    remove_generated([Path(prepared['diagnostic'])],root/'diagnostic_elf_cleanup.json','Gate diagnostic complete; retain ages, counts, source, patches and hashes. No timing uses this counter-instrumented ELF.')
    reduced=sparse(prepared,root/'diagnostic/result.json',root/'sparse')
    spec=dict(common,out=str(root/'sparse_diagnostic'),hybrid=True,mongo_binary=reduced['sparse_diag']['binary'],seed=84902)
    manifest=root/'sparse_diagnostic_spec.json';b.save(manifest,spec)
    h.platform(root/'sparse_diagnostic',['python3',Path(__file__),'diagnostic',manifest])
    remove_generated([Path(reduced['sparse_diag']['binary'])],root/'sparse_diagnostic_elf_cleanup.json','Sparse gate verification complete; preserve its independent-seed activity and age records. Counter code is excluded from timing.')
    arms['hybrid_sparse_nop']=dict(common,mongo_binary=reduced['sparse']['nop'],hybrid=True,controls=['original','hybrid_nop'])
    arms['hybrid_sparse']=dict(common,mongo_binary=reduced['sparse']['binary'],hybrid=True,controls=['original','cost75','hybrid_sparse_nop','hybrid_it0'])
    protocol=json.loads((root/'protocol.json').read_text());protocol.update(arms=arms,sparse_prepared=reduced,
        finalized_before_timing_epoch=time.time());b.save(root/'protocol.json',protocol)
    screen=root/'screen';screen.mkdir();b.save(screen/'protocol.json',dict(blocks=blocks,arms=arms,seedbase=85001))
    names=list(arms);rows=[]
    for block in range(blocks):
        for arm in names if block%2==0 else list(reversed(names)):
            b.space(root);out=screen/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=85001+block))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            r=json.loads((out/'result.json').read_text());assert r['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=r['pool']['achieved_rps'],pool_util_pct=r['pool_util_pct'],
                metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']))
            rows.append(row);b.save(screen/'rows.json',rows);b.save(screen/'summary.json',summarize(rows,arms));print(json.dumps(row),flush=True)
    b.save(screen/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))
    evaluate(screen,root/'screen_evaluation.json')
    b.save(root/'complete.json',dict(clean_trials=len(rows),diagnostic_valid=True))
    b.run(['python3',Path(__file__).with_name('backend_summary.py'),root,'--plot'],root/'summary.log')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['campaign','trial','diagnostic']);p.add_argument('path',type=Path)
    p.add_argument('--blocks',type=int,default=3);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if a.action=='campaign':campaign(a.path,a.blocks)
    else:globals()[a.action](json.loads(a.path.read_text()))
