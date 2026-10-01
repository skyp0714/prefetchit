#!/usr/bin/env python3
"""Keep compact endpoint time bins after timing, before raw request cleanup."""
import argparse
import gzip
import json
import math
from pathlib import Path
import signal

import dense_build as b


def retain_windows(out):
    raw=out/'load/requests.json.gz';result=out/'result.json'
    if not raw.exists() or not result.exists():return
    data=json.loads(result.read_text());pool=data['pool'];start=pool['start'];end=pool['end']
    with gzip.open(raw,'rt') as stream:samples=json.load(stream)
    count=max(1,round((end-start)/10));width=(end-start)/count
    buckets=[[] for _ in range(count)]
    for sent,finished in samples:
        if start<=finished<end:buckets[min(count-1,int((finished-start)/width))].append((finished-sent)*1000)
    windows=[]
    for i,values in enumerate(buckets):
        lo=start+i*width;hi=end if i==count-1 else start+(i+1)*width;values.sort()
        windows.append(dict(start=lo,end=hi,relative_start_s=lo-start,seconds=hi-lo,completed=len(values),
            achieved_rps=len(values)/(hi-lo),mean_ms=math.fsum(values)/len(values) if values else None,
            p99_ms=values[int(.99*(len(values)-1))] if values else None))
    assert sum(w['completed'] for w in windows)==pool['completed']
    b.save(out/'endpoint_windows.json',dict(valid=True,source_sha256=b.sha(__file__),raw_sha256=b.sha(raw),
        windows=windows,whole_roi=pool,limitation='Post-run aggregation of the same clean ROI; equal bins of approximately ten seconds within a trial are not independent trial replications. Dispatch-to-completion latency at fixed closed-loop concurrency.'))


def trial(spec):
    import fullset as h
    import media_system_study as system
    compact=h.old.compact
    def preserve(out):
        try:retain_windows(Path(out))
        except Exception as error:
            b.save(Path(out)/'endpoint_windows.json',dict(valid=False,error=repr(error),
                limitation='Post-run extraction failure does not invalidate or justify retrying the completed timing trial.'))
        finally:compact(out)
    h.old.compact=preserve
    system.trial(spec)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial']);p.add_argument('spec',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    trial(json.loads(a.spec.read_text()))
