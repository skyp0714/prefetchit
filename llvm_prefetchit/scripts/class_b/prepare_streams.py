#!/usr/bin/env python3
"""Build service-scope accuracy/coverage variants from fresh baseline PT.

Dependencies and baseline linkage are unchanged; this stage does not claim
library-internal instrumentation. Run only between measurement stages.
"""
import json
from pathlib import Path

import social_headroom as h
import build


def main():
    h.c.space()
    trace=h.TRACE/'training'
    assert (h.OUT/'capture/completed.json').exists()
    root=h.c.S/'social_build/usertimeline'
    configs={
        'accuracy':dict(d=4,dmax=16,k=4,kmerge=8,gap_k=8,post_call=8,p_min=.8,merge_policy='support'),
        'balanced':dict(d=8,dmax=32,k=8,kmerge=16,gap_k=16,post_call=16,p_min=.65,merge_policy='support'),
        'coverage':dict(d=8,dmax=48,k=12,kmerge=32,gap_k=32,post_call=24,p_min=.5,merge_policy='byte-efficiency'),
    }
    results={}
    for name,config in configs.items():
        arm='headroom_'+name
        plan=root/(arm+'.plan.json')
        assert not plan.exists()
        command=['python3',h.REPO/'flat_codegen/dsb_build/media/ws/ws_plan_pass.py',
            trace/'runs',trace,plan,'--symfs',trace/'symfs','--exe','/custom/'+h.EXE,
            '--instrumentable',root/'base/instrumentable.txt','--site-p','.8','--max-calls','1.5']
        for key,value in config.items():
            command+=['--'+key.replace('_','-'),str(value)]
        h.c.run(command,root/(arm+'.plan.log'))
        parsed=json.loads(plan.read_text())
        assert parsed['sites']
        try:
            binary=build.build(h.SERVICE,arm,plan)
            results[name]=dict(binary=str(binary),nop=str(binary)+'.nop',
                binary_sha256=h.c.sha(binary),nop_sha256=h.c.sha(str(binary)+'.nop'),
                plan=str(plan),plan_sha256=h.c.sha(plan),config=config,
                sites=len(parsed['sites']),targets=sum(len(v['t']) for v in parsed['sites'].values()))
        except Exception as error:
            results[name]=dict(build_failed=True,error=repr(error),plan=str(plan),config=config)
        h.c.save(h.OUT/'stream_candidates.json',results)
    print(json.dumps(results,indent=2),flush=True)


if __name__=='__main__':main()
