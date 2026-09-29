#!/usr/bin/env python3
"""Validate a frozen continuation-aware placement after the hybrid screen."""
import argparse
import json
from pathlib import Path
import signal
import struct
import backend_study
import balanced_backend
import dense_build as b
import fullset as h
from callpath_prefetch import stubs
from dense_cause_analysis import Code,category
from e2e_lbr import remove_generated
from fullset_study import summarize
from mechanism_report import evaluate

MONITORED={k:v for k,v in backend_study.MONITORED.items() if k.startswith('mongo_')}


def prepare(parent,root):
    root.mkdir(exist_ok=False);b.space(root)
    source=parent/'split_coverage_plan'
    protocol=json.loads((source/'protocol.json').read_text())
    selected=json.loads((source/'selection.json').read_text())
    summary=json.loads((source/'plan_complete.json').read_text())
    assert not summary['compiled'] and protocol['target_model']
    assert b.sha(Path(__file__).with_name('callpath_refine.py'))==protocol['source_sha256']
    assert b.sha(stubs.__file__)==protocol['builder_sha256']
    reference=Path(protocol['reference']);assert b.sha(reference)==protocol['reference_sha256']
    b.save(root/'protocol.json',dict(source=str(source),selection_sha256=b.sha(source/'selection.json'),
        source_protocol=protocol,summary=summary,runner_sha256=b.sha(__file__),
        rule='Build the already frozen train-only continuation-aware 75% selection. No new selection or tuning from the balanced/hybrid E2E outcomes.'))
    code=Code(reference);raw=reference.read_bytes();elf=stubs.Elf(raw);targets={}
    for row in selected['choices']:targets.setdefault(row['site'],[]).append(row['target'])
    calls=[]
    for site,lines in sorted(targets.items()):
        length,asm,function=code.get(site)
        assert length==5 and category(asm)=='direct_call'
        offset=elf.offset(site,5,True);assert raw[offset]==0xe8
        callee=site+5+struct.unpack_from('<i',raw,offset+1)[0]
        assert callee in code.instructions and all(target in code.instructions for target in lines)
        calls.append(dict(site=site,callee=callee,targets=lines,expected=raw[offset:offset+5].hex(),
            function=function,callee_function=code.get(callee)[2]))
    plan=dict(sha256=b.sha(reference),calls=calls);b.save(root/'plan.json',plan)
    binary=root/'build/mongod';record=None
    try:
        record=stubs.build(reference,plan,binary,boundaries=code.instructions)
        del code
        verified=Code(binary)
        assert all(verified.raw_targets[hint['va']]==hint['target'] for hint in record['hints'])
        result=dict(binary=str(binary),nop=str(binary)+'.nop',reference=str(reference),
            sha256=record['sha256'],nop_sha256=record['nop_sha256'],summary=summary,
            extra_instruction_bytes=record['extra_instruction_bytes'],extra_mapped_bytes=record['extra_mapped_bytes'])
        b.save(root/'prepared.json',result);return result
    except BaseException as error:
        b.save(root/'failure.json',dict(error=repr(error)))
        remove_generated([p for p in [binary,Path(str(binary)+'.nop')] if p.exists()],root/'failed_cleanup.json',
            'Continuation-aware build rejected. Retain frozen selection, source, patch and native decode checks; remove unused generated ELF files.')
        raise


def trial(spec):
    # Dedicated child globals only; existing campaigns retain their own scopes.
    backend_study.MONITORED=MONITORED
    backend_study.EVENTS={k:v for k,v in backend_study.EVENTS.items() if k in ['cache','prefetch']}
    balanced_backend.trial(spec)


