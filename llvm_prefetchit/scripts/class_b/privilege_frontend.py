#!/usr/bin/env python3
"""Separate user/kernel frontend costs on the entire shared workload CPU pool."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import time
import dense_build as b
import fullset as h
from backend_prefetch import start_client
from dense_causes import counters
from stack_frontend import EVENTS as ORIGINAL_EVENTS

DECODE_EVENTS='cycles:u,instructions:u,cpu/event=0x79,umask=0x8,name=DSB_UOPS/u,cpu/event=0x79,umask=0x4,name=MITE_UOPS/u,cpu/event=0x75,umask=0x1,name=DECODED/u,cpu/event=0xad,umask=0x40,name=UNKNOWN_BRANCH_CYCLES,config1=0x7/u'
EVENTS=dict(ORIGINAL_EVENTS,
    branch='cycles:u,instructions:u,branches:u,branch-misses:u,cpu/event=0xc6,umask=0x3,name=FE_ITLB,config1=0x14/u',
    decode=DECODE_EVENTS)


def events(label,privilege):
    return EVENTS[label].replace(':u',':'+privilege).replace('/u','/'+privilege)


def run(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),events=EVENTS,
        scope='Original full Media C4. CPU-wide counters on 32-39, separately filtered to user/kernel. Includes scheduler/interrupt work on that pool; excludes work on other CPUs.',
        ordering='Two repeats, reversed privilege and group order in repeat 2; every PMU window has its own request denominator.',
        limitation='Diagnostic attribution, not a prefetch E2E trial or critical-path causal bound. Frontend events overlap; their counts cannot be subtracted into exclusive causes.',
        event_source='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/'))
    for privilege in ['u','k']:
        for label in EVENTS:
            stem=out/('preflight_'+privilege+'_'+label)
            b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events(label,privilege),'-a','-C','84','--','sleep','.2'],Path(str(stem)+'.log'))
            row=counters(Path(str(stem)+'.csv'));assert row['fully_scheduled']
    stack=client=None;windows=[]
    try:
        stack=h.start(out,'media',spec['overrides'],8)
        client=start_client(out,95+len(EVENTS)*2*2*5,spec['seed']);time.sleep(50)
        a=stack.accounts();time.sleep(30);z=stack.accounts()
        costs={name:h.c.diff_cpu(a[name],z[name]) for name in a}
        order=[(p,label) for p in ['u','k'] for label in EVENTS]
        for repeat in range(2):
            for privilege,label in (order if not repeat else list(reversed(order))):
                before=h.old.pool_cpu(set(range(32,40)))
                stem=out/f'{repeat}_{privilege}_{label}'
                b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events(label,privilege),'-a','-C','32-39','--','sleep','4'],Path(str(stem)+'.log'))
                after=h.old.pool_cpu(set(range(32,40)));row=counters(Path(str(stem)+'.csv'))
                assert row['fully_scheduled'] and client.poll() is None
                windows.append(dict(repeat=repeat,privilege=privilege,label=label,**row,
                    window=dict(start=before['epoch'],end=after['epoch'],wall_s=after['monotonic']-before['monotonic'],
                        cpu_us=sum(after['ticks'][k]-v for k,v in before['ticks'].items())*1e6/before['clock_ticks'])))
                b.save(out/'windows_pending.json',windows)
        assert client.wait(timeout=220)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text());assert not info['steady_errors'] and info['client_cpu_cores']<.8
        with gzip.open(out/'load/requests.json.gz','rt') as f:samples=json.load(f)
        for value in costs.values():h.old.attach(value,samples)
        for row in windows:
            h.old.attach(row['window'],samples)
            row['per_request']={k:v/row['window']['completed'] for k,v in row['counters'].items()}
        b.save(out/'result.json',dict(valid=True,windows=windows,costs=costs,load=info))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('spec',type=Path);args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);run(json.loads(args.spec.read_text()))
