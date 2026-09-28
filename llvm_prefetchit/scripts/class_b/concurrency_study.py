#!/usr/bin/env python3
"""Fresh-stack concurrency scaling at fixed CPU resources, with scheduler evidence."""
import argparse
import gzip
import json
import os
from pathlib import Path
import signal
import subprocess
import time

def schedstat(text,cpus):
    lines=text.splitlines();version=int(lines[0].split()[1])
    if version!=15:raise ValueError('Only audited Linux schedstat version 15 is supported')
    result={}
    for line in lines:
        fields=line.split()
        if not fields or not fields[0].startswith('cpu'):continue
        cpu=int(fields[0][3:])
        if cpu not in cpus:continue
        if len(fields)!=10:raise ValueError('Unexpected per-CPU schedstat layout')
        result[cpu]=dict(run_ns=int(fields[7]),wait_ns=int(fields[8]),timeslices=int(fields[9]))
    if set(result)!=set(cpus):raise ValueError('Missing CPU scheduler counters')
    return result


def snapshot(cpus):
    return dict(monotonic=time.monotonic(),epoch=time.time(),
                counters=schedstat(Path('/proc/schedstat').read_text(),cpus))


def trial(spec):
    import fullset as h
    h.c.space();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    cpus=set(range(32,32+spec.get('pool',8)));roi=spec.get('roi_s',60)
    sysctl=Path('/proc/sys/kernel/sched_schedstats');before_setting=sysctl.read_text()
    h.c.save(out/'protocol.json',dict(**spec,mode='Fixed-resource closed-loop concurrency scaling',
        process_instances='One instance per Media service in every arm; internal async/server threading model unchanged',
        schedstat_before=before_setting,source_sha256=h.c.sha(__file__),
        loader_sha256=h.c.sha(Path(__file__).with_name('closed_loop_load.py')),
        interpretation='Concurrency > CPU count is not by itself proof of runnable oversubscription; report measured aggregate runqueue wait.',
        scheduler_source='https://www.kernel.org/doc/html/v6.8/scheduler/sched-stats.html'))
    stack=client=None
    try:
        sysctl.write_text('1\n')
        stack=h.start(out,'media',spec['overrides'],len(cpus))
        load=out/'load';load.mkdir()
        command=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,
            '--concurrency',str(spec['concurrency']),'--seconds',str(65+roi+(24 if spec.get('pmu_events') else 0)),
            '--seed',str(spec['seed'])]
        h.c.save(load/'command.json',command)
        with (load/'client.log').open('w') as log:
            client=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if (load/'started.json').exists():break
            assert client.poll() is None;time.sleep(.1)
        else:raise RuntimeError('Client failed to start')
        time.sleep(50);assert client.poll() is None
        accounts_before=stack.accounts();pool_before=h.old.pool_cpu(cpus);schedule_before=snapshot(cpus)
        time.sleep(roi)
        schedule_after=snapshot(cpus);pool_after=h.old.pool_cpu(cpus);accounts_after=stack.accounts()
        pmu={}
        if spec.get('pmu_events'):
            from dense_causes import counters
            for key,(name,_,_) in h.TARGETS['media'].items():
                pid=stack.states[name]['State']['Pid'];before=h.c.cpu(pid)
                group=str(Path(before['path']).parent.relative_to('/sys/fs/cgroup'))
                command=['perf','stat','-x,','-o',str(out/(key+'.pmu.csv')),'-e',spec['pmu_events'],
                         '-a','-C','32-39','-G',group,'--','sleep','8']
                h.c.run(command,out/(key+'.pmu.log'))
                pmu[key]=dict(**counters(out/(key+'.pmu.csv')),window=h.c.diff_cpu(before,h.c.cpu(pid)))
                assert pmu[key]['fully_scheduled']
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=json.loads((load/'load.json').read_text())
        with gzip.open(load/'requests.json.gz','rt') as f:samples=json.load(f)
        for entry in pmu.values():
            h.old.attach(entry['window'],samples)
            entry['per_request']={k:v/entry['window']['completed'] for k,v in entry['counters'].items()}
        pool=h.old.attach(dict(start=pool_before['epoch'],end=pool_after['epoch'],
            wall_s=pool_after['monotonic']-pool_before['monotonic'],
            cpu_us=sum(pool_after['ticks'][k]-v for k,v in pool_before['ticks'].items())*1e6/pool_before['clock_ticks']),samples)
        costs={k:h.old.attach(h.c.diff_cpu(accounts_before[k],accounts_after[k]),samples) for k in accounts_before}
        duration=schedule_after['monotonic']-schedule_before['monotonic']
        delta={k:sum(schedule_after['counters'][cpu][k]-schedule_before['counters'][cpu][k] for cpu in cpus)
               for k in ('run_ns','wait_ns','timeslices')}
        assert all(v>=0 for v in delta.values())
        errors=sum(pool['start']<=t<pool['end'] for t in info['error_times'])
        # CPython's GIL can saturate a single core despite a four-core affinity.
        result=dict(valid=not info['steady_errors'] and info['client_cpu_cores']<.8,pmu=pmu,
            concurrency=spec['concurrency'],pool=pool,load=info,
            roi_errors=errors,error_fraction=errors/(pool['completed']+errors),
            whole_stack_cpu_us_per_request=sum(v['cpu_us'] for v in costs.values())/pool['completed'],
            pool_util_pct=100*pool['cpu_us']/pool['wall_s']/1e6/len(cpus),
            scheduler=dict(before=schedule_before,after=schedule_after,delta=delta,
                average_running_tasks=delta['run_ns']/1e9/duration,
                average_waiting_runnable_tasks=delta['wait_ns']/1e9/duration,
                runqueue_wait_us_per_request=delta['wait_ns']/1000/pool['completed'],
                limitation='All tasks scheduled on the selected CPUs, not only service threads; wait accumulation may include boundary-crossing waits'),
            services={k:costs[v[0]] for k,v in h.TARGETS['media'].items()})
        h.c.save(out/'result.json',result)
    except BaseException as error:
        h.c.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        try:
            if stack is not None:stack.close()
        finally:
            sysctl.write_text(before_setting)
            h.c.save(out/'scheduler_restoration.json',dict(before=before_setting,after=sysctl.read_text(),restored=sysctl.read_text()==before_setting))
        if (out/'result.json').exists():h.old.compact(out)


