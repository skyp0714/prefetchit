#!/usr/bin/env python3
"""After baseline qualification, validate isolation and prepare traced candidates."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import social_headroom as h


def platform(name,command):
    h.c.space()
    wrapper=h.LEGACY/'run_platform.py'
    h.c.run(['python3',wrapper,'--out',h.OUT/('platform_'+name),'--cpus','16-19,32-43',*command],
            h.OUT/(name+'.log'),timeout=2400)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qualification-pid',type=int,required=True)
    a=p.parse_args()
    while True:
        message=(h.OUT/'qualification.log').read_text()
        if 'QUALIFICATION_COMPLETE' in message:
            break
        try:os.kill(a.qualification_pid,0)
        except ProcessLookupError:raise RuntimeError('qualification stopped before completion')
        time.sleep(10)
    rows=[]
    for path in sorted((h.OUT/'qualification').glob('*/result.json')):
        result=json.loads(path.read_text())
        settings=json.loads((path.parent/'protocol.json').read_text())
        if result['valid'] and result['pool_util_pct']>=15 and result['pmu']['mpki']>=5:
            rows.append(dict(pool=settings['pool'],rate=settings['rate'],mpki=result['pmu']['mpki'],
                             path=str(path),pool_util_pct=result['pool_util_pct']))
    assert rows,'No valid high-MPKI regime'
    selected=max(rows,key=lambda x:x['mpki'])
    h.c.save(h.OUT/'selection.json',dict(selected=selected,candidates=rows,
        rule='Highest measured baseline shared L2 code MPKI among predeclared valid operating points; chosen before PF results'))
    runner=h.REPO/'llvm_prefetchit/scripts/class_b/social_headroom.py'
    platform('alone',['python3',runner,'--out',h.OUT/'qualification/alone_selected',
                      '--pool',str(selected['pool']),'--rate',str(selected['rate']),'--alone'])
    alone=json.loads((h.OUT/'qualification/alone_selected/result.json').read_text())
    assert alone['valid'] and selected['mpki']/alone['pmu']['mpki']>=2
    h.c.save(h.OUT/'isolation_gate.json',dict(alone_mpki=alone['pmu']['mpki'],
        shared_mpki=selected['mpki'],inflation=selected['mpki']/alone['pmu']['mpki']))
    capture=h.REPO/'llvm_prefetchit/scripts/class_b/capture_context.py'
    platform('context_capture',['python3',capture,'--out',h.OUT/'capture',
        '--trace-out',h.TRACE,'--pool',str(selected['pool']),'--rate',str(selected['rate'])])
    trainer=h.REPO/'llvm_prefetchit/scripts/class_b/train_kernel_wake.py'
    for weighting in ('probability','miss'):
        command=['python3',trainer,h.TRACE/'training',h.TRACE/'validation',
                 '--out',h.OUT/('kernel_'+weighting),'--threshold','.8','--horizon','128']
        if weighting=='miss':command+=['--miss-samples',h.TRACE/'misses.txt']
        h.c.run(command,h.OUT/('train_'+weighting+'.log'),timeout=1200)
    h.c.save(h.OUT/'context_ready.json',dict(selection=selected,trace=str(h.TRACE),
                                          status='Trace quality and training completed; no kernel performance claims'))
    print('CONTEXT_CANDIDATES_READY',flush=True)


if __name__=='__main__':main()
