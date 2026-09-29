#!/usr/bin/env python3
"""Map frontend costs across active services, outside clean end-to-end timing."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import subprocess
import time
import dense_build as b
import fullset as h
from dense_causes import counters

EVENTS={
 'cache':'cycles:u,instructions:u,cpu/event=0x24,umask=0x24,name=L2I/u,cpu/event=0xc6,umask=0x3,name=FE_L2,config1=0x13/u,cpu/event=0x80,umask=0x4,name=ICACHE_DATA_STALL/u',
 'frontend':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_L1,config1=0x12/u,cpu/event=0x11,umask=0x10,name=ITLB_WALK_ACTIVE,cmask=1/u,cpu/event=0x9c,umask=0x1,name=FE_BUBBLES/u,cpu/event=0xa4,umask=0x1,name=SLOTS/u'}

def trial(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(**spec,source_sha256=b.sha(__file__),events=EVENTS,
        selection='Measure services using >=0.5% of clean whole-stack CPU; retain all service CPU costs and omitted fraction.',
        scope='Cgroup user-mode PMU on CPUs 32-39. Counters after clean ROI; each service normalized to completed requests in its own window.'))
    stack=client=None;windows=[]
    try:
        stack=h.start(out,'media',spec['overrides'],8)
        load=out/'load';load.mkdir();seconds=100+len(stack.states)*len(EVENTS)*6
        command=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,'--concurrency','4','--seconds',str(seconds),'--seed',str(spec['seed'])]
        b.save(load/'command.json',command)
        with (load/'client.log').open('w') as log:client=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if (load/'started.json').exists():break
            assert client.poll() is None;time.sleep(.1)
        else:raise RuntimeError('Client did not start')
        time.sleep(50);a=stack.accounts();time.sleep(30);z=stack.accounts()
        costs={k:h.c.diff_cpu(a[k],z[k]) for k in a};total=sum(c['cpu_us'] for c in costs.values())
        selected=sorted([k for k,v in costs.items() if v['cpu_us']>=.005*total],key=lambda k:-costs[k]['cpu_us'])
        b.save(out/'service_selection.json',dict(selected=selected,omitted=[k for k in costs if k not in selected],
            selected_cpu_fraction=sum(costs[k]['cpu_us'] for k in selected)/total,all_costs=costs))
        for name in selected:
            b.space(out);pid=stack.states[name]['State']['Pid']
            (out/(name+'.maps')).write_text(Path(f'/proc/{pid}/maps').read_text())
            for label,events in EVENTS.items():
                before=h.c.cpu(pid);group=str(Path(before['path']).parent.relative_to('/sys/fs/cgroup'))
                stem=out/(name+'.'+label)
                command=['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'-a','-C','32-39','-G',group,'--','sleep','5']
                b.run(command,Path(str(stem)+'.log'))
                entry=dict(service=name,label=label,window=h.c.diff_cpu(before,h.c.cpu(pid)),**counters(Path(str(stem)+'.csv')))
                assert entry['fully_scheduled'] and client.poll() is None
                windows.append(entry);b.save(out/'windows_pending.json',windows)
        assert client.wait(timeout=300)==0;client=None;stack.check()
        info=json.loads((load/'load.json').read_text());assert not info['steady_errors'] and info['client_cpu_cores']<.8
        with gzip.open(load/'requests.json.gz','rt') as f:samples=json.load(f)
        for value in costs.values():h.old.attach(value,samples)
        for entry in windows:
            h.old.attach(entry['window'],samples)
            entry['per_request']={k:v/entry['window']['completed'] for k,v in entry['counters'].items()}
        b.save(out/'result.json',dict(valid=True,costs=costs,windows=windows,load=info,
            limitation='One diagnostic baseline capture, no causal performance comparison or direct request-critical-path attribution.'))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);trial(json.loads(a.spec.read_text()))
