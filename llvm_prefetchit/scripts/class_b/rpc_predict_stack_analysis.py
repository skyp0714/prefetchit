#!/usr/bin/env python3
"""Bounded-symbol and fixed-line coverage of the frozen stack-context policy."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import subprocess

import dense_build as b
from dense_cause_analysis import Code
from rpc_predict_symbols import Symbols
from rpc_route_study import load
from temporal_path_analysis import read


def analyze(root):
    follow=root/'stack_followup';model=load(follow/'model.json')
    protocol=load(follow/'protocol.json');train=Path(protocol['training'])
    assert b.sha(train)==protocol['training_sha256']
    with gzip.open(train,'rt') as stream:data=json.load(stream)
    main=data['names'].index('/custom/ComposeReviewService')
    source=Path(load(root/'arms.json')['full']['overrides']['compose'])
    assert b.sha(source)==data['catalog'][data['names'][main]]['sha256']
    code=Code(source);lookup=Symbols(root);lines={t//64 for c in model['choices'] for t in c['targets']}
    counts=collections.Counter();records=[]
    for row in data['rows']:
        counts['all']+=1
        if row['address'][0]!=main:continue
        ip=row['address'][1];counts['main']+=1;length=code.get(ip)[0]
        counts['fixed_start_lines']+=ip//64 in lines
        counts['fixed_end_lines']+=bool(length) and (ip+length-1)//64 in lines
    for choice in model['choices']:
        for target,samples in zip(choice['targets'],choice['samples']):
            original,address,layers=lookup.original(source,target)
            symbol=lookup.lookup(original,address)
            records.append(dict(method=choice['method'],issuer=choice['site'],target=target,
                line=target//64,selected_context_samples=samples,symbol=symbol,patch_lineage=layers))
    pretty=subprocess.check_output(['c++filt'],input='\n'.join(r['symbol'] for r in records)+'\n',text=True).splitlines()
    for row,name in zip(records,pretty):row['demangled']=name
    result=dict(source_sha256=b.sha(__file__),training_sha256=b.sha(train),
        unique_target_lines=len(lines),static_hints=len(records),training_counts=dict(counts),
        selected_rpc_context_samples=sum(r['selected_context_samples'] for r in records),targets=records,
        interpretation='Frozen selection described after construction; no target changes. Training coverage is not held-out miss reduction or a runtime prediction-accuracy estimate. Selected RPC/context counts and unconditional fixed-line counts are different populations. Bounded ELF symbols only; shared stubs retain ambiguity.')
    if (follow/'all_measurements_complete.json').exists():
        old=load(Path(str(source)+'.json'))['patches']
        new=load(Path(load(follow/'prepared.json')['binary']+'.json'))['patches']
        def inside(ip,patches):return any(p['stub']<=ip<max(p['terminal_jumps'])+5 for p in patches)
        profiles={}
        for name in ('full','stack'):
            directory=follow/'profiles'/name/'compose/l2';data=read(directory/'observations.json.gz')
            main=data['names'].index('/custom/ComposeReviewService');counts=collections.Counter()
            for row in data['rows']:
                dso,ip=row['dso'],row['ip'];weight=data['period']/data['requests']
                kind='unmapped' if dso<0 else 'dso' if dso!=main else 'new_stub' if name=='stack' and inside(ip,new) else 'incumbent_stub' if inside(ip,old) else 'main_original'
                counts[kind]+=weight
            timeline=load(directory/'timeline.json')
            profiles[name]=dict(per_request=dict(counts),time_bins=timeline['bins'],
                migrated_pct=timeline['migrated_pct'],median_run_us=timeline['median_run_us'],median_off_us=timeline['median_off_us'])
        result['heldout_profiles']=profiles
        result['heldout_limit']='One perturbing Compose capture per arm; locations are not causal attribution of cache pollution or a whole-system miss estimate. New stub ranges come from preserved patch records; no retired executable is needed.'
    b.save(follow/'target_analysis.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='targets'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);analyze(p.parse_args().root)
