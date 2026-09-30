#!/usr/bin/env python3
"""Cover residual misses using existing executed NOPs, preserving split75 hints."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import signal
import backend_prefetch as capture
import balanced_backend
import dense_build as b
import fullset as h
from dense_cause_analysis import Code
from e2e_lbr import remove_generated
from fullset_study import summarize
from index_executable_padding import is_padding_nop
from residual_retarget import plan
import split_lead_study as lead


def profile(spec):
    capture.start_client=balanced_backend.start_client
    capture.profile(spec)
    validation=json.loads((Path(spec['out'])/'load_validation.json').read_text())
    assert validation['valid'] and validation['load']['mapping_preserved']


def prepare(root):
    assert (root/'hybrid_screen/complete.json').exists()
    out=root/'padding_residual';out.mkdir(exist_ok=False);b.space(out)
    initial=json.loads((root/'prepared_complete.json').read_text());base=initial['arms']['split75']
    binary=Path(base['mongo_binary']);audit=json.loads(Path(str(binary)+'.json').read_text())
    assert b.sha(binary)==audit['sha256']
    b.save(out/'protocol.json',dict(source_sha256=b.sha(__file__),base=str(binary),base_sha256=audit['sha256'],
        selector_sha256=b.sha(Path(capture.__file__).with_name('residual_retarget.py')),
        patcher_sha256=b.sha(capture.__file__),max_new_hints=256,min_gain=8,min_train_coverage_pct=5,
        rule='Two fresh full Media C4 captures, train seed 89201 and heldout seed 89202. The two review MongoDBs provide 8s PEBS/LBR windows after 50s warmup. Consider only existing 7..15-byte decoded NOP instructions observed on earlier retired paths, ages 64..8192. Correct split instructions to the modeled continuation line. Keep all existing split75 hints and jumps. Train-only selection; build only if train path coverage reaches 5%. Heldout is reported after choices freeze, never used to choose.',
        limitation='Padding hint execution adds memory operations, despite fixed instruction boundaries, code size and branch count. Coverage is not predicted speedup. Retirement age is not issue-to-fetch lead. This is an incremental addition to split75, whose original binary is the exact incremental NOP control.'))
    for phase,seed in [('train',89201),('heldout',89202)]:
        folder=out/'profiles'/phase;manifest=out/(phase+'_spec.json');b.space(out)
        b.save(manifest,dict(out=str(folder),mongo_binary=str(binary),reference=str(binary),overrides=base['overrides'],seed=seed,capture_kind='miss'))
        h.platform(folder,['python3',Path(__file__),'profile',manifest])
    code=Code(binary);raw=binary.read_bytes();slots={}
    for site,(length,asm,_) in code.instructions.items():
        if not 7<=length<=15 or not re.search(r'\bnop[wl]?\b',asm):continue
        section=next((s for s in code.sections if s[0]<=site and site+length<=s[0]+s[2]),None)
        if section is None:continue
        offset=section[1]+site-section[0]
        if is_padding_nop(raw[offset:offset+length]):slots[site]=(offset,length)
    assert slots
    phases={};quality={}
    for phase in ['train','heldout']:
        rows=[]
        for service in capture.BACKENDS:
            folder=out/'profiles'/phase/service
            observed,counts=capture.observed_rows(folder,code,slots)
            assert json.loads((folder/'record_types.json').read_text())['SAMPLE']==counts['all_samples']>100
            for row in observed:
                length=code.get(row['ip'])[0];assert length
                if row['ip']//64!=(row['ip']+length-1)//64:
                    row['target']=row['ip']+length;row['line']=row['target']//64
            dest=out/'observations'/(phase+'_'+service+'.json.gz');dest.parent.mkdir(exist_ok=True)
            with gzip.open(dest,'wt') as stream:json.dump(observed,stream,separators=(',',':'))
            quality[phase+':'+service]=dict(counts,observations_sha256=b.sha(dest),decoded_sha256=b.sha(folder/'samples.txt'))
            b.save(out/'profile_quality.json',dict(records=quality,slots=len(slots),binary_sha256=audit['sha256']))
            remove_generated([folder/'samples.txt'],folder/'decoded_cleanup.json',
                'Sparse NOP-path observations and quality/command/hash records retained; decoded trace extracted completely.')
            rows.extend(observed)
        phases[phase]=rows
    selected=plan(phases['train'],{site:0 for site in slots},max_fraction=min(1,256/len(slots)),min_gain=8)
    selected['train_samples']=len(phases['train'])
    b.save(out/'selection_frozen.json',selected)
    choices={row['site']:row['target']//64 for row in selected['changes']}
    selected.update(heldout_samples=len(phases['heldout']),heldout_covered=sum(any(choices.get(site)==row['line'] for site in row['sites']) for row in phases['heldout']))
    b.save(out/'selection.json',selected)
    train_pct=100*selected['final_covered']/selected['train_samples']
    if train_pct<5:
        b.save(out/'complete.json',dict(valid=True,compiled=False,train_coverage_pct=train_pct,
            reason='Train-only minimum 5% residual path coverage not reached; no generated ELF or E2E claim.'))
        return
    dest=out/'build/mongod';capture.padding_variant(binary,dest,code,slots,selected['changes'])
    patches=json.loads(dest.with_suffix('.patches.json').read_text());data=bytearray(dest.read_bytes())
    hints=list(audit['hints'])
    for row in patches['patches']:
        hints.append(dict(va=row['site'],offset=row['offset'],target=row['target'],original=row['after'],nop=row['before'],padding=True))
    nop=bytearray(data)
    for hint in hints:nop[hint['offset']:hint['offset']+len(bytes.fromhex(hint['nop']))]=bytes.fromhex(hint['nop'])
    assert hashlib.sha256(nop).hexdigest()==audit['nop_sha256']
    b.save(Path(str(dest)+'.json'),dict(audit,sha256=b.sha(dest),hints=hints,
        padding_extension=dict(source_sha256=b.sha(__file__),base=str(binary),base_sha256=audit['sha256'],
            patches=patches['patches'],new_hint_slots=len(choices),all_existing_hints_unchanged=True,
            incremental_nop_sha256=audit['sha256'],all_hints_nop_sha256=audit['nop_sha256'],
            instruction_boundaries_unchanged=True,extra_code_bytes=0,extra_jumps=0)))
    b.save(out/'complete.json',dict(valid=True,compiled=True,binary=str(dest),sha256=b.sha(dest),
        patches=len(choices),train_coverage_pct=train_pct,
        heldout_coverage_pct=100*selected['heldout_covered']/selected['heldout_samples'],additional_code_bytes=0,additional_jumps=0))


def campaign(root):
    assert (root/'lead_screen/complete.json').exists()
    prepared=json.loads((root/'padding_residual/complete.json').read_text());assert prepared['valid'] and prepared['compiled']
    initial=json.loads((root/'prepared_complete.json').read_text());base=dict(initial['arms']['split75']);base.pop('controls',None)
    arms=dict(split75=base,padding_t1=dict(base,mongo_binary=prepared['binary'],controls=['split75']))
    stage=root/'padding_screen';stage.mkdir(exist_ok=False);(stage/'screen').mkdir();b.space(stage)
    sources=[Path(__file__),Path(lead.__file__),Path(lead.study.__file__),Path(balanced_backend.__file__),
        Path(balanced_backend.__file__).with_name('balanced_load.py'),Path(capture.__file__),Path(lead.study.hybrid.__file__)]
    protocol=dict(arms=arms,control='split75',blocks=4,monitored=lead.study.MONITORED,
        orders=[['split75','padding_t1'],['padding_t1','split75']]*2,seedbase=89301,
        source_hashes={str(path):b.sha(path) for path in sources},binary_hashes={v['mongo_binary']:b.sha(v['mongo_binary']) for v in arms.values()},
        scope='Four fresh full Media C4 paired blocks including MovieId, 8 workload CPUs, 50s warmup and 60s clean ROI; post-ROI PMU only. Alternating AB/BA order; no performance-based retries or exclusions.',
        hypotheses='Supplement split75 with observed executed NOP slots. Preserve all old hints, all instruction addresses and lengths, code size and branch count. Reversing only new hints reproduces the split75 ELF byte-for-byte; it is the exact incremental NOP control. Added memory operations and cache traffic are measured costs.',
        title='Existing-padding supplement: fresh full Media C4',plot_title='Existing-padding supplement versus split75: full Media C4')
    b.save(stage/'protocol.json',protocol);b.save(stage/'screen/protocol.json',protocol);rows=[]
    for block,order in enumerate(protocol['orders']):
        for arm in order:
            b.space(stage);assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            out=stage/'screen'/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=89301+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(lead.__file__),'trial',manifest])
            result=json.loads((out/'result.json').read_text());assert result['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=result['pool']['achieved_rps'],pool_util_pct=result['pool_util_pct'],
                metrics=dict(mean_ms=result['pool']['mean_ms'],p99_ms=result['pool']['p99_ms'],stack_cpu=result['whole_stack_cpu_us_per_request'],inverse_rps=1/result['pool']['achieved_rps']))
            rows.append(row);b.save(stage/'screen/rows.json',rows);b.save(stage/'screen/summary.json',summarize(rows,arms));print(json.dumps(row),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)));b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows)))
    lead.report(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['profile','prepare','campaign']);parser.add_argument('path',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='profile':profile(json.loads(args.path.read_text()))
    elif args.action=='prepare':
        try:prepare(args.path)
        except BaseException as error:
            out=args.path/'padding_residual'
            if out.exists():
                b.save(out/'failure.json',dict(error=repr(error)))
                unused=[path for path in out.rglob('*') if path.name in ['perf.data','samples.txt','mongod'] and path.is_file() and not path.is_symlink()]
                if unused:remove_generated(unused,out/'failed_cleanup.json','Padding qualification failed; preserve quality, commands, source, selections, patches and hashes before deleting unused generated bulk.')
            raise
    else:campaign(args.path)
