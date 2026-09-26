#!/usr/bin/env python3
"""Serial five-service DSB validation; all timings use fresh full stacks."""
import argparse
import fcntl
import gzip
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[3]
HARNESS=REPO/'llvm_prefetchit/migration/schemes/class_b_extension_20260926'
sys.path.insert(0,str(HARNESS))
import common as c
import media
import social
import trace_media
import build
import social_headroom as old

OUT=Path(os.environ.get('CLASS_B_FULLSET_OUT','/storage/prefetchit/class_b_fullset_20260926'))
TRACE=Path(os.environ.get('CLASS_B_FULLSET_TRACE','/trace/prefetchit/class_b_fullset_20260926'))
TARGETS={
    'media':{'movie':('movie-id-service','MovieIdService','40-41'),
             'compose':('compose-review-service','ComposeReviewService','42-43'),
             'rating':('rating-service','RatingService','44-45')},
    'social':{'composepost':('compose-post-service','ComposePostService','40-41'),
              'usertimeline':('user-timeline-service','UserTimelineService','42-43')}}
media.TARGETS=TARGETS['media']
RATE={'media':600,'social':600}
POLICY=dict(d=8,dmax=48,k=12,kmerge=32,gap_k=32,post_call=24,p_min=.5,
            merge_policy='byte-efficiency',site_p=.8,max_calls=1.5)


def baseline(family,key):
    return c.S/(family+'_build')/key/'base'/TARGETS[family][key][1]


def reference(family,key):
    if key=='movie':return REPO/'flat_codegen/dsb_build/out_mid_p11a/MovieIdService'
    # Rating's old wake16 failed promotion and its generated binary was removed.
    # The retained reference for deployment is therefore its baseline.
    if key=='rating':return baseline(family,key)
    return c.S/(family+'_build')/key/('wake8' if key=='compose' else 'wake16')/TARGETS[family][key][1]


def start(out,family,overrides,pool,alone=False):
    os.environ['CLASS_B_MEDIA_SAMPLE_RATE']='1'
    os.environ['CLASS_B_SOCIAL_SAMPLE_RATE']='.1'
    stack=(media.Stack if family=='media' else social.Stack)(out,overrides)
    stack.project='codex-b-fullset-'+family
    stack.dc=['docker','compose','-p',stack.project,'-f',str(out/'compose.json')]
    try:
        stack.start()
        target_cpus={v[0]:v[2] for v in TARGETS[family].values()}
        for name in stack.states:
            cpus=target_cpus[name] if alone and name in target_cpus else f'32-{31+pool}'
            subprocess.run(['docker','update','--cpuset-cpus',cpus,stack.cid(name)],
                           check=True,stdout=subprocess.DEVNULL)
        stack.check()
    except BaseException:
        stack.close();raise
    return stack


def load(out,family,rate,seed,seconds):
    out.mkdir()
    command=['python3',str(HARNESS/'load.py'),'--out',str(out),'--rate',str(rate),
        '--seconds',str(seconds),'--seed',str(seed),'--workload',family,
        '--port','18081' if family=='media' else '18082']
    c.save(out/'command.json',command)
    with (out/'client.log').open('w') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for _ in range(100):
        if (out/'started.json').exists():return child
        assert child.poll() is None
        time.sleep(.1)
    raise RuntimeError('load did not start')


def platform(out,command):
    c.space()
    p=out.with_name(out.name+'_platform')
    c.run(['python3',HARNESS/'run_platform.py','--out',p,'--cpus','16-19,32-45',*command],
          out.with_suffix('.log'),timeout=2400)
    checks=[]
    for before in p.rglob('*_before.json'):
        after=before.with_name(before.name.replace('_before','_restored'))
        checks.append(after.exists() and json.loads(before.read_text())==json.loads(after.read_text()))
    assert checks and all(checks),'platform state not restored'
    c.save(p/'verified.json',dict(restored=True,comparisons=len(checks)))


