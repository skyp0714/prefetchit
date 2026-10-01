#!/usr/bin/env python3
"""Separate service-wide cache, translation, recovery and backend diagnostics."""
import argparse
import json
from pathlib import Path
import signal

import dense_build as b
from dense_causes import counters
import fullset as h
from media_library_study import bind_libraries
import media_system_study as system
import split_hybrid_study as diagnostic


SOURCE='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/'
EXTRA={
    'recovery':'cycles:u,instructions:u,branches:u,branch-misses:u,cpu/event=0xad,umask=0x1,name=RECOVERY_CYCLES/u,cpu/event=0xad,umask=0x80,name=CLEAR_RESTEER_CYCLES/u',
    'l1':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,config1=0x12,name=FE_L1/u,cpu/event=0x11,umask=0x20,name=ITLB_STLB_HIT/u,cpu/event=0x11,umask=0xe,name=ITLB_WALK_COMPLETED/u,cpu/event=0x83,umask=0x4,name=ICACHE_TAG_STALL/u',
    'prefetch':diagnostic.EVENTS['prefetch'],
}


def preflight(root):
    out=root/'extra_pmu_preflight';out.mkdir(exist_ok=False);b.space(root)
    b.save(out/'protocol.json',dict(events=EXTRA,source=SOURCE,source_sha256=b.sha(__file__)))
    for label,events in EXTRA.items():
        stem=out/label
        b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'-a','-C','84','--',
            'taskset','-c','84','python3','-c','sum(i*i for i in range(10000000))'],Path(str(stem)+'.log'))
        row=counters(Path(str(stem)+'.csv'));assert row['fully_scheduled']
        b.save(Path(str(stem)+'.json'),row)
    b.save(out/'complete.json',dict(valid=True))


def trial(spec):
    system.configure();system.audited_start(spec)
    diagnostic.MONITORED=system.MONITORED
    if spec['suite']=='core':
        diagnostic.EVENTS={k:v for k,v in diagnostic.EVENTS.items() if k in ('cache','topdown','front','memory')}
    else:
        assert spec['suite']=='extra'
        diagnostic.EVENTS={**diagnostic.EVENTS,**EXTRA}
        spec=dict(spec,service_event_sets=list(EXTRA))
    spec=dict(spec,diagnostic=True,diagnostic_roi_s=5,diagnostic_source=SOURCE,collect_request_traces=True,
        event_note='Recovery includes machine clears. Clear-resteer counts the subsequent gap until first uop issue. These overlapping event populations do not partition request latency or prove BTB absence.')
    with bind_libraries(Path(spec['out']),spec):diagnostic.trial(spec)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial','platform_trial','preflight']);p.add_argument('path',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if a.action=='preflight':preflight(a.path)
    else:
        spec=json.loads(a.path.read_text())
        if a.action=='trial':trial(spec)
        else:h.platform(Path(spec['out']),['python3',__file__,'trial',a.path])
