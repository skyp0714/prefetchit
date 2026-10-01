#!/usr/bin/env python3
"""Add code-request totals, stall periods and late IT hints to final diagnostics."""
import argparse
import json
from pathlib import Path
import signal

import dense_build as b
from dense_causes import counters
import fullset as h
import temporal_path_pmu as pmu

CACHE=pmu.diagnostic.EVENTS['cache']+',cpu/event=0x24,umask=0xe4,name=L2_CODE_ALL/u,cpu/event=0x80,umask=0x4,cmask=1,edge=1,name=ICACHE_STALL_PERIODS/u'
RECOVERY=pmu.EXTRA['recovery']+',cpu/event=0xc6,umask=0x3,config1=0xa,name=FE_LATE_SWPF/u'


def preflight(root):
    out=root/'final_pmu_preflight';out.mkdir(exist_ok=False);b.space(root)
    b.save(out/'protocol.json',dict(events=dict(cache=CACHE,recovery=RECOVERY),source=pmu.SOURCE,
        source_sha256=b.sha(__file__),purpose='Verify five simultaneous generic counters are fully scheduled before final service diagnostics.'))
    for label,events in [('cache',CACHE),('recovery',RECOVERY)]:
        stem=out/label
        b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'-a','-C','84','--',
            'taskset','-c','84','python3','-c','sum(i*i for i in range(10000000))'],Path(str(stem)+'.log'))
        row=counters(Path(str(stem)+'.csv'));assert row['fully_scheduled']
        b.save(Path(str(stem)+'.json'),row)
    b.save(out/'complete.json',dict(valid=True))


def trial(spec):
    root=Path(spec['root'])
    assert json.loads((root/'final_pmu_preflight/complete.json').read_text())['valid']
    pmu.diagnostic.EVENTS['cache']=CACHE
    pmu.EXTRA['recovery']=RECOVERY
    pmu.trial(dict(spec,extended_runner_sha256=b.sha(__file__),
        extended_event_note='Code-read lookups, retired true-miss tags and stall periods are distinct populations. Late-SWPF applies to PREFETCHIT, not ordinary T1 data hints. No accepted-prefetch or wrong-path attribution is claimed.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['preflight','trial','platform_trial']);parser.add_argument('path',type=Path)
    args=parser.parse_args();signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if args.action=='preflight':preflight(args.path)
    else:
        spec=json.loads(args.path.read_text())
        if args.action=='trial':trial(spec)
        else:h.platform(Path(spec['out']),['python3',__file__,'trial',args.path])