def trial(spec):
    c.space()
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    family=spec['family'];pool=spec['pool'];rate=spec.get('rate',RATE[family])
    overrides={k:c.ensure_local(Path(v)) for k,v in spec.get('overrides',{}).items()}
    c.save(out/'protocol.json',dict(**spec,policy_metric='target and whole-stack user+kernel CPU per exact completed request',
        binary_hashes={k:c.sha(overrides.get(k,baseline(family,k))) for k in TARGETS[family]},
        driver_sha256=c.sha(__file__),warmup_s=50,primary_s=30,
        source_hashes={p.name:c.sha(p) for p in HARNESS.glob('*.py')}))
    stack=client=None;fd=None;loaded=False
    measured=set(range(32,32+pool))
    if spec.get('alone'):measured|=set(range(40,46 if family=='media' else 44))
    pmu_keys=spec.get('pmu',[])
    try:
        stack=start(out,family,overrides,pool,spec.get('alone',False))
        kernel=spec.get('kernel')
        if kernel:
            assert not Path('/sys/module/wake_prefetch').exists()
            module=REPO/'llvm_prefetchit/kernel/wake_prefetch/wake_prefetch.ko'
            subprocess.run(['insmod',str(module)],check=True);loaded=True
            pid=stack.states[TARGETS[family][kernel['service']][0]]['State']['Pid']
            if kernel['mode']!='empty':
                plan=json.loads(Path(kernel['plan']).read_text())
                profiles,audit=old.control.resolve(plan,pid)
                fd=os.open('/dev/wake_prefetch',os.O_RDWR|os.O_CLOEXEC)
                config=old.control.pack_config(pid,int(kernel['mode']=='t1'),profiles,**kernel.get('options',{}))
                fcntl.ioctl(fd,old.control.CONFIG_IOCTL,config,True)
                c.save(out/'kernel_registration.json',dict(profiles=profiles,audit=audit,
                    module_sha256=c.sha(module),plan_sha256=c.sha(kernel['plan']),settings=kernel))
        client=load(out/'load',family,rate,spec['seed'],max(95,95+20*len(pmu_keys)))
        time.sleep(50);assert client.poll() is None
        before=stack.accounts();pb=old.pool_cpu(measured)
        kb=old.control.stats(fd) if fd is not None else None
        db=old.control.detail(fd) if fd is not None else None
        time.sleep(30)
        ka=old.control.stats(fd) if fd is not None else None
        da=old.control.detail(fd) if fd is not None else None
        pa=old.pool_cpu(measured);after=stack.accounts()
        costs={k:c.diff_cpu(before[k],after[k]) for k in before}
        pmu={}
        for key in pmu_keys:
            name=TARGETS[family][key][0];pid=stack.states[name]['State']['Pid'];b=c.cpu(pid)
            group=str(Path(b['path']).parent.relative_to('/sys/fs/cgroup'))
            command=['perf','stat','-x,','-o',str(out/(key+'.pmu.csv')),'-e',c.EVENTS,
                     '-a','-C','32-45','-G',group,'--','sleep','20']
            c.run(command,out/(key+'.pmu.log'))
            pmu[key]=dict(**c.counters(out/(key+'.pmu.csv')),window=c.diff_cpu(b,c.cpu(pid)))
        rc=client.wait(timeout=90);client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        with gzip.open(out/'load/requests.json.gz','rt') as f:samples=json.load(f)
        for cost in costs.values():old.attach(cost,samples)
        pc=old.attach(dict(start=pb['epoch'],end=pa['epoch'],wall_s=pa['monotonic']-pb['monotonic'],
            cpu_us=sum(pa['ticks'][k]-v for k,v in pb['ticks'].items())*1e6/pb['clock_ticks']),samples)
        for record in pmu.values():
            old.attach(record['window'],samples);n=record['window']['completed'];co=record['counters']
            record.update(user_cycles_per_request=co['cycles:u']/n,code_misses_per_request=co['L2I']/n)
        valid=rc==0 and not info['steady_errors'] and not info['steady_drops']
        services={}
        for key,(name,_,_) in TARGETS[family].items():
            cost=costs[name]
            valid &= abs(cost['achieved_rps']/rate-1)<.04 and cost['p99_ms']<100
            if key in pmu:valid &= pmu[key]['fully_scheduled'] and abs(pmu[key]['window']['achieved_rps']/rate-1)<.04
            services[key]=dict(cpu=cost,pmu=pmu.get(key))
        if ka:valid &= ka['matched_switches']>kb['matched_switches']
        result=dict(valid=bool(valid),family=family,services=services,pool=pc,
            whole_stack_cpu_us_per_request=sum(x['cpu_us'] for x in costs.values())/pc['completed'],
            pool_util_pct=100*pc['cpu_us']/(pc['wall_s']*1e6*len(measured)),
            load=info,kernel_before=kb,kernel_after=ka,kernel_detail_before=db,kernel_detail_after=da)
        c.save(out/'result.json',result)
        print(json.dumps(dict(out=str(out),valid=result['valid'],pool_util=result['pool_util_pct'],
            cpu={k:v['cpu']['cpu_us_per_request'] for k,v in services.items()},
            mpki={k:v['mpki'] for k,v in pmu.items()})),flush=True)
    except BaseException as error:
        c.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        c.stop(client)
        if fd is not None:os.close(fd)
        if loaded:subprocess.run(['rmmod','wake_prefetch'],check=True)
        if stack is not None:stack.close()
        if (out/'result.json').exists():old.compact(out)


