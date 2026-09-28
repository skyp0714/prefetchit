#!/usr/bin/env python3
"""Whole-request tests of CFG/call-graph prefetch and scheduler-age decay."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import dense_build as b

def trial(spec):
    import concurrency_study as c
    module=Path(spec['module']);assert not Path('/sys/module/prefetchit_sched_clock').exists()
    b.space(Path(spec['out']).parent)
    command=['insmod',str(module),'flat='+str(int(spec.get('flat',False)))]
    allowed={'dense_us','medium_us','sparse_us','dense_begin_us','medium_begin_us','sparse_begin_us'}
    for name,value in spec.get('clock_options',{}).items():
        assert name in allowed and type(value) is int and 0 <= value <= 1000
        command.append(f'{name}={value}')
    enabled=spec.get('clock',True)
    if enabled:subprocess.run(command,check=True)
    old=os.environ.get('CLASS_B_SCHED_CLOCK')
    os.environ['CLASS_B_SCHED_CLOCK']='1' if enabled else '0'
    try:
        c.trial(spec)
    finally:
        if old is None:os.environ.pop('CLASS_B_SCHED_CLOCK',None)
        else:os.environ['CLASS_B_SCHED_CLOCK']=old
        if enabled:subprocess.run(['rmmod','prefetchit_sched_clock'],check=True)
        b.save(Path(spec['out'])/'clock_restoration.json',dict(unloaded=True,enabled=enabled,command=command if enabled else [],module_sha256=b.sha(module)))

def campaign(root, blocks=2):
    import fullset as h
    from fullset_study import summarize
    from dense_causes import ev,fe
    events=','.join(['cycles:u','instructions:u',ev('L2I',0x24,0x24),fe('FE_L2',0x13),
        ev('ITLB_WALK',0x11,0x0e),ev('SWPF_MISS',0x24,0x28),ev('SWPF_HIT',0x24,0xc8)])
    arms=json.loads((root/'arms.json').read_text())
    arms['flat']=dict(overrides=arms['dom_decay']['overrides'],controls=['base'],flat=True)
    out=root/'screen_c4';out.mkdir(exist_ok=False)
    protocol=dict(blocks=blocks,concurrency=4,pool=8,roi_s=60,warmup_s=50,seedbase=46001,
        primary='Whole-stack throughput, dispatch-to-completion mean/p99, total CPU per successful request',
        arms=arms,intervals_us=[10,20,40],eligible_group_fractions=[1,.5,.25,0],
        note='Fractions are static group eligibility, not guaranteed dynamic issue-rate fractions. Flat retains the gate but all deadlines are UINT64_MAX.',
        selection='Exploratory screen. Promote to independent confirmation only if both mean and CPU improve over base and matched NOP, p99 regression <=2%.',
        controls='Original baseline has no clock hook. Exact-layout NOP retains the clock, all gates and register pressure.',
        pmu_after_clean_roi_first_block=events,source_sha256=b.sha(__file__))
    b.save(out/'protocol.json',protocol)
    rows=[];names=['base','dom_decay_nop','dom_decay','flat']
    for block in range(blocks):
        order=names if block%2==0 else list(reversed(names))
        for name in order:
            dest=out/f'{block:02d}_{name}'
            spec=dict(out=str(dest),overrides=arms[name]['overrides'],flat=arms[name].get('flat',False),clock=name!='base',
                concurrency=4,pool=8,roi_s=60,seed=46001+block,module=str(root/'kernel_build/prefetchit_sched_clock.ko'))
            if block==0:spec['pmu_events']=events
            p=dest.with_suffix('.json');b.save(p,spec)
            h.platform(dest,['python3',Path(__file__),'trial',p])
            r=json.loads((dest/'result.json').read_text())
            row=dict(block=block,arm=name,valid=r['valid'],output=str(dest),
                metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],
                    stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']),
                achieved_rps=r['pool']['achieved_rps'],pool_util_pct=r['pool_util_pct'])
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True);assert row['valid']
    b.save(out/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['trial','campaign']);p.add_argument('path',type=Path)
    p.add_argument('--blocks',type=int,default=2);a=p.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    if a.action=='trial':trial(json.loads(a.path.read_text()))
    else:campaign(a.path,a.blocks)
