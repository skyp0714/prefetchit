#!/usr/bin/env python3
"""Index canonical NOP instructions across executable sections for LBR selection.

Unlike the static call/sequence policy index, this does not require exported
function symbols. Use only with an execution-profile selector: padding outside
an observed executed basic-block segment must never be selected.
"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
from make_nop_control_binary import executable_sections,MULTI_NOP

def is_padding_nop(raw):
    if not 7<=len(raw)<=15:return False
    body=raw
    while body and body[0] in (0x66,0x2e):body=body[1:]
    return body in (MULTI_NOP[7],MULTI_NOP[8])

def parse_slots(disassembly,sections):
    slots=[]
    for line in disassembly.splitlines():
        parts=line.split('\t')
        if len(parts)<3 or not re.search(r'\bnop[wl]?\b',parts[2]):continue
        try:
            address=int(parts[0].strip().rstrip(':'),16)
            raw=bytes.fromhex(parts[1])
        except ValueError:continue
        length=len(raw)
        if not is_padding_nop(raw):continue
        matches=[(offset+address-va,va+size) for va,offset,size in sections if va<=address and address+length<=va+size]
        if len(matches)!=1:continue
        offset,end=matches[0];slots.append([address,offset,length,end,raw.hex()])
    if len({s[0] for s in slots})!=len(slots):raise ValueError('duplicate executable NOP address')
    return sorted(slots)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.exists():p.error('output exists')
    sections=executable_sections(str(a.source));data=a.source.read_bytes()
    disassembly=subprocess.check_output(['objdump','-d','--insn-width=16',str(a.source)],text=True)
    slots=parse_slots(disassembly,sections)
    for address,offset,length,end,raw_hex in slots:
        assert data[offset:offset+length]==bytes.fromhex(raw_hex)
    result={'sha256':hashlib.sha256(data).hexdigest(),'functions':'all executable NOPs; requires LBR execution evidence','requires_execution_profile':True,'slots':slots,'calls':[]}
    a.output.write_text(json.dumps(result));print(json.dumps({'slots':len(slots),'source_sha256':result['sha256']}))
if __name__=='__main__':main()