def campaign(spec):
    import fullset as h
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);h.c.save(out/'protocol.json',spec)
    rows=[];counts=spec.get('concurrencies',[1,2,4,8,16,32])
    for block in range(spec.get('blocks',3)):
        order=counts[2*block:]+counts[:2*block]
        if block%2:order.reverse()
        for count in order:
            dest=out/f'{block:02d}_c{count}'
            setting=dict(out=str(dest),concurrency=count,seed=spec['seedbase']+block,
                         overrides=spec['overrides'],pool=8,roi_s=spec.get('roi_s',60))
            manifest=dest.with_suffix('.json');h.c.save(manifest,setting)
            h.platform(dest,['python3',Path(__file__),'trial',manifest])
            result=json.loads((dest/'result.json').read_text())
            row=dict(block=block,concurrency=count,output=str(dest),valid=result['valid'],
                metrics={k:result['pool'][k] for k in ('achieved_rps','mean_ms','p50_ms','p95_ms','p99_ms')},
                pool_util_pct=result['pool_util_pct'],error_fraction=result['error_fraction'],
                client_cpu_cores=result['load']['client_cpu_cores'],
                average_waiting_runnable_tasks=result['scheduler']['average_waiting_runnable_tasks'],
                runqueue_wait_us_per_request=result['scheduler']['runqueue_wait_us_per_request'])
            rows.append(row);h.c.save(out/'rows.json',rows);print(json.dumps(row),flush=True)
    h.c.save(out/'complete.json',dict(rows=len(rows),all_valid=all(r['valid'] for r in rows)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['trial','campaign']);parser.add_argument('manifest',type=Path)
    args=parser.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[args.action](json.loads(args.manifest.read_text()))
