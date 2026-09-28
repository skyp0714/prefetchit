#!/usr/bin/env python3
"""Archive compact evidence before deleting rejected dominator executables."""
import argparse
import gzip
import json
import shutil
from pathlib import Path
import dense_build as b
from dominator_report import publish

def finish(root):
    assert (root/'screen_c4/complete.json').exists()
    eligible=publish(root)
    audit=json.loads((root/'binary_audit.json').read_text())
    targets=[]
    for row in audit:
        sections=row['nop_executable_sections'];good=bad=register=0;examples=[]
        path=Path(row['path']).with_suffix('.patches.json.gz')
        with gzip.open(path,'rt') as f:patches=json.load(f)
        for p in patches:
            if '(%rip)' not in p['instruction']:register+=1;continue
            raw=bytes.fromhex(p['original']);va=int(p['va'],16)
            target=va+len(raw)+int.from_bytes(raw[-4:],'little',signed=True)
            if any(s['va']<=target<s['va']+s['size'] for s in sections):good+=1
            else:
                bad+=1
                if len(examples)<10:examples.append(dict(site=p['va'],target=hex(target),instruction=p['instruction']))
        targets.append(dict(service=row['service'],rip_targets_in_executable_sections=good,
            rip_outside=bad,register_targets_runtime_only=register,examples=examples))
        assert not bad,targets[-1]
    b.save(root/'target_address_audit.json',targets)
    restore=[]
    for out in sorted((root/'screen_c4').glob('[01][01]_*')):
        if not out.is_dir() or out.name.endswith('_platform'):continue
        if not (out/'result.json').exists():continue
        v=json.loads(out.with_name(out.name+'_platform').joinpath('verified.json').read_text())
        scheduler=json.loads((out/'scheduler_restoration.json').read_text())
        clock=json.loads((out/'clock_restoration.json').read_text())
        assert v['restored'] and scheduler['restored'] and clock['unloaded']
        restore.append(dict(run=out.name,platform=v,scheduler=scheduler,clock=clock))
    assert len(restore)==8
    b.save(root/'restoration_audit.json',restore)
    if not eligible:
        from dense_study import remove_arm
        remove_arm(root,'dom_decay_v2','Completed two-block C4 screen failed predeclared net mean/CPU/p99 criteria. Raw PMU, request summaries, byte patches, source and ELF hashes retained.')
    from e2e_lbr import remove_generated
    temporary=[p for p in (root/'kernel_build').iterdir() if p.is_file() and p.name not in
               ('Makefile','prefetchit_sched_clock.c','prefetchit_sched_clock.ko')]
    temporary += [root/n for n in ('sched_runtime.o','probe','probe_base','clock_smoke') if (root/n).exists()]
    remove_generated(temporary,root/'temporary_cleanup.json','Completed validation/compile products; current reusable plugin/module, sources, smoke outputs and controls retained')
    for name in ('test_artifacts_v5','harness_tests'):
        b.remove_build(root/name,root/(name+'_cleanup.json'))
    publish(root) # Include completed target/restoration/cleanup audits.
    evidence=b.REPO/'llvm_prefetchit/migration/evidence/class_b_dominator_20260927'
    evidence.mkdir(exist_ok=False)
    # All compact settings, results, commands, counters and cleanup records.
    # Source inputs and large per-file build cleanup inventories stay local.
    files=list(root.glob('*.json'))+list(root.glob('compiler_tests*.log'))+list(root.glob('clock_smoke*.log'))
    files += [root/'harness_tests.log',root/'kernel_build_v2.log',root/'plugin_jammy_compile_v4.log']
    for out in (root/'screen_c4').iterdir():
        if out.is_file() and out.suffix=='.json':files.append(out)
        if out.is_dir() and not out.name.endswith('_platform'):
            files += [p for p in out.glob('*') if p.is_file() and (p.suffix=='.csv' or p.name in
                ('result.json','protocol.json','binary_hashes.json','clock_mapping_audit.json','clock_restoration.json','scheduler_restoration.json'))]
    for out in (root/'builds/dom_decay_v2').iterdir():
        if out.is_dir():
            files += list(out.glob('*.patches.json.gz'))+list(out.glob('binary.json'))
        elif out.name=='complete.json' or out.name.endswith('_installed_hashes.json'):files.append(out)
    manifest=[]
    for p in sorted(set(files)):
        if not p.exists():continue
        rel=p.relative_to(root);dest=evidence/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        if (p.stat().st_size>2*1024*1024 and p.suffix=='.json') or p.name.startswith('compiler_tests'):
            dest=dest.with_name(dest.name+'.gz')
            with p.open('rb') as src,gzip.open(dest,'wb') as sink:shutil.copyfileobj(src,sink)
        else:shutil.copyfile(p,dest)
        manifest.append(dict(path=str(dest.relative_to(evidence)),sha256=b.sha(dest),bytes=dest.stat().st_size))
    b.save(evidence/'manifest.json',dict(original_root=str(root),files=manifest,
        retained_references=['Original baseline ELF in class_b_dense_20260927',str(root/'plugin_jammy/PrefetchITPass.so'),str(root/'kernel_build/prefetchit_sched_clock.ko')]))
    return eligible

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args();finish(a.root)
