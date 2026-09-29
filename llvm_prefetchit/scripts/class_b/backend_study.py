#!/usr/bin/env python3
"""Fresh-state full-stack comparisons with shared MongoDB ELF overrides."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import time
import dense_build as b
import fullset as h
from backend_prefetch import bind_mongodb,audit_backends,start_client
from dense_causes import counters
from fullset_study import summarize

MONITORED={**{k:v[0] for k,v in h.TARGETS['media'].items()},
    'mongo_user':'user-review-mongodb','mongo_movie':'movie-review-mongodb',
    'mongo_storage':'review-storage-mongodb','nginx':'nginx-web-server'}
EVENTS={
 'cache':'cycles:u,instructions:u,cpu/event=0x24,umask=0x24,name=L2I/u,cpu/event=0xc6,umask=0x3,name=FE_L2,config1=0x13/u,cpu/event=0x80,umask=0x4,name=ICACHE_DATA_STALL/u',
 'frontend':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_L1,config1=0x12/u,cpu/event=0x11,umask=0x10,name=ITLB_WALK_ACTIVE,cmask=1/u,cpu/event=0x9c,umask=0x1,name=FE_BUBBLES/u,cpu/event=0xa4,umask=0x1,name=SLOTS/u',
 'prefetch':'cycles:u,instructions:u,cpu/event=0x24,umask=0x28,name=SWPF_MISS/u,cpu/event=0x24,umask=0xc8,name=SWPF_HIT/u,cpu/event=0x40,umask=0x4,name=T1_T2_EXECUTED/u,cpu/event=0x48,umask=0x2,name=L1D_FB_FULL/u'}

def trial(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    extra=spec.get('extra_events',{});assert not set(extra)&set(EVENTS)
    event_sets=dict(EVENTS,**extra)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),
        backend_adapter_sha256=b.sha(Path(__file__).with_name('backend_prefetch.py')),monitored=MONITORED,events=event_sets,
        event_source='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/',
        event_limitation='At most four general events per window. L1D_FB_FULL measures data fill-buffer resource waits, not instruction-fetch queue occupancy. T1_T2_EXECUTED is speculative and includes original data-prefetch instructions.',
        scope='Fresh full Media stack for every arm; clean 60s ROI after 50s warmup, diagnostics afterwards. No long-crossover E2E.'))
    stack=client=None;pmu={}
    try:
        with bind_mongodb(out,spec.get('mongo_binary')):stack=h.start(out,'media',spec['overrides'],8)
        audit_backends(stack,out,spec.get('mongo_binary'))
        seconds=125+len(MONITORED)*len(event_sets)*6
        client=start_client(out,seconds,spec['seed']);time.sleep(50)
        a=stack.accounts();pb=h.old.pool_cpu(set(range(32,40)));time.sleep(60)
        pa=h.old.pool_cpu(set(range(32,40)));z=stack.accounts()
        for label,events in event_sets.items():
            pmu[label]={}
            for key,name in MONITORED.items():
                pid=stack.states[name]['State']['Pid'];before=h.c.cpu(pid)
                group=str(Path(before['path']).parent.relative_to('/sys/fs/cgroup'))
                stem=out/(key+'.'+label)
                command=['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'-a','-C','32-39','-G',group,'--','sleep','5']
                b.run(command,Path(str(stem)+'.log'))
                row=dict(**counters(Path(str(stem)+'.csv')),window=h.c.diff_cpu(before,h.c.cpu(pid)))
                assert row['fully_scheduled'] and client.poll() is None;pmu[label][key]=row
                b.save(out/'pmu_pending.json',pmu)
        assert client.wait(timeout=seconds+60)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        with gzip.open(out/'load/requests.json.gz','rt') as f:samples=json.load(f)
        for values in pmu.values():
            for row in values.values():
                h.old.attach(row['window'],samples)
                row['per_request']={k:v/row['window']['completed'] for k,v in row['counters'].items()}
        pool=h.old.attach(dict(start=pb['epoch'],end=pa['epoch'],wall_s=pa['monotonic']-pb['monotonic'],
            cpu_us=sum(pa['ticks'][k]-v for k,v in pb['ticks'].items())*1e6/pb['clock_ticks']),samples)
        costs={k:h.old.attach(h.c.diff_cpu(a[k],z[k]),samples) for k in a}
        errors=sum(pool['start']<=t<pool['end'] for t in info['error_times'])
        result=dict(valid=not info['steady_errors'] and info['client_cpu_cores']<.8,pmu={},pmu_extra=pmu,
            pool=pool,load=info,roi_errors=errors,whole_stack_cpu_us_per_request=sum(v['cpu_us'] for v in costs.values())/pool['completed'],
            pool_util_pct=100*pool['cpu_us']/pool['wall_s']/8e6,all_services=costs,
            services={key:costs[name] for key,name in MONITORED.items()})
        b.save(out/'result.json',result);assert result['valid'],'Invalid operation retained, no performance-based retry'
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)

def campaign(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    b.save(out/'protocol.json',dict(spec,monitored=MONITORED,source_sha256=b.sha(__file__),
        interpretation='Each independent block has fresh-stack arms with identical workload age; individual paired-log t95 intervals, no multiplicity correction.'))
    names=list(spec['arms']);rows=[]
    for block in range(spec['blocks']):
        order=names if block%2==0 else list(reversed(names))
        for arm in order:
            b.space(out);dest=out/f'{block:02d}_{arm}'
            setting=dict(spec['arms'][arm],out=str(dest),seed=spec['seedbase']+block)
            manifest=dest.with_suffix('.json');b.save(manifest,setting)
            h.platform(dest,['python3',Path(__file__),'trial',manifest])
            r=json.loads((dest/'result.json').read_text());assert r['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(dest),achieved_rps=r['pool']['achieved_rps'],
                pool_util_pct=r['pool_util_pct'],metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],
                    stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']))
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,spec['arms']))
            print(json.dumps(row),flush=True)
    b.save(out/'complete.json',dict(rows=len(rows),summary=summarize(rows,spec['arms'])))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial','campaign']);p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);globals()[a.action](json.loads(a.spec.read_text()))
