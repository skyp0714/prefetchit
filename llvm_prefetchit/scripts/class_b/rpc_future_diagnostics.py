#!/usr/bin/env python3
"""Separate request-normalized PMU windows for the frozen RPC policies."""
import argparse
import json
from pathlib import Path
import signal

import backend_study
import dense_build as b
import fullset as h
from media_library_study import bind_libraries
import media_system_study as system
import split_hybrid_study as diagnostic


def trial(spec):
    system.configure();system.audited_start(spec)
    diagnostic.MONITORED={k:v for k,v in system.MONITORED.items() if k!='nginx'}
    diagnostic.EVENTS.update(translation=backend_study.EVENTS['frontend'],prefetch=backend_study.EVENTS['prefetch'])
    spec=dict(spec,diagnostic_roi_s=5,service_event_sets=['cache','translation','topdown','prefetch'],
              purpose='PMU diagnostics only; this five-second endpoint is never used in clean speedup inference.')
    with bind_libraries(Path(spec['out']),spec):diagnostic.trial(spec)


def campaign(spec):
    root=Path(spec['root']);out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__)))
    for block,order in enumerate(spec['orders']):
        for name in order:
            b.space(root);dest=out/f'{block:02d}_{name}';manifest=dest.with_suffix('.json')
            b.save(manifest,dict(spec['arms'][name],out=str(dest),seed=spec['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(dest,['python3',__file__,'trial',manifest])
            assert json.loads((dest/'result.json').read_text())['valid']
            print(json.dumps(dict(stage='diagnostic_complete',block=block,arm=name)),flush=True)
    b.save(out/'complete.json',dict(valid=True,trials=sum(map(len,spec['orders']))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial','campaign']);p.add_argument('spec',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    globals()[a.action](json.loads(a.spec.read_text()))
