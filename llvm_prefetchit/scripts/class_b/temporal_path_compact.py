#!/usr/bin/env python3
"""Charge for opening call stubs so target hints share fewer branch sites."""
import argparse
import json
from pathlib import Path

import dense_build as b
import temporal_path_analysis as model


def prepare(root,base,site_overhead=4,tag=None,respect_retained_capacity=False):
    from temporal_path_build import build
    from temporal_path_common import PRIOR
    name=tag or base+'_compact';assert name.replace('_','').isalnum();b.space(root)
    images=model.load_original_images(root)
    anchors={(row['source'],row['target']):row['entries'] for row in json.loads((root/'analysis/got_anchors.json').read_text())['anchors']}
    histogram=json.loads((root/'analysis/call_frequency.json').read_text())
    frequency={(row['sha'],row['site']):row['per_request'] for row in histogram['rates']}
    settings=json.loads((PRIOR/'settings.json').read_text());legacy=json.loads(Path(settings['mongo_split75']+'.json').read_text())
    opened={(legacy['source_sha256'],row['site']) for row in legacy['plan']['calls']}
    caps={(legacy['source_sha256'],row['site']):8-len(row['targets']) for row in legacy['plan']['calls']} if respect_retained_capacity else None
    train,quality=model.collect(root,'train',images,anchors,64,16384)
    chosen=model.choose(train,frequency,histogram['floor'],per_site=8,min_gain=3,goal=.90,
        site_overhead=site_overhead,opened_sites=opened,site_caps=caps)
    del train
    heldout,hq=model.collect(root,'heldout',images,anchors,64,16384)
    chosen.update(train_quality=quality,heldout_quality=hq,heldout=model.assess(heldout,chosen['choices']),
        minimum=64,maximum=16384,source_sha256=b.sha(__file__),selector_sha256=b.sha(model.__file__),
        rule=f'Same original train-only targets/lead/budget/90% coverage goal as pathwide. Cost adds {site_overhead} local-hint equivalents when opening a new stub; existing retained Mongo stubs are already open. Refresh discounted priorities after each newly opened site. Heldout is assessment only; fresh E2E determines utility.',
        respect_retained_capacity=respect_retained_capacity)
    for choice in chosen['choices']:
        source=images[choice['source_sha']];target=images[choice['target_sha']]
        choice.update(call=source.calls[choice['site']],caller=source.function(choice['site']),
            target_function=target.function(choice['target']),
            relation=source.dominance(choice['site'],choice['target']) if source.sha==target.sha else 'cross_dso_trace')
    b.save(root/'analysis'/(name+'_selection.json'),chosen)
    prior=json.loads((root/'analysis'/(base+'_selection.json')).read_text())
    worthwhile=chosen['sites']<prior['sites'] and chosen['covered']/chosen['samples']>=prior['covered']/prior['samples']-.02
    decision=dict(eligible=worthwhile,sites_before=prior['sites'],sites_after=chosen['sites'],hints=chosen['hints'],
        train_coverage=chosen['covered']/chosen['samples'],heldout_coverage=chosen['heldout']['quality']['covered']/chosen['heldout']['quality']['samples'],
        rule='Build only if training-site count decreases and training coverage loses at most two percentage points; no heldout or E2E selection at this gate.')
    b.save(root/'candidates'/name/'model_decision.json',decision)
    if not worthwhile:return None
    retained=json.loads((root/'prepared_candidates.json').read_text());result={}
    try:result=build(root,[name])
    finally:b.save(root/'prepared_candidates.json',dict(retained,**result))
    result[name]['arm']['controls']=['original','mongo',base,name+'_nop']
    b.save(root/'candidates'/name/'prepared.json',result[name])
    b.save(root/'prepared_candidates.json',dict(retained,**result))
    print(json.dumps(dict(stage='compact_built',variant=name,**decision)),flush=True)
    return name


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--base',required=True)
    parser.add_argument('--site-overhead',type=float,default=4);parser.add_argument('--tag');parser.add_argument('--respect-retained-capacity',action='store_true')
    args=parser.parse_args();prepare(args.root,args.base,args.site_overhead,args.tag,args.respect_retained_capacity)
