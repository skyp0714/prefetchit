#!/usr/bin/env python3
"""Locate new RPC target lines in earlier independent PEBS populations.

This is static overlap with sampled retired instructions, not accepted fills,
actual dynamic coverage, a fetch-deadline measurement, or a causal speedup bound.
"""
import argparse
import collections
import json
from pathlib import Path

import dense_build as b
from dense_cause_analysis import Code
from temporal_path_analysis import read
from rpc_future_study import PRIOR


def analyze(root):
    b.space(root);prepared=json.loads((root/'prepared_candidates.json').read_text())
    inventory=json.loads((root/'rpc_inventory.json').read_text());prior=json.loads((root/'references.json').read_text())['previous']
    aggregates={p:collections.Counter() for p in ('train','heldout','final')};services={};targets={}
    for key,info in inventory.items():
        added=json.loads(Path(prepared['rpc_stable']['builds'][key]['binary']+'.json').read_text())
        old=json.loads(Path(prepared['no_dso']['builds'][key]['binary']+'.json').read_text())
        new_lines={h['target']//64 for h in added['hints']};old_lines={h['target']//64 for h in old['hints']}
        code=Code(Path(info['source']));services[key]={}
        targets[key]=dict(added_hint_sites=len(added['hints']),distinct_new_bundle_lines=len(new_lines),
            lines_already_targeted_elsewhere=len(new_lines&old_lines),previously_untargeted_lines=len(new_lines-old_lines))
        for phase in ('train','heldout','final'):
            path=PRIOR/'profiles'/(phase+'_native')/key/'l2/observations.json.gz';data=read(path)
            expected=info['sha256'] if phase!='final' else b.sha(prior['arm']['overrides'][key])
            assert data['digests'].count(expected)==1,(key,phase)
            main=data['digests'].index(expected);counts=collections.Counter();weight=data['period']/data['requests'];locations=collections.Counter()
            for row in data['rows']:
                counts['all']+=1
                early=isinstance(row.get('age_us'),(int,float)) and 0<=row['age_us']<=20
                counts['early_all']+=early
                if row['dso']!=main:
                    counts['outside_main_elf']+=1;continue
                counts['main_elf']+=1
                length,asm,function=code.get(row['ip'])
                if not length:
                    counts['outside_original_instruction_boundaries']+=1;continue
                lines=set(range(row['ip']//64,(row['ip']+length-1)//64+1))
                if lines&new_lines:
                    counts['new_rpc_target_overlap']+=1;counts['early_new_rpc_target_overlap']+=early
                    locations[function]+=1
                    if lines&(new_lines-old_lines):counts['previously_untargeted_overlap']+=1
            weighted={k:v*weight for k,v in counts.items()};aggregates[phase].update(weighted)
            services[key][phase]=dict(samples=dict(counts),estimated_events_per_request=weighted,
                overlapping_functions=dict(locations.most_common(20)),source=str(path),source_sha256=b.sha(path),
                requests=data['requests'],period=data['period'])
        print(json.dumps(dict(service=key,targets=targets[key])),flush=True)
    summary={}
    for phase,c in aggregates.items():
        summary[phase]=dict(estimated_events_per_request=dict(c),new_rpc_target_overlap_pct=100*c['new_rpc_target_overlap']/c['all'],
            new_rpc_target_overlap_within_main_pct=100*c['new_rpc_target_overlap']/c['main_elf'],
            previously_untargeted_overlap_pct=100*c['previously_untargeted_overlap']/c['all'],
            early_new_rpc_target_overlap_pct=100*c['early_new_rpc_target_overlap']/c['early_all'],
            outside_main_elf_pct=100*c['outside_main_elf']/c['all'])
    result=dict(summary=summary,targets=targets,services=services,source_sha256=b.sha(__file__),
        scope='Nine app process populations, including their DSOs. Excludes MongoDB, kernel, Nginx, Redis, Memcached and Jaeger process counts. Each service normalized by its own request window before summing.',
        independence='Train selected targets; heldout was a separate baseline capture; final was an earlier full-DSO policy residual capture. Neither is a new rpc_stable trace or causal coverage validation.',
        limitation=__doc__+' Instruction spans include both touched cache lines, optimistically. PEBS retired-instruction L2 events are not unique raw code-read transactions. Secondary cache effects and target execution after other placements are not inferred.')
    b.save(root/'analysis/rpc_target_footprint.json',result)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();analyze(a.root)
