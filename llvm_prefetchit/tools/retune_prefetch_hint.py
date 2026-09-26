#!/usr/bin/env python3
"""Change only PREFETCHT1's ModRM hint bits, preserving address and layout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from make_nop_control_binary import executable_sections


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--hint', choices=['t0','t2','nta'], required=True)
    a = p.parse_args()
    if a.output.exists(): p.error('output already exists')
    original = a.input.read_bytes(); data=bytearray(original)
    sections = executable_sections(str(a.input)); offsets=[]
    dis=subprocess.check_output(['objdump','-d','--insn-width=16',str(a.input)],text=True)
    for line in dis.splitlines():
        m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s+prefetcht1\s',line)
        if not m: continue
        address=int(m[1],16); raw=bytes.fromhex(m[2]); index=raw.find(b'\x0f\x18')
        if index<0 or (raw[index+2]>>3)&7 != 2: raise RuntimeError('unexpected T1 encoding')
        matches=[off+address-va+index+2 for va,off,size in sections if va<=address and address+len(raw)<=va+size]
        if len(matches)!=1: raise RuntimeError('ambiguous instruction mapping')
        pos=matches[0]
        if original[pos] != raw[index+2]: raise RuntimeError('disassembly byte mismatch')
        data[pos]=(data[pos]&~0x38)|({'t0':1,'t2':3,'nta':0}[a.hint]<<3); offsets.append(pos)
    if not offsets: raise RuntimeError('no T1 instructions found')
    if sum(x!=y for x,y in zip(original,data))!=len(offsets): raise RuntimeError('patch audit mismatch')
    a.output.write_bytes(data); a.output.chmod(a.input.stat().st_mode)
    print(json.dumps({'input_sha256':hashlib.sha256(original).hexdigest(),
                      'output_sha256':hashlib.sha256(data).hexdigest(), 'hint':a.hint,'patched':len(offsets)}))


if __name__=='__main__': main()
