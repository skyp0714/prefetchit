#!/usr/bin/env python3
"""Train on remaining L1I misses, preserving all split75 T1 hints and calls."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import signal
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
import split_lead_study as lead


def profile(spec):
    capture.start_client=balanced_backend.start_client
    capture.profile(spec)
    checked=json.loads((Path(spec['out'])/'load_validation.json').read_text())
    assert checked['valid'] and checked['load']['mapping_preserved']


def variant(source, audit, dest, slots, kind):
    assert kind in ['it0','nop'] and not dest.exists()
    data=bytearray(source.read_bytes()); original=bytes(data); changes=[]; hints=[]
    for row in audit['hints']:
        offset=row['offset']; before=bytes(data[offset:offset+7]); assert before.hex()==row['original']
        if row['va'] in slots:
            assert before[:3]==bytes.fromhex('0f1815')
            if kind=='it0': data[offset+2]=0x3d
            else: data[offset:offset+7]=bytes.fromhex(row['nop'])
            changes.append(dict(va=row['va'],offset=offset,before=before.hex(),after=bytes(data[offset:offset+7]).hex()))
        if kind!='nop' or row['va'] not in slots:
            hints.append(dict(row,original=bytes(data[offset:offset+7]).hex()))
    assert len(changes)==len(slots)
    restored=bytearray(data)
    for row in changes: restored[row['offset']:row['offset']+7]=bytes.fromhex(row['before'])
    assert bytes(restored)==original
    nop=bytearray(data)
    for row in hints:nop[row['offset']:row['offset']+7]=bytes.fromhex(row['nop'])
    assert hashlib.sha256(nop).hexdigest()==audit['nop_sha256']
    dest.parent.mkdir(parents=True,exist_ok=True)
    transform=dict(kind=kind,source=str(source),source_sha256=audit['sha256'],source_tool_sha256=b.sha(__file__),
        changes=changes,only_new_slots_changed=True,all_old_t1_hints_preserved=True,identical_layout=True,fully_reversible=True)
    b.save(Path(str(dest)+'.transform.json'),dict(transform,verified=False,sha256=hashlib.sha256(data).hexdigest()))
    dest.write_bytes(data); dest.chmod(0o755)
    command=['objdump','-d','-j','.text.prefetch_calls','--insn-width=16',str(dest)]
    b.save(Path(str(dest)+'.decode.command.json'),command)
    decoded=subprocess.check_output(command,text=True);Path(str(dest)+'.asm').write_text(decoded)
    found={}
    for line in decoded.splitlines():
        match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$',line)
        if match and int(match[1],16) in slots:found[int(match[1],16)]=(bytes.fromhex(match[2]),match[3])
    assert set(found)==set(slots)
    for address,(raw,asm) in found.items():
        assert len(raw)==7
        if kind=='it0':
            target=re.search(r'#\s*([0-9a-f]+)',asm)
            assert asm.startswith('prefetchit0') and target and int(target[1],16)==slots[address]
        else:assert re.search(r'\bnop',asm)
    record=dict(audit,sha256=b.sha(dest),hints=hints,supplemental_transform=transform)
    b.save(Path(str(dest)+'.transform.json'),dict(transform,verified=True,sha256=record['sha256']))
    b.save(Path(str(dest)+'.json'),record)
    return dict(binary=str(dest),sha256=record['sha256'])


def prepare(root):
    assert json.loads((root/'lead_screen/complete.json').read_text())['valid']
    out=root/'l1_supplement';out.mkdir(exist_ok=False);b.space(out)
    initial=json.loads((root/'prepared_complete.json').read_text());base=initial['arms']['split75']
    binary=Path(base['mongo_binary']);audit=json.loads(Path(str(binary)+'.json').read_text())
    reference=Path(audit['source']);assert b.sha(binary)==audit['sha256'] and b.sha(reference)==audit['source_sha256']
    # The reference is inside backend/reference; use the recorded frequency source.
    parent=reference.parents[2]
    old_selection=json.loads((parent/'split_coverage_plan/selection.json').read_text())
    frequency_path=Path(old_selection['frequency_source']['path'])
    assert b.sha(frequency_path)==old_selection['frequency_source']['sha256']
    b.save(out/'protocol.json',dict(base=str(binary),base_sha256=audit['sha256'],source_sha256=b.sha(__file__),
        capture_sha256=b.sha(capture.__file__),builder_sha256=b.sha(stubs.__file__),
        frequency_source=str(frequency_path),frequency_sha256=b.sha(frequency_path),
        max_new_hints=256,max_new_hints_per_call=1,coverage_goal_pct=10,min_train_coverage_pct=5,
        min_gain=16,minimum_retired_age=64,maximum_retired_age=8192,
        rule='Two fresh full Media C4 captures (train 89501, heldout 89502), 8s L1I PEBS/LBR windows for the two review MongoDBs after 50s warmup. Retain all split75 T1 hints and original call sites. Add at most one leading hint per existing call stub. Select on train only, weighted miss gain per original sampled call rate across Mongo3. Exclude split instructions and added-stub samples from selection, retaining them in the denominator. New target instruction addresses avoid every old hint address, preventing new/old stub sharing. Build only if train coverage reaches 5%; heldout never selects.',
        hypothesis='Residual frontend costs may remain at L1I and branch/decode delivery after L2 warming. Test added IT0 against identical added T1/NOP slots, with all old T1 hints retained. One added IT0 per selected stub, no timestamp/epoch guard, no new call sites or jumps. This is a new path-based supplement, not a repeat of the early switch burst.',
        limitation='L1I miss samples do not prove L2 residency or fetch-queue state. Retired age is not issue-to-fetch lead. Code layout changes versus split75 are measured using an incremental NOP control. Added instruction/cache traffic can offset the benefit.'))
    for phase,seed in [('train',89501),('heldout',89502)]:
        folder=out/'profiles'/phase;manifest=out/(phase+'_spec.json');b.space(out)
        b.save(manifest,dict(out=str(folder),mongo_binary=str(binary),reference=str(binary),overrides=base['overrides'],seed=seed,capture_kind='l1'))
        h.platform(folder,['python3',Path(__file__),'profile',manifest])
    code=Code(binary); elf=stubs.Elf(reference.read_bytes())
    executable=[(p[3],p[3]+p[5]) for p in elf.ph if p[0]==1 and p[1]&1]
    old_addresses={row['target'] for row in audit['hints']}
    sites={row['site'] for row in audit['patches']};anchors={};phases={};quality={}
    def anchor(line):
        if line not in anchors:
            anchors[line]=next((va for va in range(line*64,line*64+64)
                if va in code.instructions and va not in old_addresses and
                (va+code.get(va)[0]-1)//64==line and any(lo<=va and va+code.get(va)[0]<=hi for lo,hi in executable)),None)
        return anchors[line]
    for phase in ['train','heldout']:
        rows=[]
        for service in capture.BACKENDS:
            folder=out/'profiles'/phase/service
            observed,counts=capture.observed_rows(folder,code,sites,minimum=64)
            assert json.loads((folder/'record_types.json').read_text())['SAMPLE']==counts['all_samples']>100
            requests=json.loads((folder/'request_window.json').read_text())['completed_requests']
            exclusions=collections.Counter()
            for row in observed:
                length=code.get(row['ip'])[0];assert length
                target=anchor(row['ip']//64)
                if (row['ip']+length-1)//64!=row['ip']//64:
                    row['sites']=[];exclusions['split_instruction']+=1
                elif target is None:
                    row['sites']=[];exclusions['no_original_nonduplicate_boundary']+=1
                row['target']=target if target is not None else row['ip'];row['line']=row['ip']//64
                row['miss_weight']=1021/requests
            dest=out/'observations'/(phase+'_'+service+'.json.gz');dest.parent.mkdir(exist_ok=True)
            with gzip.open(dest,'wt') as stream:json.dump(observed,stream,separators=(',',':'))
            quality[phase+':'+service]=dict(counts,selection_eligible=sum(bool(row['sites']) for row in observed),
                exclusions=dict(exclusions),observations_sha256=b.sha(dest),decoded_sha256=b.sha(folder/'samples.txt'))
            b.save(out/'profile_quality.json',dict(records=quality,base_sha256=audit['sha256']))
            remove_generated([folder/'samples.txt'],folder/'decoded_cleanup.json',
                'L1I sample counts, sparse observations, commands, source and hashes retained; remove decoded trace after extraction.')
            rows.extend(observed)
        phases[phase]=rows
    frequency=json.loads(frequency_path.read_text());assert frequency['valid'] and frequency['reference_sha256']==audit['source_sha256']
    rates=collections.Counter();floor=0
    for record in frequency['records'].values():
        assert record['valid'];rates.update({int(k):v for k,v in record['direct_call_estimates'].items()})
        floor+=record['zero_sample_cost_floor_per_request']
    chosen=select(phases['train'],rates,floor,max_sites=256,max_hints=256,per_site=1,min_gain=16,goal=.10)
    chosen['estimated_selected_call_visits_per_request']=chosen.pop('estimated_extra_jumps_per_request')
    chosen['estimated_extra_jumps_per_request']=0
    b.save(out/'selection_frozen.json',chosen)
    chosen['heldout']=coverage(phases['heldout'],chosen['choices'])
    b.save(out/'selection.json',chosen)
    train_pct=100*chosen['covered']/chosen['samples']
    if train_pct<5:
        b.save(out/'complete.json',dict(valid=True,compiled=False,train_coverage_pct=train_pct,
            heldout_coverage_pct=100*chosen['heldout']['covered']/chosen['heldout']['samples'],
            reason='Train-only minimum 5% L1I path coverage not reached; no ELF or E2E claim.'))
        return
    selected={row['site']:row['target'] for row in chosen['choices']};assert len(selected)==len(chosen['choices'])
    calls=[dict(row,targets=([selected[row['site']]] if row['site'] in selected else [])+row['targets']) for row in audit['plan']['calls']]
    plan=dict(sha256=audit['source_sha256'],calls=calls);b.save(out/'build_plan.json',plan)
    dest=out/'build/extra_t1/mongod';b.space(out)
    built=stubs.build(reference,plan,dest,boundaries=code.instructions)
    assert built['unique_stubs']==audit['unique_stubs'] and built['call_sites']==audit['call_sites']
    added=built['extra_instruction_bytes']-audit['extra_instruction_bytes']
    assert 0<=added<=4096
    slots={row['stub']:selected[row['site']] for row in built['patches'] if row['site'] in selected}
    assert len(slots)==len(selected) and len({(site+6)//32 for site in slots})==len(slots)
    for old,new in zip(audit['patches'],built['patches']):
        assert old['site']==new['site'] and old['callee']==new['callee']
        assert new['targets'][int(old['site'] in selected):]==old['targets']
    variants=dict(extra_t1=dict(binary=str(dest),sha256=built['sha256']))
    for kind in ['it0','nop']:
        variants['extra_'+kind]=variant(dest,built,out/'build'/('extra_'+kind)/'mongod',slots,kind)
    remove_generated([Path(str(dest)+'.nop')],out/'unused_all_nop_cleanup.json',
        'All-hint NOP is not a study arm; its hash is retained. The incremental NOP preserves all original T1 hints and is the active matched control.')
    smoke=out/'smoke_spec.json'
    b.save(smoke,dict(out=str(out/'smoke'),mongo_binary=variants['extra_it0']['binary'],overrides=base['overrides'],seed=89503))
    h.platform(out/'smoke',['python3',Path(balanced_backend.__file__),'smoke',smoke])
    assert json.loads((out/'smoke/result.json').read_text())['valid']
    b.save(out/'complete.json',dict(valid=True,compiled=True,variants=variants,new_slots=len(slots),
        train_coverage_pct=train_pct,heldout_coverage_pct=100*chosen['heldout']['covered']/chosen['heldout']['samples'],
        added_hint_instruction_bytes=7*len(slots),added_code_section_bytes=added,
        extra_code_section_bytes=built['extra_instruction_bytes'],additional_calls=0,additional_jumps=0,
        all_old_t1_preserved=True,one_new_it0_per_static_32B_region=True))


def campaign(root):
    prepared=json.loads((root/'l1_supplement/complete.json').read_text());assert prepared['valid'] and prepared['compiled']
    assert all(b.sha(value['binary'])==value['sha256'] for value in prepared['variants'].values())
    initial=json.loads((root/'prepared_complete.json').read_text());base=dict(initial['arms']['split75']);base.pop('controls',None)
    arms=dict(split75=base)
    for name in ['extra_nop','extra_t1','extra_it0']:
        controls=['split75']+(['extra_nop'] if name!='extra_nop' else [])+(['extra_t1'] if name=='extra_it0' else [])
        arms[name]=dict(base,mongo_binary=prepared['variants'][name]['binary'],controls=controls)
    stage=root/'l1_screen';stage.mkdir(exist_ok=False);(stage/'screen').mkdir();b.space(stage)
    files=[Path(__file__),Path(capture.__file__),Path(lead.__file__),Path(lead.study.__file__),Path(lead.study.hybrid.__file__),
        Path(balanced_backend.__file__),Path(balanced_backend.__file__).with_name('balanced_load.py'),Path(lead.study.backend_study.__file__)]
    protocol=dict(arms=arms,control='split75',blocks=4,orders=trial_orders(list(arms),4),seedbase=89601,
        prepared_sha256=b.sha(root/'l1_supplement/complete.json'),selection_sha256=b.sha(root/'l1_supplement/selection_frozen.json'),
        monitored=lead.study.MONITORED,source_hashes={str(p):b.sha(p) for p in files},
        binary_hashes={v['mongo_binary']:b.sha(v['mongo_binary']) for v in arms.values()},
        scope='Four balanced blocks, fresh full Media compose-review C4 including MovieId. Eight workload CPUs, 50s warmup and 60s clean ROI. Same 25 post-ROI PMU windows; no performance-based retries/exclusions. Do not pool with previous campaigns.',
        hypotheses='Add at most one L1I-trained hint at each selected existing stub, retaining all original split75 T1 hints and original call sites. extra_it0/extra_t1/extra_nop have identical layout and targets; only new-slot bytes differ. Split75 versus incremental NOP measures layout/instruction overhead. No timestamp/epoch gate. The single IT0 at each selected stub is also the only added IT0 in its static 32B region; fetch-queue occupancy is not observed.',
        title='L1I-guided supplement with old T1 retained: fresh full Media C4',plot_title='L1I-guided supplement versus split75: full Media C4')
    b.save(stage/'protocol.json',protocol);b.save(stage/'screen/protocol.json',protocol);rows=[]
    for block,order in enumerate(protocol['orders']):
        for arm in order:
            b.space(stage);assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            out=stage/'screen'/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=protocol['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(lead.__file__),'trial',manifest])
            value=json.loads((out/'result.json').read_text());assert value['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=value['pool']['achieved_rps'],pool_util_pct=value['pool_util_pct'],
                metrics=dict(mean_ms=value['pool']['mean_ms'],p99_ms=value['pool']['p99_ms'],stack_cpu=value['whole_stack_cpu_us_per_request'],inverse_rps=1/value['pool']['achieved_rps']))
            rows.append(row);b.save(stage/'screen/rows.json',rows);b.save(stage/'screen/summary.json',summarize(rows,arms));print(json.dumps(row),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)));b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows)))
    lead.report(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','profile','campaign']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='profile':profile(json.loads(args.root.read_text()))
    elif args.action=='prepare':
        try:prepare(args.root)
        except BaseException as error:
            out=args.root/'l1_supplement'
            if out.exists():
                b.save(out/'failure.json',dict(error=repr(error)))
                paths=[p for p in out.rglob('*') if p.is_file() and not p.is_symlink() and p.name in ['perf.data','samples.txt','mongod','mongod.nop']]
                if paths:remove_generated(paths,out/'failed_cleanup.json','Preparation failed; retain source, hashes, patches, choices, quality and error before removing unused generated bulk.')
            raise
    else:campaign(args.root)
