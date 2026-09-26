#!/usr/bin/env python3
"""Split audited FeedSim staged entry/body hints without changing other bytes."""
import argparse, hashlib, json, re
from pathlib import Path
from make_nop_control_binary import disassemble, executable_sections

def inspect(source,control,symbol):
    original=source.read_bytes();nop=control.read_bytes();assert len(original)==len(nop)
    sections=executable_sections(str(source));sites=[];counts={0:0,64:0,128:0}
    for line in disassemble(str(source),symbol).splitlines():
        fields=line.split('\t',2)
        if len(fields)!=3 or 'prefetcht1' not in fields[2]:continue
        address=int(fields[0].rstrip(':'),16);raw=bytes.fromhex(fields[1])
        m=re.fullmatch(r'(?:rex\s+)?prefetcht1\s+(?:(0x[0-9a-f]+|[0-9]+))?\((%[a-z0-9]+)\)\s*',fields[2])
        assert m,('Uninspected staged operand',fields[2])
        disp=int(m[1],0) if m[1] else 0;assert disp in counts
        counts[disp]+=1
        offsets=[off+address-va for va,off,size in sections if va<=address and address+len(raw)<=va+size]
        assert len(offsets)==1;off=offsets[0];assert original[off:off+len(raw)]==raw
        assert original[off:off+len(raw)]!=nop[off:off+len(raw)]
        sites.append({'address':address,'offset':off,'length':len(raw),'displacement':disp,'base_register':m[2],'asm':fields[2]})
    assert counts=={0:3,64:3,128:3},counts
    # Source emits one far entry and two near body hints in each unrolled path.
    for i in range(0,9,3):
        group=sites[i:i+3];assert [x['displacement'] for x in group]==[0,64,128]
        assert group[1]['base_register']==group[2]['base_register']
    rebuilt=bytearray(original)
    for x in sites:
        off,n=x['offset'],x['length'];rebuilt[off:off+n]=nop[off:off+n]
    assert rebuilt==nop,'control differs outside selected staged hint sites'
    return original,nop,sites

def build(source,control,out,symbol,keep,near_entry=False):
    original,nop,sites=inspect(source,control,symbol)
    data=bytearray(original)
    for x in sites:
        off,n=x['offset'],x['length'];x['kept']=x['displacement'] in keep
        if not x['kept']:data[off:off+n]=nop[off:off+n]
    if near_entry:
        assert keep=={0,64,128}
        # Change only the entry hint's base register. Both source pointer
        # computations and every other instruction remain in the binary.
        regs=['rax','rcx','rdx','rbx','rsp','rbp','rsi','rdi']+[f'r{i}' for i in range(8,16)]
        for i in range(0,len(sites),3):
            entry,body=sites[i:i+2];reg=regs.index(body['base_register'][1:])
            off,n=entry['offset'],entry['length'];before=bytes(data[off:off+n])
            rm=reg%8
            operand=(b'\x14\x24' if rm==4 else b'\x55\x00' if rm==5 else bytes([0x10+rm]))
            encoded=(b'\x41' if reg>=8 else b'')+b'\x0f\x18'+operand
            # An otherwise redundant REX preserves the original instruction
            # length when changing a high register to a low register.
            if reg<8 and len(encoded)+1==n:encoded=b'\x40'+encoded
            assert len(encoded)==n,'Register encoding would change instruction length'
            data[off:off+n]=encoded
            entry.update(before=before.hex(),after=encoded.hex(),near_base_register=body['base_register'])
        reversed_data=bytearray(data)
        for x in sites:
            off,n=x['offset'],x['length'];reversed_data[off:off+n]=nop[off:off+n]
        assert reversed_data==nop
    assert not out.exists();out.write_bytes(data);out.chmod(0o755)
    if near_entry:
        _,_,decoded=inspect(out,control,symbol)
        assert [x['address'] for x in decoded]==[x['address'] for x in sites]
        assert all(len({x['base_register'] for x in decoded[i:i+3]})==1 for i in range(0,len(decoded),3))
    meta={'source_sha256':hashlib.sha256(original).hexdigest(),'control_sha256':hashlib.sha256(nop).hexdigest(),
          'sha256':hashlib.sha256(data).hexdigest(),'keep_displacements':sorted(keep),'sites':sites,
          'control_reversal_verified':True,'near_entry':near_entry,
          'semantics':('Entry and body+64/+128 at 4 calls; retains unused far-pointer work' if near_entry else 'Entry at 12 calls; body+64/+128 at 4 calls')+'; only for inspected staged source and emitted operand pattern'}
    Path(str(out)+'.json').write_text(json.dumps(meta,indent=2));return meta

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('control',type=Path);p.add_argument('out',type=Path);p.add_argument('--symbol',required=True);p.add_argument('--keep',type=int,nargs='+',required=True);p.add_argument('--near-entry',action='store_true');a=p.parse_args()
    print(json.dumps(build(a.source,a.control,a.out,a.symbol,set(a.keep),a.near_entry)))