def report(root):
    data=evaluate(root/'screen',root/'screen_evaluation.json')
    protocol=json.loads((root/'screen/protocol.json').read_text())
    lines=['# Continuation-aware placement: fresh full Media C4','',
        f'{protocol["blocks"]} exploratory paired blocks. Each arm uses a fresh full stack, 50 s warmup and 60 s clean ROI. Individual paired-log t95 intervals; no multiplicity correction.',
        '', '| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |',
        '|---|---:|---:|---:|---:|---:|']
    for arm,values in data['absolute'].items():
        e=values['e2e'];lines.append(f'| {arm} | {values["rps"]:.2f} | {e["mean_ms"]:.4f} | {e["p99_ms"]:.4f} | {e["stack_cpu"]:.2f} | {values["util_pct"]:.2f}% |')
    lines += ['', '| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |',
        '|---|---:|---:|---:|---:|']
    def pct(value):
        ci=value['ci95_pct'];return f'{value["cost_reduction_pct"]:+.3f}% [{ci[0]:+.3f}, {ci[1]:+.3f}]'
    for arm,controls in data['e2e'].items():
        for control,values in controls.items():
            speed=values['inverse_rps'];ci=speed['speedup_ci95']
            lines.append(f'| {arm} / {control} | {speed["speedup"]:.5f}x [{ci[0]:.5f}, {ci[1]:.5f}] | '+
                ' | '.join(pct(values[key]) for key in ['mean_ms','p99_ms','stack_cpu'])+' |')
    lines += ['', '| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |',
        '|---|---:|---:|---:|']
    for arm,controls in data['pmu'].items():
        for control,values in controls.items():
            lines.append('| '+arm+' / '+control+' | '+' | '.join(pct(values['cache:sum:'+key]) for key in ['FE_L2','L2I','ICACHE_DATA_STALL'])+' |')
    lines += ['', 'PMU windows follow the clean ROI and cover three MongoDBs only; each window has its own request denominator. CPU and latency still cover the whole stack, including MovieId. No inference of maximum throughput, prefetch accuracy, or queue occupancy. Existing campaigns are not pooled.']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    groups={'review_mongo2':['mongo_user','mongo_movie'],'mongo3':list(MONITORED)}
    grouped=[]
    for row in data['pmu_rows']:
        metrics={group+':'+event:sum(row['metrics']['cache:'+service+':'+event] for service in services)
            for group,services in groups.items() for event in ['FE_L2','L2I','ICACHE_DATA_STALL']}
        grouped.append(dict(row,metrics=metrics))
    group_result=dict(control='original',groups=groups,pmu=summarize(grouped,protocol['arms']),rows=grouped)
    b.save(root/'grouped_pmu.json',group_result)
    ages=[]
    for row in json.loads((root/'screen/rows.json').read_text()):
        measurement=json.loads((Path(row['output'])/'result.json').read_text());pool=measurement['pool']
        ages.append(dict(arm=row['arm'],block=row['block'],roi_begin_epoch=pool['start'],roi_end_epoch=pool['end'],
            completed_before_roi=measurement['completed_before_roi'],roi_completed=pool['completed'],
            rps=row['achieved_rps'],cpu=row['metrics']['stack_cpu'],mean_ms=row['metrics']['mean_ms'],p99_ms=row['metrics']['p99_ms']))
    b.save(root/'workload_age.json',dict(rows=ages,limitation='Identical initial data and warmup duration do not mean equal cumulative writes.'))
    from backend_summary import plot
    from cpu_attribution import analyze
    plot(root,data,group_result);analyze(root,plot=True)
    return data


def campaign(parent,blocks=4):
    assert blocks>=3 and (parent/'hybrid_switch/complete.json').exists()
    root=parent/'split_coverage';root.mkdir(exist_ok=False);b.space(root)
    amendment=parent/'split_coverage_replication_amendment.json'
    if amendment.exists():
        record=json.loads(amendment.read_text())
        assert record['before_any_split_e2e'] and record['new_blocks']==blocks
        assert b.sha(__file__)==record['new_source_sha256']
        assert b.sha(record['old_source'])==record['old_source_sha256']
        assert b.sha(parent/'split_coverage_plan/selection.json')==record['selection_sha256']
        b.save(root/'replication_amendment.json',record)
        (root/'source_before_replication.py').write_bytes(Path(record['old_source']).read_bytes())
    prepared=prepare(parent,root/'prepared')
    fixed=json.loads((parent/'split_target_refine/prepared.json').read_text())
    overrides=json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    arms={
        'original':dict(mongo_binary=prepared['reference']),
        'fixed_split':dict(mongo_binary=fixed['binary'],controls=['original']),
        'split75_nop':dict(mongo_binary=prepared['nop'],controls=['original']),
        'split75':dict(mongo_binary=prepared['binary'],controls=['original','split75_nop','fixed_split'])}
    for settings in arms.values():settings.update(overrides=overrides,stat_s=3)
    screen=root/'screen';screen.mkdir()
    b.save(screen/'protocol.json',dict(blocks=blocks,arms=arms,monitored=MONITORED,seedbase=86001,
        source_sha256=b.sha(__file__),client_sha256=b.sha(Path(balanced_backend.__file__).with_name('balanced_load.py')),
        hashes={settings['mongo_binary']:b.sha(settings['mongo_binary']) for settings in arms.values()},
        rule='Frozen follow-up to the independently calibrated split-instruction attribution issue. Three MongoDB cache and prefetch windows shorten post-ROI diagnostics, without changing clean endpoint conditions. No performance-based retries/exclusions.'))
    rows=[];names=list(arms)
    for block in range(blocks):
        for arm in names if block%2==0 else list(reversed(names)):
            b.space(root);out=screen/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=86001+block))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            result=json.loads((out/'result.json').read_text());assert result['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=result['pool']['achieved_rps'],
                pool_util_pct=result['pool_util_pct'],metrics=dict(mean_ms=result['pool']['mean_ms'],
                p99_ms=result['pool']['p99_ms'],stack_cpu=result['whole_stack_cpu_us_per_request'],inverse_rps=1/result['pool']['achieved_rps']))
            rows.append(row);b.save(screen/'rows.json',rows);b.save(screen/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
    b.save(screen/'complete.json',dict(rows=len(rows)));report(root)
    b.save(root/'complete.json',dict(valid=True,clean_trials=len(rows)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['campaign','trial','report']);parser.add_argument('path',type=Path)
    parser.add_argument('--blocks',type=int,default=4)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='campaign':campaign(args.path,args.blocks)
    else:globals()[args.action](json.loads(args.path.read_text()) if args.action=='trial' else args.path)
