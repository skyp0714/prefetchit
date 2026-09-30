#!/usr/bin/env python3
"""Retarget fixed supplemental T1 slots using long frontend-stall samples."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import signal
import struct
import subprocess
import backend_prefetch as capture
import balanced_backend
import dense_build as b
import fullset as h
from call_cost_selector import select
from callpath_prefetch import coverage, stubs
from dense_cause_analysis import Code
from e2e_lbr import remove_generated
from fullset_study import summarize
from split_coverage_campaign import trial_orders
from split_l1_continue import annotate
import split_lead_study as lead

LAT128 = 'cpu/event=0xc6,umask=0x3,config1=0x608006,name=FE_LAT128/u'


def profile(spec):
    capture.start_client=balanced_backend.start_client
    capture.profile(spec)
    checked=json.loads((Path(spec['out'])/'load_validation.json').read_text())
    assert checked['valid'] and checked['load']['mapping_preserved']


def prepare(root):
    assert json.loads((root/'l1_screen/complete.json').read_text())['valid']
    assert not json.loads((root/'l1_confirmation_qualification.json').read_text())['qualified']
    out=root/'latency_retarget';out.mkdir(exist_ok=False);b.space(out)
    previous=json.loads((root/'l1_screen/protocol.json').read_text())
    base=previous['arms']['extra_t1'];binary=Path(base['mongo_binary'])
    audit=json.loads(Path(str(binary)+'.json').read_text())
    reference=Path(audit['source']);assert b.sha(binary)==audit['sha256']==previous['binary_hashes'][str(binary)]
    assert b.sha(reference)==audit['source_sha256']
    old_choices=json.loads((root/'l1_supplement/selection_frozen.json').read_text())['choices']
    old_targets={row['site']:row['target'] for row in old_choices};assert len(old_targets)==256
    original_t1=json.loads(Path(previous['arms']['split75']['mongo_binary']+'.json').read_text())
    forbidden={row['target'] for row in original_t1['hints']}
    frequency_record=json.loads((root/'l1_supplement/protocol.json').read_text())
    frequency_path=Path(frequency_record['frequency_source'])
    assert b.sha(frequency_path)==frequency_record['frequency_sha256']
    b.save(out/'protocol.json',dict(source_sha256=b.sha(__file__),capture_sha256=b.sha(capture.__file__),
        source_binary=str(binary),source_binary_sha256=audit['sha256'],
        frequency_source=str(frequency_path),frequency_sha256=b.sha(frequency_path),
        event='cpu/event=0xc6,umask=0x3,config1=0x608006,period=257,name=fe_lat128/upp',
        selected_call_sites=sorted(old_targets),new_calls=0,new_hints=0,new_code_bytes=0,
        train_seed=89801,heldout_seed=89802,minimum_retired_age=64,maximum_retired_age=8192,
        minimum_train_coverage_pct=5,minimum_train_gain_pp=1.5,
        rule='Capture long frontend stalls on the existing extra_t1 binary. Use exactly its 256 supplemental slots; never change original split75 T1 hints. Select targets on training only with original call-frequency cost. Keep old extra targets at sites not selected. Freeze before heldout evaluation. Compile only if train path coverage is >=5% and >=1.5 percentage points better than old supplemental targets.',
        hypothesis='Miss-count-selected hints may cover short or overlapped fetch delays. Retarget the same slots to instructions after frontend delivery gaps >=128 cycles, excluding backend-interrupted gaps according to Intel event definition. Same code layout, call sites, hint count and instruction opcodes isolate target selection from code inflation and guard cost.',
        limitation='The event is not specific to code-cache misses: branch and translation effects can contribute. A retired-IP association does not identify the missing byte, actual hint issue lead, acceptance, or request critical path. Split instructions and non-original target boundaries are excluded from selection but stay in the denominator.'))
    b.run(['perf','stat','-x,','-o',str(out/'lat128_preflight.csv'),'-e','cycles:u,instructions:u,'+LAT128,
        '-a','-C','84','--','taskset','-c','84','python3','-c','sum(i*i for i in range(1000000))'],out/'lat128_preflight.log')
    counts=lead.study.counters(out/'lat128_preflight.csv');assert counts['fully_scheduled']
    b.save(out/'lat128_preflight.json',counts)
    for phase,seed in [('train',89801),('heldout',89802)]:
        folder=out/'profiles'/phase;manifest=out/(phase+'_spec.json');b.space(out)
        b.save(manifest,dict(out=str(folder),mongo_binary=str(binary),reference=str(binary),
            overrides=base['overrides'],seed=seed,capture_kind='lat128'))
        h.platform(folder,['python3',Path(__file__),'profile',manifest])
    code=Code(binary);elf=stubs.Elf(reference.read_bytes())
    executable=[(p[3],p[3]+p[5]) for p in elf.ph if p[0]==1 and p[1]&1]
    anchors={};phases={};quality={}
    def anchor(line):
        if line not in anchors:
            anchors[line]=next((va for va in range(line*64,line*64+64)
                if va in code.instructions and va not in forbidden and
                (va+code.get(va)[0]-1)//64==line and any(lo<=va and va+code.get(va)[0]<=hi for lo,hi in executable)),None)
        return anchors[line]
    for phase in ['train','heldout']:
        rows=[]
        for service in capture.BACKENDS:
            folder=out/'profiles'/phase/service
            observed,counts=capture.observed_rows(folder,code,set(old_targets),minimum=64)
            assert json.loads((folder/'record_types.json').read_text())['SAMPLE']==counts['all_samples']>100
            requests=json.loads((folder/'request_window.json').read_text())['completed_requests'];exclusions=collections.Counter()
            for row in observed:
                length=code.get(row['ip'])[0];assert length
                target=anchor(row['ip']//64)
                if (row['ip']+length-1)//64!=row['ip']//64:
                    row['sites']=[];exclusions['split_instruction']+=1
                elif target is None:
                    row['sites']=[];exclusions['no_original_nonduplicate_boundary']+=1
                row['target']=target if target is not None else row['ip'];row['line']=row['ip']//64
                row['miss_weight']=257/requests
            dest=out/'observations'/(phase+'_'+service+'.json.gz');dest.parent.mkdir(exist_ok=True)
            with gzip.open(dest,'wt') as stream:json.dump(observed,stream,separators=(',',':'))
            quality[phase+':'+service]=dict(counts,selection_eligible=sum(bool(row['sites']) for row in observed),
                exclusions=dict(exclusions),observations_sha256=b.sha(dest),decoded_sha256=b.sha(folder/'samples.txt'))
            b.save(out/'profile_quality.json',dict(records=quality,base_sha256=audit['sha256']))
            remove_generated([folder/'samples.txt'],folder/'decoded_cleanup.json',
                'Retain long-stall sparse observations, quality, commands and hashes; remove decoded trace after extraction.')
            rows.extend(observed)
        phases[phase]=rows
    frequency=json.loads(frequency_path.read_text());assert frequency['valid'] and frequency['reference_sha256']==audit['source_sha256']
    rates=collections.Counter();floor=0
    for record in frequency['records'].values():
        assert record['valid'];rates.update({int(k):v for k,v in record['direct_call_estimates'].items()})
        floor+=record['zero_sample_cost_floor_per_request']
    selected=select(phases['train'],rates,floor,max_sites=256,max_hints=256,per_site=1,min_gain=8,goal=.10)
    selected['estimated_covered_long_stall_events_per_request']=selected.pop('estimated_covered_misses_per_request')
    selected['estimated_existing_hint_visits_per_request']=selected.pop('estimated_hint_executions_per_request')
    selected['estimated_existing_call_visits_per_request']=selected.pop('estimated_extra_jumps_per_request')
    selected['added_hint_executions_per_call']=0
    selected['added_jumps_per_call']=0
    chosen=dict(old_targets);chosen.update({row['site']:row['target'] for row in selected['choices']})
    choices=[dict(site=site,target=target) for site,target in sorted(chosen.items())]
    before=coverage(phases['train'],old_choices);after=coverage(phases['train'],choices)
    changes=[row for row in choices if old_targets[row['site']]!=row['target']]
    record=dict(choices=choices,changed_choices=changes,train_before=before,train_after=after,
        train_coverage_pct=100*after['covered']/after['samples'],
        train_gain_pp=100*(after['covered']-before['covered'])/after['samples'],
        extra_calls=0,extra_hints=0,extra_code_bytes=0,selection=selected)
    b.save(out/'selection_frozen.json',record)
    record.update(heldout_before=coverage(phases['heldout'],old_choices),heldout_after=coverage(phases['heldout'],choices))
    b.save(out/'selection.json',record)
    if record['train_coverage_pct']<5 or record['train_gain_pp']<1.5:
        b.save(out/'complete.json',dict(valid=True,compiled=False,train_coverage_pct=record['train_coverage_pct'],
            train_gain_pp=record['train_gain_pp'],reason='Frozen train-only coverage/gain thresholds not met; no executable or E2E claim.'))
        return
    data=bytearray(binary.read_bytes());original=bytes(data);patches=[]
    patch_by_site={row['site']:row for row in audit['patches']};hint_by_va={row['va']:row for row in audit['hints']}
    for choice in changes:
        slot=patch_by_site[choice['site']]['stub'];hint=hint_by_va[slot];offset=hint['offset']
        assert hint['target']==old_targets[choice['site']] and bytes(data[offset:offset+3])==bytes.fromhex('0f1815')
        old=bytes(data[offset:offset+7]);data[offset+3:offset+7]=struct.pack('<i',choice['target']-slot-7)
        patches.append(dict(site=choice['site'],va=slot,offset=offset,target=choice['target'],before=old.hex(),after=bytes(data[offset:offset+7]).hex()))
    restored=bytearray(data)
    for row in patches:restored[row['offset']:row['offset']+7]=bytes.fromhex(row['before'])
    assert bytes(restored)==original
    nop=bytearray(data)
    for site in old_targets:
        hint=hint_by_va[patch_by_site[site]['stub']];nop[hint['offset']:hint['offset']+7]=bytes.fromhex(hint['nop'])
    expected=previous['binary_hashes'][previous['arms']['extra_nop']['mongo_binary']]
    assert hashlib.sha256(nop).hexdigest()==expected
    dest=out/'build/mongod';dest.parent.mkdir();b.space(out)
    b.save(Path(str(dest)+'.json'),dict(source=str(binary),source_sha256=audit['sha256'],source_tool_sha256=b.sha(__file__),
        sha256=hashlib.sha256(data).hexdigest(),changes=patches,incremental_nop_sha256=expected,
        unchanged_original_t1=True,only_added_slot_displacements_changed=True,extra_code_bytes=0,verified=False))
    dest.write_bytes(data);dest.chmod(0o755)
    command=['objdump','-d','-j','.text.prefetch_calls','--insn-width=16',str(dest)]
    b.save(out/'decode.command.json',command);decoded=subprocess.check_output(command,text=True);(out/'stubs.asm').write_text(decoded)
    found={}
    for line in decoded.splitlines():
        match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$',line)
        if match:found[int(match[1],16)]=(bytes.fromhex(match[2]),match[3])
    for patch in patches:
        raw,asm=found[patch['va']];target=re.search(r'#\s*([0-9a-f]+)',asm)
        assert raw.hex()==patch['after'] and asm.startswith('prefetcht1') and target and int(target[1],16)==patch['target']
    verified=json.loads(Path(str(dest)+'.json').read_text());verified['verified']=True;b.save(Path(str(dest)+'.json'),verified)
    smoke=out/'smoke_spec.json';b.save(smoke,dict(out=str(out/'smoke'),mongo_binary=str(dest),overrides=base['overrides'],seed=89803))
    h.platform(out/'smoke',['python3',Path(balanced_backend.__file__),'smoke',smoke])
    assert json.loads((out/'smoke/result.json').read_text())['valid']
    b.save(out/'complete.json',dict(valid=True,compiled=True,binary=str(dest),sha256=b.sha(dest),
        modified_displacements=len(patches),extra_calls=0,extra_hints=0,extra_code_bytes=0,
        train_coverage_pct=record['train_coverage_pct'],train_gain_pp=record['train_gain_pp'],
        heldout_coverage_pct=100*record['heldout_after']['covered']/record['heldout_after']['samples']))


def trial(spec):
    lead.study.check_td=annotate
    lead.study.EVENTS['lat128']='cycles:u,instructions:u,'+LAT128
    lead.trial(dict(spec,quality_wrapper_sha256=b.sha(Path(__file__).with_name('split_l1_continue.py'))))


def campaign(root):
    prepared=json.loads((root/'latency_retarget/complete.json').read_text());assert prepared['valid'] and prepared['compiled']
    previous=json.loads((root/'l1_screen/protocol.json').read_text())
    initial=json.loads((root/'prepared_complete.json').read_text())
    original=dict(initial['arms']['original']);original.pop('controls',None)
    arms=dict(original=original,split75=dict(previous['arms']['split75'],controls=['original']),
        extra_t1=dict(previous['arms']['extra_t1'],controls=['original','split75']))
    arms['latency_t1']=dict(arms['extra_t1'],mongo_binary=prepared['binary'],controls=['original','split75','extra_t1'])
    assert b.sha(original['mongo_binary'])==initial['binary_hashes'][original['mongo_binary']]
    assert all(b.sha(arms[name]['mongo_binary'])==previous['binary_hashes'][arms[name]['mongo_binary']]
        for name in ['split75','extra_t1'])
    assert b.sha(prepared['binary'])==prepared['sha256']
    stage=root/'latency_screen';stage.mkdir(exist_ok=False);(stage/'screen').mkdir();b.space(stage)
    files=[Path(__file__),Path(capture.__file__),Path(lead.__file__),Path(lead.study.__file__),Path(lead.study.hybrid.__file__),
        Path(balanced_backend.__file__),Path(lead.study.backend_study.__file__),Path(__file__).with_name('split_l1_continue.py'),
        Path(__file__).with_name('balanced_load.py'),Path(__file__).with_name('dense_causes.py')]
    protocol=dict(arms=arms,control='split75',orders=trial_orders(list(arms),4),blocks=4,seedbase=89901,
        source_hashes={str(p):b.sha(p) for p in files},binary_hashes={v['mongo_binary']:b.sha(v['mongo_binary']) for v in arms.values()},
        monitored=lead.study.MONITORED,selection_sha256=b.sha(root/'latency_retarget/selection_frozen.json'),
        scope='Four balanced blocks: fresh full Media compose-review C4 including MovieId, eight workload CPUs, 50s warmup, 60s clean ROI. 28 separate post-ROI PMU windows include long frontend stalls. No performance-based retry/exclusion; no pooling with earlier campaigns.',
        hypotheses='Retarget only existing supplemental T1 displacements using long frontend-stall samples, preserving code size, call sites, hint count and every original split75 T1 hint. latency_t1 and extra_t1 have identical layout/opcodes outside the changed displacements and restore to the same recorded incremental-NOP hash. Directly compare the full policy to original and split75; isolate target selection versus extra_t1. Do not infer E2E benefit by multiplying previous ratios.',
        title='Long frontend-stall targets with fixed supplemental slots: fresh full Media C4',plot_title='Long frontend-stall targets versus split75: full Media C4')
    for name in ['protocol.json','screen/protocol.json']:b.save(stage/name,protocol)
    rows=[]
    for block,order in enumerate(protocol['orders']):
        for arm in order:
            b.space(stage);assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            out=stage/'screen'/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=protocol['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            value=json.loads((out/'result.json').read_text());assert value['valid']
            rows.append(dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=value['pool']['achieved_rps'],pool_util_pct=value['pool_util_pct'],
                metrics=dict(mean_ms=value['pool']['mean_ms'],p99_ms=value['pool']['p99_ms'],stack_cpu=value['whole_stack_cpu_us_per_request'],inverse_rps=1/value['pool']['achieved_rps'])))
            b.save(stage/'screen/rows.json',rows);b.save(stage/'screen/summary.json',summarize(rows,arms));print(json.dumps(rows[-1]),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)));b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows)))
    lead.report(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','profile','trial','campaign']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action in ['profile','trial']:globals()[args.action](json.loads(args.root.read_text()))
    elif args.action=='prepare':
        try:prepare(args.root)
        except BaseException as error:
            out=args.root/'latency_retarget'
            if out.exists():
                b.save(out/'failure.json',dict(error=repr(error)))
                paths=[p for p in out.rglob('*') if p.is_file() and not p.is_symlink() and p.name in ['perf.data','samples.txt','mongod']]
                if paths:remove_generated(paths,out/'failed_cleanup.json','Retain failure, commands, source, hashes and observations; remove inactive generated bulk.')
            raise
    else:campaign(args.root)
