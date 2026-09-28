#!/usr/bin/env python3
"""Serial cause diagnostics at measured concurrency, outside clean latency ROI.

Separate speculative request, translation, predictor and precise retired-event
populations. Different FRONTEND_RETIRED selectors share an MSR and are always
measured separately. No recorder overlaps a clean latency ROI.
"""
import argparse
import collections
import csv
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

import fullset as h

SOURCE='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/'

def ev(name,event,umask,extra=''):
    return f'cpu/event=0x{event:x},umask=0x{umask:x},name={name}{extra}/u'

def fe(name,selector):
    return ev(name,0xc6,3,f',config1=0x{selector:x}')

SETS={
 'cache':[ev('L2I',0x24,0x24),ev('L2_CODE_ALL',0x24,0xe4),ev('SWPF_MISS',0x24,0x28),ev('SWPF_HIT',0x24,0xc8)],
 'translation':[ev('ITLB_STLB_HIT',0x11,0x20),ev('ITLB_WALK',0x11,0x0e),ev('ITLB_WALK_ACTIVE',0x11,0x10,',cmask=1'),ev('ICACHE_DATA_STALL',0x80,4)],
 'retired_l2':[fe('FE_L2',0x13),ev('BACLEARS',0x60,1),'branches:u','branch-misses:u'],
 'retired_l1':[fe('FE_L1',0x12),ev('ICACHE_TAG_STALL',0x83,4)],
 'retired_itlb':[fe('FE_ITLB',0x14),ev('CLEAR_RESTEER',0xad,0x80)],
 'unknown_branch':[fe('FE_UNKNOWN',0x17),ev('BR_INDIRECT',0xc4,0x80),ev('MISP_INDIRECT',0xc5,0x80)],
}
SAMPLES={'l2':fe('fe_l2',0x13)[:-2]+',period=257/upp',
         'unknown':fe('fe_unknown',0x17)[:-2]+',period=257/upp',
         'instructions':'cpu/event=0xc0,umask=0,period=100003,name=inst/upp'}


def counters(path):
    values={};percent={}
    for row in csv.reader(path.open()):
        if len(row)<5 or row[0].startswith('#'):continue
        value=float(row[0]);name=row[2]
        try:float(row[3]);index=4
        except ValueError:index=5
        values[name]=value;percent[name]=float(row[index])
    assert values['instructions:u']>0 and values['cycles:u']>0
    return dict(counters=values,scheduled_pct=percent,fully_scheduled=all(x>=99.99 for x in percent.values()))


def snapshot_dsos(pid,dest,overrides):
    maps=Path(f'/proc/{pid}/maps').read_text();(dest/'maps.txt').write_text(maps)
    result={};dest.joinpath('dsos').mkdir()
    for line in maps.splitlines():
        fields=line.split(None,5)
        if len(fields)<6 or 'x' not in fields[1] or not fields[5].startswith('/'):continue
        name=fields[5]
        if name in result:continue
        if name.startswith('/custom/'):
            source=next(Path(v) for k,v in overrides.items() if h.TARGETS['media'][k][1]==Path(name).name)
            local=source
        else:
            source=Path(f'/proc/{pid}/root'+name)
            local=dest/'dsos'/Path(name).name
            assert not local.exists();shutil.copyfile(source,local)
        result[name]=dict(local=str(local),sha256=h.c.sha(source),bytes=source.stat().st_size)
    h.c.save(dest/'dsos.json',result)
    (dest/'smaps.txt').write_text(Path(f'/proc/{pid}/smaps').read_text())


def decode(dest):
    command=['perf','script','-i',str(dest/'perf.data'),'-F','pid,ip,dso,brstack','--show-lost-events']
    h.c.save(dest/'decode_command.json',command)
    with (dest/'samples.txt').open('w') as output,(dest/'decode.log').open('w') as err:
        subprocess.run(command,stdout=output,stderr=err,check=True)
    types=collections.Counter()
    with (dest/'quality.log').open('w') as err:
        proc=subprocess.Popen(['perf','script','-D','-i',str(dest/'perf.data')],stdout=subprocess.PIPE,stderr=err,text=True)
        for line in proc.stdout:
            match=re.search(r'PERF_RECORD_(\w+)',line)
            if match:types[match[1]]+=1
        assert proc.wait()==0
    h.c.save(dest/'record_types.json',dict(types))
    assert not any(types[k] for k in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))
    from e2e_lbr import remove_generated
    remove_generated([dest/'perf.data'],dest/'raw_cleanup.json','Decoded samples active for miss/branch/coverage analysis; quality, command and raw hash retained')


