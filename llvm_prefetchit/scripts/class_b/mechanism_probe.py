#!/usr/bin/env python3
"""Run serial calibrated code-prefetch probes under the platform wrapper."""
import argparse
import json
from pathlib import Path
import subprocess
import dense_build as b
from dense_causes import ev, fe, counters

def run(root, serialized=False, fixed=False):
    out=root/('probe_fixed' if fixed else 'probe_serialized' if serialized else 'probe');out.mkdir(exist_ok=False)
    binary=root/('prefetch_probe_serialized' if serialized else 'prefetch_probe')
    events=','.join(['cycles:u','instructions:u',ev('L2I',0x24,0x24),
                     ev('SWPF_MISS',0x24,0x28),fe('FE_L2',0x13),ev('ICACHE_DATA_STALL',0x80,4)])
    settings=[(demand,flush,lead) for demand,flush in [(0,1),(1,1),(1,0)]
              for lead in ([1024] if not demand or not flush else [0,64,256,1024])]
    if serialized:
        settings=[(d,f,l) for f in [2,3] for d in [0,1] for l in ([1024] if not d else [64,256])]
    if fixed:
        settings=[(d,f,256 if not d else 64) for f in [2,3,4,5] for d in [0,1]]
    source=Path(__file__).with_name('prefetch_probe_fixed.c' if fixed else 'prefetch_probe.c')
    b.save(out/'protocol.json',dict(iterations=100000,repeats=3,settings=settings,events=events,
        binary_sha256=({k:b.sha(root/('probe_fixed_'+k)) for k in ['nop','it0','it1','t1']} if fixed else b.sha(binary)),source_sha256=b.sha(source),
        limitation='CLFLUSH is an artificial all-level eviction. This calibrates event semantics and lead sensitivity, not application speedup. Timestamps include serialized call/return overhead. Lead is dependent IMUL iterations, not measured issue-to-fetch time.'))
    rows=[]
    for repeat in range(3):
        kinds=['nop','it0','it1','t1']
        if repeat%2:kinds.reverse()
        for demand,flush,lead in settings:
            for kind in kinds:
                b.space(root)
                if fixed:binary=root/('probe_fixed_'+kind)
                stem=out/f'{repeat}_{kind}_d{demand}_f{flush}_l{lead}'
                cmd=['perf','stat','-x,','-o',str(stem.with_suffix('.csv')),'-e',events,'--',
                     'taskset','-c','32',str(binary),kind,str(lead),str(demand),str(flush),'100000']
                b.save(stem.with_suffix('.command.json'),cmd)
                result=subprocess.run(cmd,check=True,text=True,capture_output=True)
                stem.with_suffix('.log').write_text(result.stderr)
                row=dict(repeat=repeat,**json.loads(result.stdout),**counters(stem.with_suffix('.csv')))
                assert row['fully_scheduled']
                rows.append(row);b.save(out/'rows.json',rows)
                print(json.dumps(row),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--serialized',action='store_true');p.add_argument('--fixed',action='store_true');a=p.parse_args();run(a.root,a.serialized,a.fixed)
