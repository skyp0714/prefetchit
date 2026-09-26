#!/usr/bin/env python3
"""Replace canonical in-function 7/8-byte NOPs with same-size code prefetches.

No code movement or instruction-count change. Reversing the recorded patches
reproduces the source byte-for-byte, including any native prefetch instructions.
Targets stay within their owning function.
This is a static binary-analysis experiment, independent of miss profiles.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from make_nop_control_binary import executable_sections, MULTI_NOP


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('output',type=Path)
    ap.add_argument('--distance',type=int,required=True)
    ap.add_argument('--next-call',action='store_true',help='prefetch a following direct callee instead of sequential code')
    ap.add_argument('--min-call-lead',type=int,default=32,help='minimum static bytes to the call')
    ap.add_argument('--functions',default='fleetbench5proto')
    ap.add_argument('--index',type=Path,required=True)
    a = ap.parse_args()
    if a.output.exists(): ap.error('output exists')
    data = bytearray(a.source.read_bytes()); digest = hashlib.sha256(data).hexdigest()
    if a.index.exists():
        ix = json.loads(a.index.read_text())
        if ix['sha256'] != digest or ix['functions'] != a.functions: ap.error('index mismatch')
        slots = ix['slots']; calls = ix.get('calls',[])
        if a.next_call and 'calls' not in ix: ap.error('use a fresh index with call metadata')
    else:
        sections = executable_sections(str(a.source)); bounds = {}; slots = []; calls = []
        symbol_text = subprocess.check_output(['nm','-S','--defined-only',str(a.source)],text=True,stderr=subprocess.DEVNULL)
        if not symbol_text.strip():
            symbol_text = subprocess.check_output(['nm','-D','-S','--defined-only',str(a.source)],text=True)
        for line in symbol_text.splitlines():
            f = line.split()
            if len(f) == 4 and f[2] in 'TtWw' and re.search(a.functions,f[3]):
                bounds[int(f[0],16)] = int(f[0],16)+int(f[1],16)
        cur = None
        for line in subprocess.check_output(['objdump','-d','--insn-width=16',str(a.source)],text=True).splitlines():
            head = re.match(r'^([0-9a-f]+) <',line)
            if head: cur = bounds.get(int(head[1],16)); continue
            parts = line.split('\t')
            if cur is not None and len(parts) >= 3:
                call = re.search(r'\bcallq?\s+([0-9a-f]+)\s+<',parts[2])
                if call and int(call[1],16) in bounds:
                    calls.append([int(parts[0].strip().rstrip(':'),16),int(call[1],16)])
            if cur is None or len(parts) < 3 or not re.search(r'\bnop[wl]?\b',parts[2]): continue
            raw = bytes.fromhex(parts[1]); n = len(raw)
            if n not in (7,8) or raw != MULTI_NOP[n]: continue
            addr = int(parts[0].strip().rstrip(':'),16)
            if addr+n > cur: continue  # exclude padding after the function's return
            matches = [off+addr-va for va,off,size in sections if va <= addr and addr+n <= va+size]
            if len(matches) != 1: raise RuntimeError('cannot map padding')
            slots.append([addr,matches[0],n,cur])
        a.index.write_text(json.dumps({'sha256':digest,'functions':a.functions,'slots':slots,'calls':calls}))
    calls.sort(); call_addresses = [c[0] for c in calls]
    count = 0; patches = []
    for addr,off,n,end in slots:
        target = addr+n+a.distance
        if a.next_call:
            i = bisect.bisect_left(call_addresses,addr+n+a.min_call_lead)
            if i == len(calls) or calls[i][0] >= end or calls[i][0] > addr+n+a.distance: continue
            target = calls[i][1]
        elif target >= end: continue
        assert data[off:off+n] == MULTI_NOP[n]
        before = bytes(data[off:off+n])
        after = b'\x66'*(n-7)+bytes.fromhex('0f1815')+struct.pack('<i',target-addr-n)
        data[off:off+n] = after
        patches.append({'address':addr,'offset':off,'target':target,'before':before.hex(),'after':after.hex()})
        count += 1
    if not count: raise RuntimeError('no eligible padding')
    twin = bytearray(data)
    for patch in patches:
        off = patch['offset']; raw = bytes.fromhex(patch['before'])
        twin[off:off+len(raw)] = raw
    assert hashlib.sha256(twin).hexdigest() == digest, 'patch reversal differs from source'
    a.output.write_bytes(data); a.output.chmod(0o755)
    a.output.with_suffix('.json').write_text(json.dumps({'source_sha256':digest,
        'sha256':hashlib.sha256(data).hexdigest(),'distance':a.distance,'sites':count,
        'twin':str(a.source),'static_selection':a.functions,'next_call':a.next_call,
        'min_call_lead':a.min_call_lead,'reversed_patches_sha256':digest,'patches':patches},indent=2))
    print(a.output.name,count,flush=True)


if __name__ == '__main__': main()
