#!/usr/bin/env python3
"""Freeze earlier-lead and issue-thinning variants before independent testing."""
import argparse
import gzip
import json
from pathlib import Path
import dense_build as b
import fullset as h
from e2e_lbr import remove_generated
from lean_plan import read_image
from residual_retarget import observations,plan,lead_rows,patch,thin_plan,thin_patch

def run(root):
    assert (root/'retarget_screen/complete.json').exists()
    b.space(root)
    spec=json.loads((root/'retarget_training_spec.json').read_text())
    spec.update(out=str(root/'refine_training'),seed=70001)
    manifest=root/'refine_training_spec.json';b.save(manifest,spec)
    b.save(root/'refine_protocol.json',dict(source_sha256=b.sha(__file__),
        planner_sha256=b.sha(Path(__file__).with_name('residual_retarget.py')),
        policies=['protected128','protected512','retarget_thin'],
        lead_proxy='Retired completed LBR segment cycles, not actual prefetch lead time',
        training='Fresh exact-layout NOP capture; no measurements used to tune within the validation set',
        protection='Preserve old observed 0..8192-cycle coverage in the replacement gain calculation',
        thinning='Keep >=98% observed covered miss samples; no evidence about unsampled paths; same-size NOPs'))
    h.platform(root/'refine_training_run',['python3',Path(__file__).with_name('dense_causes.py'),'trial',manifest])
    builds={k:{} for k in ['protected128','protected512','retarget_thin']};records={}
    for service,exe in b.SERVICES.items():
        folder=root/'refine_training'/service;source=root/'builds/selected_t1'/service/exe
        b.space(root)
        rows,quality,code=observations(folder,source,0,8192,keep_ages=True,include_partial=True)
        obs=root/'refine_observations'/f'{service}.json.gz';obs.parent.mkdir(exist_ok=True)
        with gzip.open(obs,'wt') as f:json.dump(rows,f,separators=(',',':'))
        records[service]=dict(quality=quality,source_sha256=b.sha(source),
            trace_sha256=b.sha(folder/'l2/samples.txt'),observation_sha256=b.sha(obs),policies={})
        for age in [128,512]:
            kind=f'protected{age}';dest=root/'builds'/kind/service/exe
            result=plan(lead_rows(rows,age,8192),code.raw_targets,protected_rows=rows)
            result.update(min_age=age,max_age=8192,protected_old_coverage=True,
                source_sha256=b.sha(source),observation_sha256=b.sha(obs))
            b.save(dest.with_suffix('.plan.json'),result)
            patch(source,dest,result['changes'],result['source_sha256'])
            records[service]['policies'][kind]={k:result[k] for k in ['initial_covered','final_covered','samples','hints']}
            records[service]['policies'][kind]['changed_hints']=len(result['changes'])
            builds[kind][service]=str(dest)
        source=root/'builds/retarget_t1'/service/exe
        targets={r['site']:r['target'] for r in read_image(source)['records'] if r['active'] and r['direct']}
        result=thin_plan(rows,targets);dest=root/'builds/retarget_thin'/service/exe
        b.save(dest.with_suffix('.plan.json'),result);thin_patch(source,dest,result['drop'],b.sha(source))
        builds['retarget_thin'][service]=str(dest)
        records[service]['policies']['retarget_thin']={k:result[k] for k in ['original_covered','retained_covered','samples']}
        records[service]['policies']['retarget_thin'].update(remaining_hints=len(result['keep']),removed_hints=len(result['drop']))
        b.save(root/'refine_build.json',dict(builds=builds,records=records))
        # Decoded copies and temporary shared DSOs have served their purpose.
        paths=[folder/'l2/samples.txt',*[p for p in (folder/'dsos').rglob('*') if p.is_file() and not p.is_symlink()]]
        remove_generated(paths,folder/'analysis_cleanup.json',
            'Compact all-age observations, plans, sample quality, source and binary hashes retained; temporary decoded trace/DSO copies no longer needed.')
        print(json.dumps(dict(service=service,**records[service])),flush=True)
    screen=json.loads((root/'retarget_screen_spec.json').read_text())
    cross=dict(out=str(root/'crossover'),seedbase=71001,stacks=4,roi_s=40,stat_s=3,
        nop=spec['overrides'],variants=dict(t1=screen['arms']['selected_t1']['overrides'],
        retarget=screen['arms']['retarget_t1']['overrides'],**builds),
        pmu_event_sets={k:v for k,v in screen['pmu_event_sets'].items() if k in ['cache','frontend']},
        controls=['nop','t1','retarget'],
        interpretation='Exploratory frozen-policy screen. Four independent stacks; two reverse-order clean intervals per arm per stack. Original baseline comparisons are a separate fresh-stack experiment.')
    b.save(root/'crossover_spec.json',cross)
    b.save(root/'refine_complete.json',dict(builds=builds,observations_retained=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
