#!/usr/bin/env python3
"""Serial follow-up after opcode screening: validate, calibrate, then profile."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import dense_build as b
import fullset as h
from lean_plan import sections

def run(root):
    assert (root/'screen/complete.json').exists()
    b.space(root)
    b.save(root/'followup_start.json',dict(space={x:shutil.disk_usage(x)._asdict() for x in ['/','/storage']},
        order=['Native opcode/coverage tests','Same-address microprobe build/audit','Serial microprobe measurement','Fresh NOP PEBS training'],
        source_sha256=b.sha(__file__)))
    tests=[b.REPO/'llvm_prefetchit/tests'/name for name in ['test_lean_it0.py','test_mechanism_opcode.py','test_residual_retarget.py']]
    command=[b.REPO/'profiling/.venv/bin/python','-m','pytest','-q','--basetemp',root/'test_work',*tests]
    b.run(command,root/'tests.log')
    from e2e_lbr import remove_generated
    fixture_files=[p for p in (root/'test_work').rglob('*') if p.is_file() and not p.is_symlink()]
    b.save(root/'test_fixture_sources.json',{str(p.relative_to(root/'test_work')):p.read_text() for p in fixture_files if p.suffix=='.c'})
    remove_generated(fixture_files,root/'test_cleanup.json','Passed native opcode tests; test/source and compile input records retained.')
    binaries={};symbol_maps={}
    for index,kind in enumerate(['nop','it0','it1','t1']):
        b.space(root);dest=root/('probe_fixed_'+kind)
        command=['gcc','-O2','-Wall','-Wextra','-fno-pie','-no-pie','-Wl,--build-id=none',f'-DHINT={index}',
                 b.REPO/'llvm_prefetchit/scripts/class_b/prefetch_probe_fixed.c','-o',dest]
        b.run(command,root/('probe_fixed_'+kind+'.build.log'))
        binaries[kind]=dest.read_bytes()
        symbols={}
        for line in subprocess.check_output(['nm','-n',str(dest)],text=True).splitlines():
            parts=line.split()
            if len(parts)==3 and parts[2] in ('hint_site','cold_target','decode_pad','icache_pad'):
                symbols[parts[2]]=int(parts[0],16)
        symbol_maps[kind]=symbols
    assert all(x==symbol_maps['nop'] for x in symbol_maps.values())
    table=sections(binaries['nop']);site=symbol_maps['nop']['hint_site']
    section=next(x for x in table if x['va']<=site<x['va']+x['size'] and x['flags']&4)
    offset=section['offset']+site-section['va'];audits=[]
    for kind,data in binaries.items():
        base=binaries['nop'];assert len(data)==len(base)
        changes=[i for i,(a,z) in enumerate(zip(base,data)) if a!=z]
        assert all(offset<=i<offset+7 for i in changes)
        audits.append(dict(kind=kind,path=str(root/('probe_fixed_'+kind)),sha256=b.sha(root/('probe_fixed_'+kind)),
                          differing_offsets=changes,hint_bytes=data[offset:offset+7].hex()))
    b.save(root/'probe_fixed_audit.json',dict(symbols=symbol_maps['nop'],hint_file_offset=offset,records=audits,
        same_layout=True,only_hint_bytes_differ=True,source_sha256=b.sha(b.REPO/'llvm_prefetchit/scripts/class_b/prefetch_probe_fixed.c')))
    h.platform(root/'probe_fixed_run',['python3',Path(__file__).with_name('mechanism_probe.py'),root,'--fixed'])
    h.platform(root/'retarget_training_run',['python3',Path(__file__).with_name('dense_causes.py'),'trial',root/'retarget_training_spec.json'])
    b.save(root/'followup_complete.json',dict(calibration=True,training=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root)