def trial(spec):
    h.c.space();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    sample_events=spec.get('sample_events',SAMPLES)
    h.c.save(out/'protocol.json',dict(**spec,events=SETS,samples=sample_events,event_source=SOURCE,
        scope='Target user-mode cgroups; all threads. Samples diagnose retired instructions; L2I counts speculative requests.',
        limitation='Unknown-branch and code-miss captures are independent populations, not paired causal observations. LBR records retired taken branches, not FDIP/BTB state.',
        source_sha256=h.c.sha(__file__),roi='30 seconds before PMU, dispatch-to-completion',
        hashes={k:h.c.sha(v) for k,v in spec['overrides'].items()}))
    captures=[];windows=[];stack=client=None
    seconds=50+30+len(h.TARGETS['media'])*(spec.get('rounds',2)*len(SETS)*spec.get('stat_s',5)+len(sample_events)*spec.get('sample_s',8) if spec.get('sample',True) else spec.get('rounds',2)*len(SETS)*spec.get('stat_s',5))+30
    try:
        stack=h.start(out,'media',spec['overrides'],8)
        for key,(name,exe,_) in h.TARGETS['media'].items():
            dest=out/key;dest.mkdir();pid=stack.states[name]['State']['Pid']
            snapshot_dsos(pid,dest,spec['overrides'])
        load=out/'load';load.mkdir()
        cmd=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,'--concurrency',str(spec['concurrency']),'--seconds',str(seconds),'--seed',str(spec['seed'])]
        h.c.save(load/'command.json',cmd)
        with (load/'client.log').open('w') as log:
            client=subprocess.Popen(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if (load/'started.json').exists():break
            assert client.poll() is None;time.sleep(.1)
        else:raise RuntimeError('Load startup failed')
        time.sleep(50);before=stack.accounts();pb=h.old.pool_cpu(set(range(32,40)))
        time.sleep(30);pa=h.old.pool_cpu(set(range(32,40)));after=stack.accounts()
        for repeat in range(spec.get('rounds',2)):
            keys=list(h.TARGETS['media'])
            if repeat%2:keys.reverse()
            for key in keys:
                name=h.TARGETS['media'][key][0];pid=stack.states[name]['State']['Pid']
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                events=list(SETS.items())
                if repeat%2:events.reverse()
                for label,evs in events:
                    h.c.space();dest=out/key/f'{repeat:02d}_{label}';dest.mkdir()
                    cmd=['perf','stat','-x,','-o',str(dest/'counts.csv'),'-e',','.join(['instructions:u','cycles:u',*evs]),'-a','-C','32-39','-G',group,'--','sleep',str(spec.get('stat_s',5))]
                    a=h.c.cpu(pid);h.c.run(cmd,dest/'stat.log');z=h.c.cpu(pid)
                    co=counters(dest/'counts.csv');assert co['fully_scheduled'],dest
                    windows.append(dict(service=key,repeat=repeat,label=label,output=str(dest),window=h.c.diff_cpu(a,z),**co))
                    h.c.save(out/'counter_windows_pending.json',windows)
                    assert client.poll() is None
        if spec.get('sample',True):
            for key,(name,exe,_) in h.TARGETS['media'].items():
                pid=stack.states[name]['State']['Pid'];group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                for label,event in sample_events.items():
                    h.c.space();dest=out/key/label;dest.mkdir()
                    cmd=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M','-e',event,'-j','any,u','-G',group,'-o',str(dest/'perf.data'),'--','sleep',str(spec.get('sample_s',8))]
                    a=h.c.cpu(pid);h.c.run(cmd,dest/'record.log');z=h.c.cpu(pid)
                    h.c.save(dest/'window.json',h.c.diff_cpu(a,z));captures.append(dest)
                    assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
                    assert client.poll() is None
        rc=client.wait(timeout=120);client=None;stack.check()
        info=json.loads((load/'load.json').read_text())
        with gzip.open(load/'requests.json.gz','rt') as f:requests=json.load(f)
        for row in windows:h.old.attach(row['window'],requests)
        for dest in captures:
            window=json.loads((dest/'window.json').read_text());h.old.attach(window,requests);h.c.save(dest/'window.json',window)
        costs={k:h.old.attach(h.c.diff_cpu(before[k],after[k]),requests) for k in before}
        pool=h.old.attach(dict(start=pb['epoch'],end=pa['epoch'],wall_s=pa['monotonic']-pb['monotonic'],cpu_us=sum(pa['ticks'][k]-v for k,v in pb['ticks'].items())*1e6/pb['clock_ticks']),requests)
        result=dict(valid=rc==0 and not info['steady_errors'] and info['client_cpu_cores']<.8,pool=pool,
            whole_stack_cpu_us_per_request=sum(v['cpu_us'] for v in costs.values())/pool['completed'],
            pool_util_pct=100*pool['cpu_us']/pool['wall_s']/8e6,load=info,
            counters=windows,services={k:costs[v[0]] for k,v in h.TARGETS['media'].items()})
        h.c.save(out/'result.json',result);assert result['valid']
    except BaseException as error:
        h.c.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        if (out/'result.json').exists():h.old.compact(out)
    for dest in captures:decode(dest)
    h.c.save(out/'complete.json',dict(captures=[str(p) for p in captures],windows=len(windows)))


def campaign(spec):
    root=Path(spec['out']);root.mkdir(exist_ok=False);h.c.save(root/'protocol.json',spec)
    for arm in spec['order']:
        setting=dict(out=str(root/arm),overrides=spec['arms'][arm],concurrency=spec.get('concurrency',4),seed=45001,
            sample=spec.get('sample',True),rounds=spec.get('rounds',2),stat_s=5,sample_s=8)
        h.c.save(root/(arm+'.json'),setting)
        h.platform(root/arm,['python3',Path(__file__),'trial',root/(arm+'.json')])
        print(json.dumps(dict(arm=arm,completed=True)),flush=True)
    h.c.save(root/'complete.json',dict(arms=spec['order']))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['trial','campaign']);p.add_argument('manifest',type=Path);a=p.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[a.action](json.loads(a.manifest.read_text()))
