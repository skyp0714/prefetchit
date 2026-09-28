#!/usr/bin/env python3
"""Frozen, resumable screens and confirmation for low-inflation prefetch policies."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b


def campaign(spec):
    import fullset as h
    from fullset_study import summarize
    from dense_causes import ev,fe
    import dominator_study as d
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    b.save(out/'protocol.json',dict(spec,driver_sha256=b.sha(__file__),
        controls='Original baseline without hook; exact-layout NOP retains all gates and register pressure',
        pmu='After clean ROI only; no concurrent builds or decoding',
        timing='50s warmup then fixed clean ROI; no performance-based retries',
        decision='Exploratory screens; net benefit requires independent repeated confirmation'))
    events=','.join(['cycles:u','instructions:u',ev('L2I',0x24,0x24),fe('FE_L2',0x13),
        ev('ITLB_WALK',0x11,0x0e),ev('SWPF_MISS',0x24,0x28),ev('SWPF_HIT',0x24,0xc8)])
    rows=[];arms=spec['arms'];names=list(arms)
    for block in range(spec.get('blocks',2)):
        offset=2*block%len(names);order=names[offset:]+names[:offset]
        if block%2:order.reverse()
        for name in order:
            arm=arms[name];dest=out/f'{block:02d}_{name}'
            setting=dict(out=str(dest),overrides=arm['overrides'],flat=arm.get('flat',False),
                clock=arm.get('clock',True),clock_options=arm.get('clock_options',spec.get('clock_options',{})),
                concurrency=spec.get('concurrency',4),pool=8,roi_s=spec.get('roi_s',60),
                seed=spec['seedbase']+block,module=spec['module'])
            if block in spec.get('pmu_blocks',[0]):setting['pmu_events']=events
            p=dest.with_suffix('.json');b.save(p,setting)
            h.platform(dest,['python3',Path(d.__file__),'trial',p])
            r=json.loads((dest/'result.json').read_text())
            row=dict(block=block,arm=name,valid=r['valid'],output=str(dest),
                metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],
                    stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']),
                achieved_rps=r['pool']['achieved_rps'],pool_util_pct=r['pool_util_pct'])
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
            assert row['valid'],'Operating failure retained; no silent retry'
    b.save(out/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    campaign(json.loads(a.spec.read_text()))
