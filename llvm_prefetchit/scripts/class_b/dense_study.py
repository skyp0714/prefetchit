#!/usr/bin/env python3
"""Audited dense/NOP controls and fresh-stack, prespecified Media experiments."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys

import dense_build as b


def read(path): return json.loads(path.read_text())


def audit(root, variants=None, prefix=''):
    sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
    import make_nop_control_binary as nop
    arms={};records=[]
    for arm,tag in (variants or {arm:arm for arm in b.ARMS}).items():
        assert (root/'builds'/tag/'complete.json').exists()
        arms[arm]=dict(overrides={})
        if arm!='base':
            arms[arm]['controls']=['base',arm+'_nop']
            arms[arm+'_nop']=dict(overrides={},controls=['base'])
        for key,exe in b.SERVICES.items():
            b.space(root);binary=root/'builds'/tag/key/exe
            source=binary.read_bytes();patched=bytearray(source)
            sections=nop.executable_sections(str(binary));patches=[];counts=collections.Counter()
            command=['objdump','-d','--insn-width=16',str(binary)]
            dis=subprocess.check_output(command,text=True)
            instructions=0
            for line in dis.splitlines():
                match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
                if not match:continue
                instructions+=1;instruction=match[3]
                if 'prefetch' not in instruction.split('#')[0]:continue
                assert instruction.split()[0]=='prefetcht1',instruction
                va=int(match[1],16);raw=bytes.fromhex(match[2]);size=len(raw)
                candidates=[(v,o,s) for v,o,s in sections if v<=va and va+size<=v+s]
                opcode = raw[1:] if 0x40 <= raw[0] <= 0x4f else raw
                assert len(candidates)==1 and opcode.startswith(b'\x0f\x18'),line
                v,o,s=candidates[0];offset=o+va-v
                assert source[offset:offset+size]==raw
                replacement=nop.MULTI_NOP[size];patched[offset:offset+size]=replacement
                patches.append(dict(va=hex(va),offset=offset,original=raw.hex(),nop=replacement.hex(),instruction=instruction))
                counts['rip' if '(%rip)' in instruction else 'register']+=1
            record=dict(arm=arm,service=key,path=str(binary),sha256=b.sha(binary),bytes=len(source),
                executable_bytes=sum(s for v,o,s in sections),static_instructions=instructions,
                prefetch_instructions=len(patches),addressing=dict(counts),disassembly_command=command)
            if arm=='base':assert not patches,'A no-prefetch baseline is required'
            else:
                assert len(patches)>0,'Instrumented build contains no prefetches'
                control=Path(str(binary)+'.nop');assert not control.exists()
                control.write_bytes(patched);control.chmod(binary.stat().st_mode)
                check=subprocess.check_output(['objdump','-d','--no-show-raw-insn',str(control)],text=True)
                assert not re.search(r'\bprefetch(?:t[012]|nta|it[01])\b',check)
                restored=bytearray(patched)
                for patch in patches:
                    raw=bytes.fromhex(patch['original']);offset=patch['offset']
                    assert patched[offset:offset+len(raw)].hex()==patch['nop']
                    restored[offset:offset+len(raw)]=raw
                assert restored==source and len(patched)==len(source)
                record.update(nop=str(control),nop_sha256=b.sha(control),exact_layout_verified=True,
                    changed_bytes=sum(x!=y for x,y in zip(source,patched)))
                import hashlib
                record['nop_executable_sections']=[dict(va=v,offset=o,size=s,
                    sha256=hashlib.sha256(patched[o:o+s]).hexdigest()) for v,o,s in sections]
                with gzip.open(binary.with_suffix('.patches.json.gz'),'wt') as f:json.dump(patches,f,separators=(',',':'))
                arms[arm+'_nop']['overrides'][key]=str(control)
            arms[arm]['overrides'][key]=str(binary);records.append(record)
            b.save(root/(prefix+'binary_audit.json'),records)
    b.save(root/(prefix+'arms.json'),arms)


def study(root,name,arms,blocks,seedbase,pmu=False,same_seed=False):
    import fullset as h
    from fullset_study import summarize,metrics
    out=root/name;out.mkdir(exist_ok=False)
    b.save(out/'protocol.json',dict(arms=arms,blocks=blocks,seedbase=seedbase,same_seed=same_seed,
        roi_s=90,rate=1000,pool=8,warmup_s=50,pmu_after_primary=pmu,
        order='Rotate two positions each block, reverse odd blocks',
        invalid='No timing-based retries; stop and retain all evidence if operating gate fails'))
    rows=[];names=list(arms)
    for block in range(blocks):
        offset=2*block%len(names);order=names[offset:]+names[:offset]
        if block%2:order.reverse()
        for arm in order:
            dest=out/f'{block:02d}_{arm}'
            spec=dict(out=str(dest),family='media',pool=8,rate=1000,roi_s=90,
                seed=seedbase+(0 if same_seed else block),overrides=arms[arm]['overrides'],
                pmu=list(b.SERVICES) if pmu and block==0 else [],
                pmu_events=h.c.EVENTS+',cpu/event=0x24,umask=0x28,name=SWPF_MISS/u,cpu/event=0x24,umask=0xc8,name=SWPF_HIT/u')
            manifest=dest.with_suffix('.json');b.save(manifest,spec)
            h.platform(dest,['python3',Path(h.__file__),'trial',manifest])
            result=read(dest/'result.json');values=metrics(result)
            values.update({k:result['pool'][k] for k in ('mean_ms','p50_ms','p95_ms','p99_ms')})
            row=dict(block=block,arm=arm,valid=result['valid'],metrics=values,output=str(dest),
                achieved_rps=result['pool']['achieved_rps'],pool_util_pct=result['pool_util_pct'])
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
            assert result['valid'],f'Operating failure retained: {dest}'
    b.save(out/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))
    return summarize(rows,arms)


def remove_arm(root,arm,reason):
    from e2e_lbr import remove_generated
    paths=[Path(str(root/'builds'/arm/key/exe)+suffix) for key,exe in b.SERVICES.items() for suffix in ('','.nop')]
    assert all(p.is_relative_to(root/'builds'/arm) for p in paths)
    remove_generated(paths,root/(arm+'_rejected_cleanup.json'),reason)


def campaign(root):
    arms=read(root/'arms.json')
    b.save(root/'measurement_protocol.json',dict(
        primary='External mean/p99 latency; whole-stack CPU/request reported independently',
        baseline_variation='Four fresh-stack A/A repeats, same request seed, 90-second ROI',
        screen='Two independent seed blocks, seven arms, 90-second clean ROI; PMU after first block ROI',
        selection='Eligible if whole-stack CPU point estimate improves versus both original and NOP, '
            'mean/p99 point estimates never regress more than 2% versus either control, and one latency endpoint improves versus both. '
            'Choose largest minimum mean-latency reduction; screening is exploratory only.',
        confirmation='If eligible, seven NEW seed blocks of base/NOP/selected. Retain only if stack CPU 95% lower bound positive against both '
            'controls and one same latency endpoint has a positive 95% lower bound against both; mean/p99 point regressions <=2%. '
            'Individual paired log-ratio t intervals, no multiple-endpoint adjustment.',
        cleanup='Rejected binaries and NOP twins removed immediately after decision; patches, hashes and measurements retained',
        scaling='No-prefetch baseline, concurrency 1/2/4/8/16/32; three fresh-stack blocks, 60-second ROI; dispatch-to-completion latency.'))
    study(root,'baseline_aa',{'base':arms['base']},4,41001,same_seed=True)
    aa=read(root/'baseline_aa/rows.json')
    b.save(root/'baseline_variation.json',{key:dict(mean=statistics.mean(v:= [r['metrics'][key] for r in aa]),
        cv_pct=100*statistics.stdev(v)/statistics.mean(v),minimum=min(v),maximum=max(v))
        for key in ('stack_cpu','mean_ms','p99_ms')})
    order=['base','callee8_nop','callee8','seq4k_nop','seq4k','seq256_nop','seq256']
    screen=study(root,'screen',{k:arms[k] for k in order},2,42001,pmu=True)
    eligible=[]
    for arm in b.ARMS:
        if arm=='base':continue
        comparisons=[screen[arm][control] for control in ('base',arm+'_nop')]
        cpu=all(v['stack_cpu']['cost_reduction_pct']>0 for v in comparisons)
        safe=all(v[k]['cost_reduction_pct']>=-2 for v in comparisons for k in ('mean_ms','p99_ms'))
        latency=any(all(v[k]['cost_reduction_pct']>0 for v in comparisons) for k in ('mean_ms','p99_ms'))
        if cpu and safe and latency:eligible.append((min(v['mean_ms']['cost_reduction_pct'] for v in comparisons),arm))
    winner=max(eligible)[1] if eligible else None
    b.save(root/'selection.json',dict(winner=winner,eligible=eligible,screen=screen))
    for arm in b.ARMS:
        if arm not in ('base',winner):remove_arm(root,arm,'Dense screening failed eligibility or was superseded by the prespecified selection; compact outcomes and patch records retained')
    promoted=False;confirmation=None
    if winner:
        selected={k:arms[k] for k in ('base',winner+'_nop',winner)}
        confirmation=study(root,'confirmation',selected,7,42501)
        comparisons=[confirmation[winner][control] for control in ('base',winner+'_nop')]
        cpu=all(v['stack_cpu']['ci95_pct'][0]>0 for v in comparisons)
        latency=any(all(v[k]['ci95_pct'][0]>0 for v in comparisons) for k in ('mean_ms','p99_ms'))
        safe=all(v[k]['cost_reduction_pct']>=-2 for v in comparisons for k in ('mean_ms','p99_ms'))
        promoted=cpu and latency and safe
    b.save(root/'dense_decision.json',dict(winner=winner,promoted=promoted,confirmation=confirmation))
    if winner and not promoted:remove_arm(root,winner,'Independent confirmation failed frozen net CPU and E2E criteria; compact evidence retained')
    from concurrency_study import campaign as scaling
    scaling(dict(out=str(root/'concurrency'),overrides=arms['base']['overrides'],
        blocks=3,roi_s=60,seedbase=43001,concurrencies=[1,2,4,8,16,32]))
    b.save(root/'measurements_complete.json',dict(dense_promoted=promoted,scaling_complete=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['audit','campaign']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[args.action](args.root)
