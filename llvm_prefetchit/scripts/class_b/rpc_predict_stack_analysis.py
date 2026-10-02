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
    b.save(follow/'target_analysis.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='targets'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);analyze(p.parse_args().root)