def prepare():
    c.space();OUT.mkdir(exist_ok=True);TRACE.mkdir(exist_ok=True)
    records=[]
    for family,targets in TARGETS.items():
        for key in targets:
            for kind,path in [('base',baseline(family,key)),('reference',reference(family,key))]:
                local=c.ensure_local(path)
                assert local.is_file() and not local.is_symlink(),local
                records.append(dict(family=family,key=key,kind=kind,path=str(local),bytes=local.stat().st_size,sha256=c.sha(local)))
    c.save(OUT/'reference_artifacts.json',records)
    c.save(OUT/'protocol.json',dict(services=TARGETS,rate=RATE,tracing={'media':1,'social':.1},
        qualification='Baseline-only pools 4/6/8; require valid load and >=15% pool utilization; choose largest geometric-mean MPKI ratio relative to pool8 across family targets.',
        policy=POLICY,primary='user+kernel CPU per completed external request; per-service and full-stack reported separately',
        fullset='Individual service application screen, followed by simultaneous Media3/Social2 deployments with fresh-seed seven-block confirmation and exact-layout NOP controls.',
        kernel='Keep selected-next-task sched_switch timing. Compare budgets, emission spacing, ordering and split phases with matching NOP controls; no early wakeup.',
        constraints='Fresh full stacks and standard inputs, fixed platform; no timing overlap with build/decode/transfer; retain negatives and promptly remove unused generated artifacts.'))


def qualify():
    for family,targets in TARGETS.items():
        rows=[]
        for pool in (4,6,8):
            out=OUT/'qualification'/f'{family}_p{pool}'
            spec=dict(out=str(out),family=family,pool=pool,seed=12001,pmu=list(targets))
            manifest=out.with_suffix('.json');c.save(manifest,spec)
            platform(out,['python3',Path(__file__),'trial',str(manifest)])
            rows.append(dict(pool=pool,result=json.loads((out/'result.json').read_text())))
            c.save(OUT/(family+'_qualification.json'),rows)
        base=next(x['result'] for x in rows if x['pool']==8)
        import math
        for row in rows:
            r=row['result']
            row['score']=math.exp(sum(math.log(r['services'][k]['pmu']['mpki']/base['services'][k]['pmu']['mpki']) for k in targets)/len(targets))
        candidates=[r for r in rows if r['result']['valid'] and r['result']['pool_util_pct']>=15 and all(v['pmu']['mpki']>=5 for v in r['result']['services'].values())]
        assert candidates,(family,'no qualified point')
        selected=max(candidates,key=lambda x:x['score'])
        c.save(OUT/(family+'_selection.json'),dict(family=family,pool=selected['pool'],rate=RATE[family],score=selected['score'],rows=rows))
    print('QUALIFICATION_COMPLETE',flush=True)


