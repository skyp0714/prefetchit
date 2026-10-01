#!/usr/bin/env python3
"""Build graph/trace policies while retaining Mongo split75's existing hints."""
import argparse
import collections
import json
from pathlib import Path

import dense_build as b
from callpath_prefetch import stubs
from e2e_lbr import remove_generated
from temporal_path_study import PRIOR


def build(root,names):
    images=json.loads((root/'analysis/images.json').read_text())
    settings=json.loads((PRIOR/'settings.json').read_text())
    original=json.loads((root/'arms.json').read_text())['original']
    legacy=json.loads(Path(settings['mongo_split75']+'.json').read_text())
    mongo_sha=b.sha(settings['mongo_original']);native={b.sha(v):k for k,v in settings['references'].items()}
    library_users=collections.defaultdict(dict)
    for path in sorted((root/'profiles/train_native').glob('*/catalog.json')):
        for name,entry in json.loads(path.read_text()).items():
            if '.so' in Path(name).name:library_users[entry['sha256']][path.parent.name]=name
    records={}
    for name in names:
        selected=json.loads((root/'analysis'/(name+'_selection.json')).read_text());groups=collections.defaultdict(list)
        for choice in selected['choices']:groups[choice['source_sha']].append(choice)
        groups.setdefault(mongo_sha,[])
        arm=json.loads(json.dumps(original));nop=json.loads(json.dumps(original));arm['libraries']={};nop['libraries']={}
        builds={};exclusions=[];outputs=[]
        try:
            for digest,choices in groups.items():
                if digest not in native and digest!=mongo_sha and digest not in library_users:
                    exclusions.append(dict(sha=digest,reason='Mongo-only DSO lacks a binding path in this candidate deployment adapter'));continue
                source=Path(images[digest]['binary']);b.space(root)
                calls={}
                if digest==mongo_sha:
                    calls={row['site']:dict(row,targets=list(row['targets'])) for row in legacy['plan']['calls']}
                kept=[];skipped=[]
                for choice in choices:
                    site=choice['site'];row=calls.setdefault(site,dict(choice['call'],targets=[],got_targets=[]))
                    row.setdefault('got_targets',[])
                    if choice['kind']=='local' and any(v//64==choice['target']//64 for v in row['targets']):
                        skipped.append(dict(site=site,target=choice['target'],reason='Existing retained Mongo hint already targets this line'));continue
                    if len(row['targets'])+len(row['got_targets'])>=8:
                        skipped.append(dict(site=site,target=choice['target'],reason='Eight-hint site cap including retained hints'));continue
                    if choice['kind']=='local':row['targets'].append(choice['target'])
                    else:
                        row['got_targets'].append({k:choice[k] for k in ('got','addend','target','target_sha','anchor')})
                    kept.append(choice)
                # Prefer one GOT load for adjacent hints using the same anchor.
                for row in calls.values():
                    if row.get('got_targets'):row['got_targets'].sort(key=lambda t:(t['got'],t['addend']))
                if not calls:continue
                plan=dict(sha256=digest,calls=[calls[k] for k in sorted(calls)])
                out=root/'builds'/name/digest/source.name
                b.save(root/'plans'/name/(digest+'.json'),dict(plan=plan,source=str(source),retained_mongo_hints=digest==mongo_sha,
                    kept_choices=kept,skipped=skipped,source_sha256=b.sha(__file__),builder_sha256=b.sha(stubs.__file__)))
                record=stubs.build(source,plan,out)
                outputs.extend([out,Path(str(out)+'.nop')])
                builds[digest]=dict(binary=str(out),nop=str(out)+'.nop',sha256=record['sha256'],nop_sha256=record['nop_sha256'],
                    extra_instruction_bytes=record['extra_instruction_bytes'],sites=len(calls),new_hints=len(kept),
                    cross_hints=sum(c['kind']=='cross' for c in kept),hints=len(record['hints']))
                if digest in native:
                    arm['overrides'][native[digest]]=str(out);nop['overrides'][native[digest]]=str(out)+'.nop'
                elif digest==mongo_sha:
                    arm['mongo_binary']=str(out);nop['mongo_binary']=str(out)+'.nop'
                else:
                    for key,target in library_users[digest].items():
                        arm['libraries'].setdefault(key,{})[target]=str(out)
                        nop['libraries'].setdefault(key,{})[target]=str(out)+'.nop'
                print(json.dumps(dict(stage='built',variant=name,image=source.name,**builds[digest])),flush=True)
            arm['controls']=['original','mongo',name+'_nop'];nop['controls']=['original']
            records[name]=dict(arm=arm,nop=nop,builds=builds,excluded=exclusions,selection_sha256=b.sha(root/'analysis'/(name+'_selection.json')))
            b.save(root/'candidates'/name/'prepared.json',records[name])
        except BaseException as error:
            b.save(root/'candidates'/name/'failure.json',dict(error=repr(error),completed=builds,excluded=exclusions))
            unused=[p for p in outputs if p.exists()]
            if unused:remove_generated(unused,root/'candidates'/name/'failure_cleanup.json','Candidate preparation failed; plans, exact patches, hashes and exclusion reason retained.')
            raise
    b.save(root/'prepared_candidates.json',records)
    return records


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--variants',nargs='+',default=['path64','path512','pathwide']);a=p.parse_args()
    build(a.root,a.variants)
