#!/usr/bin/env python3
"""Change only the ModRM byte of audited call-stub T1 hints to IT0 or IT1."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import dense_build as b
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
from call_stub_prefetch import Elf,sha
from e2e_lbr import remove_generated


def build(source,dest,kind='it0'):
    source,dest=Path(source),Path(dest)
    assert kind in ['it0','it1'] and not dest.exists()
    audit_path=Path(str(source)+'.json');audit=json.loads(audit_path.read_text())
    original=source.read_bytes();assert sha(original)==audit['sha256'],'Source fingerprint mismatch'
    elf=Elf(original);section,_=elf.section('.text.prefetch_calls');changes=[];data=bytearray(original)
    wanted={row['va']:row for row in audit['hints']};assert len(wanted)==len(audit['hints'])>0
    for va,row in wanted.items():
        offset=elf.offset(va,7,True)
        assert offset==row['offset'] and section[3]<=va and va+7<=section[3]+section[5]
        raw=original[offset:offset+7]
        assert raw.hex()==row['original'] and raw[:3]==bytes.fromhex('0f1815')
        assert va+7+struct.unpack_from('<i',raw,3)[0]==row['target']
        data[offset+2]=0x3d if kind=='it0' else 0x35;changes.append(offset+2)
    reverse=bytearray(data)
    for offset in changes:reverse[offset]=0x15
    assert bytes(reverse)==original and len(data)==len(original)
    assert sum(left!=right for left,right in zip(data,original))==len(changes)
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent)
    transform=dict(source=str(source),source_sha256=audit['sha256'],parent_record_sha256=b.sha(audit_path),
        kind=kind,byte_offsets=changes,before_byte='15',after_byte='3d' if kind=='it0' else '35',
        targets_and_addresses_unchanged=True,only_selected_modrm_bytes_differ=True,
        extra_instruction_bytes=0,fully_reversible=True,source_sha256_tool=b.sha(__file__))
    try:
        dest.write_bytes(data);dest.chmod(source.stat().st_mode)
        command=['objdump','-d','-j','.text.prefetch_calls','--insn-width=16',str(dest)]
        b.save(Path(str(dest)+'.decode.command.json'),command)
        disassembly=subprocess.check_output(command,text=True);Path(str(dest)+'.asm').write_text(disassembly)
        found=set()
        for line in disassembly.splitlines():
            match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$',line)
            if not match:continue
            va=int(match[1],16)
            if va not in wanted:continue
            target=re.search(r'#\s*([0-9a-f]+)',match[3])
            assert len(bytes.fromhex(match[2]))==7 and match[3].startswith('prefetch'+kind)
            assert target and int(target[1],16)==wanted[va]['target'];found.add(va)
        assert found==set(wanted),'Not every transformed hint decoded at its original address'
        hints=[dict(row,original=bytes(data[row['offset']:row['offset']+7]).hex()) for row in audit['hints']]
        result=dict(audit,sha256=b.sha(dest),hints=hints,opcode_transform=transform)
        b.save(Path(str(dest)+'.json'),result)
        b.save(Path(str(dest)+'.opcode.json'),dict(transform,sha256=result['sha256'],sites=len(wanted),bytes=len(data)))
        return dict(binary=str(dest),sha256=result['sha256'],sites=len(wanted),kind=kind,nop_sha256=audit['nop_sha256'])
    except BaseException as error:
        b.save(Path(str(dest)+'.failure.json'),dict(transform,error=repr(error)))
        if dest.exists():remove_generated([dest],Path(str(dest)+'.cleanup.json'),'Instruction-hint transform rejected; source, patches, hashes and validation failure retained.')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('dest',type=Path)
    p.add_argument('--kind',choices=['it0','it1'],default='it0');a=p.parse_args()
    print(json.dumps(build(a.source,a.dest,a.kind)))