def capture_family(spec):
    import capture_context
    os.environ['CLASS_B_PT_EVENT']=spec.get('pt_event','intel_pt//u')
    os.environ['CLASS_B_PT_AUX']=spec.get('pt_aux','16M')
    family=spec['family'];out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    root=Path(spec.get('trace_root',TRACE/family));root.mkdir(parents=True,exist_ok=False)
    stack=client=None;outputs=[]
    try:
        stack=start(out,family,{},spec['pool'])
        client=load(out/'load',family,RATE[family],13001,150)
        time.sleep(50)
        for phase in ('training','validation'):
            for key,(name,exe,_) in TARGETS[family].items():
                dest=root/key/phase;dest.parent.mkdir(exist_ok=True)
                old.SERVICE=key;old.NAME=name;old.EXE=exe
                outputs.append((dest,capture_context.capture(stack,dest)))
            if phase=='training':
                for key,(name,_,_) in TARGETS[family].items():
                    pid=stack.states[name]['State']['Pid']
                    group=str(Path(c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                    command=['perf','record','--no-buildid-cache','-e','cpu/event=0xc6,umask=0x03,config1=0x13/upp',
                        '-c','257','-m','4M','-a','-C','32-39','-G',group,'-o',str(root/key/'misses.data'),'--','sleep','10']
                    c.run(command,root/key/'misses_record.log')
                    message=(root/key/'misses_record.log').read_text().lower()
                    assert 'lost' not in message and 'truncated' not in message,message
        assert client.wait(timeout=100)==0;client=None
        info=json.loads((out/'load/load.json').read_text())
        assert not info['steady_errors'] and not info['steady_drops'];stack.check()
    finally:
        c.stop(client)
        if stack is not None:stack.close()
    c.save(out/'captured.json',dict(outputs=[dict(trace=str(d),syscalls=str(s)) for d,s in outputs],load=info))
    old.compact(out)


def decode_family(family,out,root):
    captured=json.loads((out/'captured.json').read_text())
    # Check all captures before expensive path reconstruction. Never suppress
    # overflow or lost-data events in the decoder.
    for row in captured['outputs']:
        dest=Path(row['trace']);meta=json.loads((dest/'capture_record.json').read_text())
        command=['perf','script','-i',str(dest/'pt.data'),'--symfs='+str(dest/'symfs'),
                 '--pid='+str(meta['pid']),'--itrace=e']
        c.save(dest/'quality_preflight.command.json',command)
        with (dest/'quality_preflight_errors.txt').open('w') as f,(dest/'quality_preflight.err').open('w') as err:
            subprocess.run(command,stdout=f,stderr=err,check=True)
        errors=(dest/'quality_preflight_errors.txt').read_text().strip()
        assert not errors,errors[:1000]
    for row in captured['outputs']:
        dest=Path(row['trace']);trace_media.decode(dest)
        cmd=json.loads((dest/'decode_command.json').read_text())+['--ns']
        c.save(dest/'context_branch_decode_command.json',cmd)
        with (dest/'branches.txt').open('w') as f,(dest/'context_branch_decode.err').open('w') as err:
            subprocess.run(cmd,stdout=f,stderr=err,check=True)
        cmd=['perf','script','--ns','-i',row['syscalls'],'-F','tid,time,event,trace,uregs']
        c.save(dest/'syscall_decode_command.json',cmd)
        with (dest/'syscall_context.txt').open('w') as f,(dest/'syscall_decode.err').open('w') as err:
            subprocess.run(cmd,stdout=f,stderr=err,check=True)
    for key in TARGETS[family]:
        dest=root/key
        with (dest/'misses.txt').open('w') as f,(dest/'misses_decode.err').open('w') as err:
            subprocess.run(['perf','script','--ns','-i',str(dest/'misses.data'),'-F','tid,time,ip'],stdout=f,stderr=err,check=True)


def candidates():
    from fullset_cleanup import cleanup
    records=json.loads((OUT/'candidates.json').read_text()) if (OUT/'candidates.json').exists() else {}
    build.T=TRACE
    for family,targets in TARGETS.items():
        selected=json.loads((OUT/(family+'_selection.json')).read_text())
        if all(k in records for k in targets):continue
        selection=OUT/(family+'_trace_selection.json')
        if selection.exists():
            trace_root=Path(json.loads(selection.read_text())['root'])
        else:
            for attempt in range(8):
                label=family if attempt==0 else f'{family}_retry{attempt}'
                out=OUT/'capture'/label;trace_root=TRACE/label
                if (out/'trace_rejection.json').exists():continue
                spec=dict(out=str(out),family=family,pool=selected['pool'],trace_root=str(trace_root))
                if attempt>=4:
                    spec.update(pt_event='intel_pt/mtc_period=6/u',pt_aux='64M',
                        reason='Repeated hardware overflow in default PT; reduce MTC packet density and enlarge AUX, retain branch tracing/TSC and identical zero-error gates')
                manifest=out.with_suffix('.json')
                if not (out/'captured.json').exists():
                    c.save(manifest,spec)
                    platform(out,['python3',Path(__file__),'capture_family',manifest])
                try:
                    decode_family(family,out,trace_root)
                except (AssertionError,subprocess.CalledProcessError) as error:
                    c.save(out/'trace_rejection.json',dict(error=repr(error),attempt=attempt,
                        reason='Decode/quality gate failed before training or candidate performance; reject the entire family capture batch'))
                    paths=[p for p in trace_root.rglob('*') if p.is_file() and not p.is_symlink() and
                           ('symfs' in p.parts or p.name in ('pt.data','branches.txt','syscall_context.txt','misses.txt','misses.data') or p.name.endswith('.syscall.data'))]
                    cleanup(paths,out/'trace_rejection_cleanup.json','Rejected capture batch; preserve decoder errors, quality records, commands, mapped hashes and settings before deleting raw/decoded copies')
                    continue
                c.save(selection,dict(root=str(trace_root),out=str(out),attempt=attempt,quality='All six/four captures passed zero-decoder-error gate'))
                break
            else:raise RuntimeError(f'{family}: eight capture batches failed quality gates')
        for key,(_,exe,_) in targets.items():
            if key in records:continue
            trace=trace_root/key;root=OUT/'plans'/key
            for name,threshold,horizon in [('strict',.8,128),('wide',.3,512)]:
                command=['taskset','-c','84-85','python3',Path(__file__).with_name('train_kernel_wake.py'),
                    trace/'training',trace/'validation','--out',root/name,'--threshold',threshold,
                    '--horizon',horizon,'--miss-samples',trace/'misses.txt']
                c.run(command,root/(name+'.log'),timeout=1800)
            plan=trace/'coverage.plan.json'
            command=['taskset','-c','84-85','python3',REPO/'flat_codegen/dsb_build/media/ws/ws_plan_pass.py',
                trace/'training/runs',trace/'training',plan,'--symfs',trace/'training/symfs',
                '--exe','/custom/'+exe,'--instrumentable',baseline(family,key).parent/'instrumentable.txt']
            for k,v in POLICY.items():command+=['--'+k.replace('_','-'),str(v)]
            c.run(command,root/'coverage_plan.log',timeout=1800)
            parsed=json.loads(plan.read_text());excluded=[]
            # This pre-existing external-only symbol cannot be directly anchored
            # in the service translation units. Exclude before performance tests.
            for site in parsed['sites'].values():
                kept=[]
                for target in site['t']:
                    if target[0]=='_ZN13jaegertracing7logging13consoleLoggerEv':excluded.append(target)
                    else:kept.append(target)
                site['t']=kept
            # Keep each original k allocation, including empty NOP-only sites.
            # Removing a site would invalidate the planner's shifted offsets.
            assert any(v['t'] for v in parsed['sites'].values());c.save(plan,parsed)
            c.save(root/'anchor_exclusions.json',dict(targets=excluded,reason='Unlinkable external-only direct anchor, determined before performance'))
            binary=build.build(key,'fullset_coverage',plan)
            c.save(root/'coverage.plan.json',parsed)
            c.save(root/'coverage_metadata.json',json.loads(Path(str(plan)+'.metadata.json').read_text()))
            records[key]=dict(family=family,binary=str(binary),nop=str(binary)+'.nop',
                sha256=c.sha(binary),nop_sha256=c.sha(str(binary)+'.nop'),plan=str(root/'coverage.plan.json'))
            c.save(OUT/'candidates.json',records)
            from fullset_cleanup import trace_done
            trace_done(trace)
    print('CANDIDATES_COMPLETE',flush=True)


def campaign():
    # The marker is written only after the last timed process has ended and
    # every platform context has been restored. No fixed process IDs are used.
    assert 'QUALIFICATION_COMPLETE' in (OUT/'qualification.log').read_text()
    c.space()
    module=REPO/'llvm_prefetchit/kernel/wake_prefetch'
    c.run(['taskset','-c','84-85','make','-C',module,'-j2'],OUT/'kernel_build.log')
    c.run(['taskset','-c','84-85',REPO/'profiling/.venv/bin/python','-m','pytest','-q',REPO/'llvm_prefetchit/tests/test_wake_kernel.py'],OUT/'kernel_unit.log')
    c.run(['taskset','-c','84-85','python3',module/'smoke.py','--out',OUT/'kernel_smoke'],OUT/'kernel_smoke.log')
    c.run(['python3', Path(__file__), 'candidates'], OUT/'candidates.log', timeout=14400)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','qualify','trial','capture_family','candidates','campaign']);p.add_argument('manifest',nargs='?',type=Path);a=p.parse_args()
    assert os.geteuid()==0
    def interrupt(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    if a.action in ('trial','capture_family'):globals()[a.action](json.loads(a.manifest.read_text()))
    else:globals()[a.action]()


if __name__=='__main__':main()
