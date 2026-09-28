#!/usr/bin/env python3
"""Change only direct RIP-relative T1 hints to IT0, preserving every address."""
import argparse
import gzip
import json
from pathlib import Path
import re
import subprocess
import dense_build as b


def patch(source, dest, expected_sha):
    b.space(dest.parent)
    assert source.is_file() and not source.is_symlink() and not dest.exists()
    assert b.sha(source)==expected_sha
    original=source.read_bytes();data=bytearray(original)
    sites=json.load(gzip.open(source.with_suffix('.patches.json.gz'),'rt'))
    changes=[];unchanged=0
    for site in sites:
        raw=bytes.fromhex(site['original']);offset=site['offset']
        assert original[offset:offset+len(raw)]==raw
        if '(%rip)' not in site['instruction']:
            unchanged+=1;continue
        assert len(raw)==7 and raw[:3]==b'\x0f\x18\x15',site
        data[offset+2]=0x3d
        changes.append(dict(offset=offset+2,original='15',replacement='3d',va=site['va'],
                            target_before=site['instruction']))
    assert changes
    dest.write_bytes(data);dest.chmod(source.stat().st_mode)
    command=['objdump','-d','--insn-width=16',str(dest)]
    dis=subprocess.check_output(command,text=True)
    instructions={};prefetch=[]
    for line in dis.splitlines():
        match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
        if not match:continue
        va=int(match[1],16);instructions[va]=match[3]
        if match[3].split()[0].startswith('prefetch'):prefetch.append((va,match[3]))
    assert sum('prefetchit0' in s for _,s in prefetch)==len(changes)
    assert sum('prefetcht1' in s for _,s in prefetch)==unchanged
    for change in changes:
        after=instructions[int(change['va'],16)]
        assert after.startswith('prefetchit0') and '(%rip)' in after
        before_target=re.search(r'#\s*([0-9a-f]+)',change['target_before'])
        after_target=re.search(r'#\s*([0-9a-f]+)',after)
        assert before_target and after_target and before_target[1]==after_target[1]
        assert int(after_target[1],16) in instructions,'Target must begin a real instruction'
    restored=bytearray(data)
    for change in changes:restored[change['offset']]=0x15
    assert restored==original and sum(a!=b for a,b in zip(original,data))==len(changes)
    with gzip.open(dest.with_suffix('.it0_patches.json.gz'),'wt') as f:json.dump(changes,f,separators=(',',':'))
    record=dict(source=str(source),source_sha256=expected_sha,path=str(dest),sha256=b.sha(dest),
                bytes=len(data),changed_bytes=len(changes),it0_rip_sites=len(changes),retained_t1_register_sites=unchanged,
                same_layout=True,all_targets_instruction_boundaries=True,disassembly_command=command,
                isa='https://cdrdv2-public.intel.com/774990/architecture-instruction-set-extensions-programming-reference.pdf')
    b.save(dest.with_suffix('.it0.json'),record)
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('dest',type=Path)
    p.add_argument('--sha256',required=True);a=p.parse_args();patch(a.source,a.dest,a.sha256)


def deduplicate_groups(source, sites_path, dest, expected_sha):
    """Diagnostic: remove same-line RIP hints within contiguous batches only.

    This preserves code size/layout. A successful result motivates compiler
    removal; it is not itself a claim of reduced executable size.
    """
    import sys
    sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
    from make_nop_control_binary import MULTI_NOP
    b.space(dest.parent)
    assert source.is_file() and not source.is_symlink() and not dest.exists()
    assert b.sha(source)==expected_sha
    data=source.read_bytes();patched=bytearray(data);sites=json.load(gzip.open(sites_path,'rt'))
    changes=[];groups=[];end=None
    for site in sites:
        va=int(site['va'],16);raw=bytes.fromhex(site['original']);offset=site['offset']
        current=data[offset:offset+len(raw)]
        if va!=end:groups.append(dict(before=set(),after=set(),hints=0,removed=0))
        group=groups[-1];end=va+len(raw);group['hints']+=1
        if '(%rip)' not in site['instruction']:
            assert current==raw;continue
        assert len(raw)==7 and raw[:3]==b'\x0f\x18\x15'
        assert current[:3] in (b'\x0f\x18\x15',b'\x0f\x18\x3d') and current[3:]==raw[3:]
        target=int(re.search(r'#\s*([0-9a-f]+)',site['instruction'])[1],16)//64
        group['before'].add(target)
        if target in group['after']:
            replacement=MULTI_NOP[len(raw)];patched[offset:offset+len(raw)]=replacement
            changes.append(dict(offset=offset,va=site['va'],original=current.hex(),nop=replacement.hex(),target_line=hex(target*64)))
            group['removed']+=1
        else:group['after'].add(target)
    assert changes and all(g['before']==g['after'] for g in groups)
    restored=bytearray(patched)
    for row in changes:restored[row['offset']:row['offset']+len(bytes.fromhex(row['original']))]=bytes.fromhex(row['original'])
    assert restored==data and len(patched)==len(data)
    dest.write_bytes(patched);dest.chmod(source.stat().st_mode)
    with gzip.open(dest.with_suffix('.dedup_patches.json.gz'),'wt') as f:json.dump(changes,f,separators=(',',':'))
    audit=subprocess.check_output(['objdump','-d','--insn-width=16',str(dest)],text=True)
    actual=sum(bool(re.match(r'^\s*[0-9a-f]+:\s*(?:[0-9a-f]{2}\s+)+\s*prefetch(?:t1|it0)\b',line)) for line in audit.splitlines())
    assert actual==len(sites)-len(changes)
    record=dict(source=str(source),source_sha256=expected_sha,path=str(dest),sha256=b.sha(dest),bytes=len(patched),
        source_sites_sha256=b.sha(sites_path),removed_hints=len(changes),remaining_hints=actual,groups=len(groups),
        direct_line_set_preserved_in_every_group=True,same_layout=True,
        limitation='NOP thinning does not reduce code size; dynamic indirect targets are retained')
    b.save(dest.with_suffix('.dedup.json'),record)
    return record
