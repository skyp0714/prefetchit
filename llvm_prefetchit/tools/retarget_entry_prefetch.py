#!/usr/bin/env python3
"""Apply a sparse static entry plan inside existing seven-byte T1 slots.

Unused slots become equal-length NOPs. This isolates policy changes at a fixed
layout; it is NOT a clean rebuild of the sparse plan and retains the original
slot footprint. Only direct RIP-relative T1s and defined in-image targets are
supported. Native non-T1 hints, branches and all other bytes are preserved.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import subprocess

from make_nop_control_binary import executable_sections, MULTI_NOP


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path)
    p.add_argument('allocated_plan',type=Path,help='entry plan used to build the original slots')
    p.add_argument('new_plan',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--fit-to-slots',action='store_true',help='explicitly cap the plan to emitted slots and archive the applied subset')
    a=p.parse_args()
    if a.output.exists(): p.error('output already exists')
    old=json.loads(a.allocated_plan.read_text())['sites']; new=json.loads(a.new_plan.read_text())['sites']
    symbols={}; sites={}
    for line in subprocess.check_output(['nm','-S','--defined-only',str(a.binary)],text=True).splitlines():
        f=line.split()
        if len(f)!=4 or f[2] not in 'TtWw': continue
        address,size=int(f[0],16),int(f[1],16)
        symbols[f[3]]=(address,size)
        if f[3] in old:
            if address in sites: raise RuntimeError('ambiguous allocated site aliases')
            sites[address]=(f[3],size)
    addresses=sorted(sites); slots={}; sections=executable_sections(str(a.binary))
    original=a.binary.read_bytes(); data=bytearray(original); outside_code=set()
    proc=subprocess.Popen(['objdump','-d','--insn-width=16',str(a.binary)],stdout=subprocess.PIPE,text=True)
    for line in proc.stdout:
        m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s+prefetcht1\s',line)
        if not m: continue
        address=int(m[1],16); raw=bytes.fromhex(m[2])
        if len(raw)!=7 or raw[:3]!=b'\x0f\x18\x15': raise RuntimeError('requires seven-byte direct T1 slots')
        original_target=address+7+int.from_bytes(raw[3:],'little',signed=True)
        if not any(va<=original_target<va+size for va,off,size in sections): outside_code.add(original_target)
        i=bisect.bisect_right(addresses,address)-1
        if i<0: raise RuntimeError('T1 outside allocated plan')
        start=addresses[i]; name,size=sites[start]
        if address+7>start+size: raise RuntimeError('T1 outside allocated function')
        offsets=[off+address-va for va,off,size in sections if va<=address and address+7<=va+size]
        if len(offsets)!=1 or original[offsets[0]:offsets[0]+7]!=raw: raise RuntimeError('byte mapping mismatch')
        slots.setdefault(name,[]).append((address,offsets[0]))
    if proc.wait(): raise RuntimeError('disassembly failed')
    requested=sum(len(s['t']) for s in new.values())
    capped={}
    if a.fit_to_slots:
        fitted={}
        for name,entry in new.items():
            count=min(len(entry['t']),len(slots.get(name,[])))
            if count<len(entry['t']): capped[name]={'requested':len(entry['t']),'available':count}
            if count: fitted[name]={'k':7*count,'t':entry['t'][:count]}
        new=fitted
    for name,entry in new.items():
        if len(entry['t'])>len(slots.get(name,[])):
            raise RuntimeError(f'not enough allocated slots at {name}')
    emitted=0
    for name,locations in slots.items():
        targets=new.get(name,{}).get('t',[])
        for index,(address,offset) in enumerate(locations):
            patch=MULTI_NOP[7]
            if index<len(targets):
                symbol,delta,got=targets[index][:3]
                if got or symbol not in symbols: raise RuntimeError(f'target must be defined and direct: {symbol}')
                target,size=symbols[symbol]
                if not 0<=delta<size: raise RuntimeError('target offset outside symbol')
                displacement=target+delta-address-7
                patch=b'\x0f\x18\x15'+displacement.to_bytes(4,'little',signed=True)
                emitted+=1
            data[offset:offset+7]=patch
    if emitted!=sum(len(s['t']) for s in new.values()): raise RuntimeError('emission count mismatch')
    a.output.write_bytes(data); a.output.chmod(a.binary.stat().st_mode)
    audit={'original_sha256':hashlib.sha256(original).hexdigest(),
           'output_sha256':hashlib.sha256(data).hexdigest(),
           'allocated_plan_sha256':hashlib.sha256(a.allocated_plan.read_bytes()).hexdigest(),
           'new_plan_sha256':hashlib.sha256(a.new_plan.read_bytes()).hexdigest(),
           'allocated_slots':sum(map(len,slots.values())),'requested':requested,'emitted':emitted,
           'capped_sites':capped,
           'original_targets_outside_code':sorted(outside_code),
           'changed_bytes':sum(x!=y for x,y in zip(original,data)),
           'same_layout':True,'clean_sparse_rebuild':False}
    a.output.with_suffix(a.output.suffix+'.retarget.json').write_text(json.dumps(audit,indent=2))
    a.output.with_suffix(a.output.suffix+'.applied-plan.json').write_text(json.dumps({'sites':new},indent=2))
    print(json.dumps({k:v for k,v in audit.items() if k!='capped_sites'}))


if __name__=='__main__': main()
