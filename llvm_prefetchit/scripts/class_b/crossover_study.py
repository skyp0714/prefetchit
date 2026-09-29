#!/usr/bin/env python3
"""Same-stack hint crossover: stable HTTP connections, warmup after each switch.

Independent units are fresh stacks, not the repeated intervals within one
stack. Original uninstrumented ELF comparisons remain in fresh-stack studies.
"""
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time
import dense_build as b
import fullset as h
from lean_plan import read_image
from live_hints import LiveHints,transition
from concurrency_study import pmu_sets

def trial(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    event_sets=pmu_sets(spec);stat_s=spec.get('stat_s',6)
    b.save(out/'protocol.json',dict(**spec,source_sha256=b.sha(__file__),patcher_sha256=b.sha(Path(__file__).with_name('live_hints.py')),
        binary_sha256={arm:{key:b.sha(path) for key,path in paths.items()} for arm,paths in {'nop':spec['nop'],**spec['variants']}.items()},
        note='One fresh full stack, continuous C4 client and TCP connections. Stop/patch/verify/resume followed by 20s warmup; no PMU in clean intervals. First write makes all arms use the same private code pages.'))
    stack=client=None;images={};intervals=[];pmu=[]
    try:
        stack=h.start(out,'media',spec['nop'],8)
        for key,(name,exe,_) in h.TARGETS['media'].items():
            source=Path(spec['variants']['t1'][key]);sites=[r['site'] for r in read_image(source)['records'] if r['active'] and r['direct']]
            images[key]=LiveHints(stack.states[name]['State']['Pid'],Path(spec['nop'][key]),
                {arm:Path(paths[key]) for arm,paths in spec['variants'].items()},sites)
        b.save(out/'initial_cow.json',transition(images,'nop'))
        orders=spec['orders'];roi=spec.get('roi_s',45);warm=20
        seconds=65+sum(len(x)*(warm+roi+2+len(event_sets)*3*(stat_s+1)) for x in orders)
        load=out/'load';load.mkdir()
        cmd=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,'--concurrency','4','--seconds',str(seconds),'--seed',str(spec['seed'])]
        b.save(load/'command.json',cmd)
        with (load/'client.log').open('w') as log:client=subprocess.Popen(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if (load/'started.json').exists():break
            assert client.poll() is None;time.sleep(.1)
        else:raise RuntimeError('Client failed to start')
        time.sleep(50)
        for repeat,order in enumerate(orders):
            for arm in order:
                assert client.poll() is None;b.space(out)
                audit=transition(images,arm);b.save(out/f'transition_{repeat}_{arm}.json',audit)
                time.sleep(warm);a=stack.accounts();pb=h.old.pool_cpu(set(range(32,40)))
                time.sleep(roi);pa=h.old.pool_cpu(set(range(32,40)));z=stack.accounts()
                intervals.append(dict(repeat=repeat,arm=arm,accounts={k:h.c.diff_cpu(a[k],z[k]) for k in a},
                    pool=dict(start=pb['epoch'],end=pa['epoch'],wall_s=pa['monotonic']-pb['monotonic'],
                        cpu_us=sum(pa['ticks'][k]-v for k,v in pb['ticks'].items())*1e6/pb['clock_ticks'])))
                b.save(out/'intervals_pending.json',intervals)
                # Equal diagnostic durations in both orders retain symmetric
                # temporal positions. Every next clean ROI gets a new warmup.
                if event_sets:
                    from dense_causes import counters
                    for label,events in event_sets.items():
                        for key,(name,_,_) in h.TARGETS['media'].items():
                            pid=stack.states[name]['State']['Pid'];before=h.c.cpu(pid)
                            group=str(Path(before['path']).parent.relative_to('/sys/fs/cgroup'))
                            stem=out/f'{repeat}.{arm}.{key}.{label}'
                            command=['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,
                                '-a','-C','32-39','-G',group,'--','sleep',str(stat_s)]
                            b.save(Path(str(stem)+'.command.json'),command)
                            h.c.run(command,Path(str(stem)+'.log'))
                            entry=dict(arm=arm,repeat=repeat,service=key,label=label,**counters(Path(str(stem)+'.csv')),
                                window=h.c.diff_cpu(before,h.c.cpu(pid)))
                            assert entry['fully_scheduled'] and client.poll() is None
                            pmu.append(entry);b.save(out/'pmu_pending.json',pmu)
        # The client duration budgets slack for every perf window. With many
        # arms that retained slack can exceed a fixed 90-second idle wait.
        assert client.wait(timeout=seconds+60)==0;client=None;stack.check()
        info=json.loads((load/'load.json').read_text())
        with gzip.open(load/'requests.json.gz','rt') as f:samples=json.load(f)
        rows=[]
        for interval in intervals:
            pool=h.old.attach(interval['pool'],samples)
            costs={k:h.old.attach(v,samples) for k,v in interval['accounts'].items()}
            errors=sum(pool['start']<=t<pool['end'] for t in info['error_times'])
            rows.append(dict(arm=interval['arm'],repeat=interval['repeat'],valid=not errors and info['client_cpu_cores']<.8,
                metrics=dict(mean_ms=pool['mean_ms'],p99_ms=pool['p99_ms'],inverse_rps=1/pool['achieved_rps'],
                    stack_cpu=sum(v['cpu_us'] for v in costs.values())/pool['completed']),
                pool=pool,services=costs,roi_errors=errors,pool_util_pct=100*pool['cpu_us']/pool['wall_s']/8e6))
        for entry in pmu:
            h.old.attach(entry['window'],samples)
            entry['per_request']={k:v/entry['window']['completed'] for k,v in entry['counters'].items()}
        result=dict(valid=all(x['valid'] for x in rows) and not info['steady_errors'],rows=rows,pmu=pmu,load=info)
        b.save(out/'result.json',result);assert result['valid'],'Operating error retained; no silent retry'
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        for im in images.values():im.close()
        if stack is not None:stack.close()
        if (out/'result.json').exists():h.old.compact(out)

def campaign(spec):
    from fullset_study import summarize
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.save(out/'protocol.json',spec)
    rows=[];stack_rows=[];names=['nop',*spec['variants']]
    arms={k:({'controls':[x for x in spec.get('controls',['nop','t1','retarget']) if x in names and x!=k]} if k!='nop' else {}) for k in names}
    for block in range(spec.get('stacks',4)):
        dest=out/f'{block:02d}'
        rotation=block%len(names);order=names[rotation:]+names[:rotation]
        setting=dict(out=str(dest),nop=spec['nop'],variants=spec['variants'],seed=spec['seedbase']+block,
            roi_s=spec.get('roi_s',45),orders=[order,list(reversed(order))],
            pmu_event_sets=spec.get('pmu_event_sets',{}),stat_s=spec.get('stat_s',6))
        p=dest.with_suffix('.json');b.save(p,setting);h.platform(dest,['python3',Path(__file__),'trial',p])
        result=json.loads((dest/'result.json').read_text());assert result['valid']
        rows.extend(dict(stack=block,**x) for x in result['rows']);b.save(out/'rows.json',rows)
        for arm in names:
            rr=[r for r in result['rows'] if r['arm']==arm]
            # A single log-space arm mean per independent fresh stack.
            stack_rows.append(dict(block=block,arm=arm,valid=True,metrics={k:math.exp(statistics.mean(math.log(r['metrics'][k]) for r in rr)) for k in rr[0]['metrics']}))
        b.save(out/'stack_rows.json',stack_rows);b.save(out/'summary.json',summarize(stack_rows,arms))
        print(json.dumps(dict(stack=block,valid=True,summary=summarize(stack_rows,arms))),flush=True)
    b.save(out/'complete.json',dict(stacks=spec.get('stacks',4),intervals=len(rows),summary=summarize(stack_rows,arms)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial','campaign']);p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[a.action](json.loads(a.spec.read_text()))
