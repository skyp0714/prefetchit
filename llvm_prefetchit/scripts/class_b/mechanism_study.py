#!/usr/bin/env python3
"""Same-layout opcode ablation with clean E2E and separate frontend selectors."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import dense_build as b

def opcode_variant(source, dest, kind):
    """Change only IT0 ModR/M bytes, using the retained audited patch map."""
    assert kind in ('it1','t1') and not dest.exists()
    audit=json.loads(source.with_suffix('.it0.json').read_text())
    assert b.sha(source)==audit['sha256'] and audit['same_layout']
    original=source.read_bytes();data=bytearray(original)
    changes=json.load(gzip.open(source.with_suffix('.it0_patches.json.gz'),'rt'))
    replacement={'it1':0x35,'t1':0x15}[kind]
    for row in changes:
        off=row['offset']
        assert data[off-2:off+1]==b'\x0f\x18\x3d'
        data[off]=replacement
    assert sum(a!=z for a,z in zip(data,original))==len(changes)
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent)
    dest.write_bytes(data);dest.chmod(source.stat().st_mode)
    record=dict(source=str(source),source_sha256=b.sha(source),path=str(dest),sha256=b.sha(dest),
        bytes=len(data),sites=len(changes),changed_bytes=len(changes),opcode=kind,same_layout=True,
        target_displacements_unchanged=True,patch_map=str(source.with_suffix('.it0_patches.json.gz')))
    if kind=='t1':assert record['sha256']==audit['source_sha256']
    b.save(dest.with_suffix('.opcode.json'),record)
    return record

def campaign(spec):
    import fullset as h
    import concurrency_study as c
    from fullset_study import summarize
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    arms=spec['arms'];names=list(arms);rows=[]
    orders=[names if block%2==0 else list(reversed(names)) for block in range(spec['blocks'])]
    b.save(out/'protocol.json',dict(spec,orders=orders,source_sha256=b.sha(__file__),
        primary='Clean whole-stack RPS and average/p99 latency, CPU/request; L2I and FE_L2 reported separately, no proxy promotion',
        exploratory=spec.get('exploratory',True),pmu='Separate selector windows, after clean ROI. No concurrent builds/decoding.'))
    for block,order in enumerate(orders):
        for arm in order:
            b.space(out);dest=out/f'{block:02d}_{arm}'
            setting=dict(out=str(dest),overrides=arms[arm]['overrides'],concurrency=4,pool=8,
                roi_s=60,seed=spec['seedbase']+block,pmu_event_sets=spec['pmu_event_sets'])
            p=dest.with_suffix('.json');b.save(p,setting)
            h.platform(dest,['python3',Path(c.__file__),'trial',p])
            r=json.loads((dest/'result.json').read_text())
            row=dict(block=block,arm=arm,valid=r['valid'],output=str(dest),
                metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],
                    stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']),
                achieved_rps=r['pool']['achieved_rps'],pool_util_pct=r['pool_util_pct'])
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
            assert row['valid'],'Operating failure retained, no performance-based retry'
    b.save(out/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupt(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupt)
    campaign(json.loads(a.spec.read_text()))
