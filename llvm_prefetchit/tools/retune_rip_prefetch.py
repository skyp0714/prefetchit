#!/usr/bin/env python3
"""Retune injected RIP-relative T1s in place without changing code layout.

The source must have no upstream T1 instructions. An all-T1 NOP twin of the
source is also the layout control for every resulting distance/density/hint arm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import subprocess

from make_nop_control_binary import executable_sections, MULTI_NOP


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--distance', type=int, required=True)
    ap.add_argument('--source-distance', type=int, required=True)
    ap.add_argument('--keep-every', type=int, default=1)
    ap.add_argument('--hint', choices=['t0','t1','t2','nta'], default='t1')
    ap.add_argument('--index', type=Path, required=True, help='cached verified patch offsets')
    a = ap.parse_args()
    if a.output.exists(): ap.error('output already exists')
    if a.keep_every < 1: ap.error('keep-every must be positive')
    data = bytearray(a.source.read_bytes()); digest = hashlib.sha256(data).hexdigest()
    if a.index.exists():
        index = json.loads(a.index.read_text())
        if index['sha256'] != digest: ap.error('cached index belongs to another binary')
        offsets = index['offsets']
    else:
        sections = executable_sections(str(a.source)); offsets = []
        dis = subprocess.check_output(['objdump','-d','--insn-width=16',str(a.source)],text=True)
        for line in dis.splitlines():
            if '\tprefetcht1 ' not in line: continue
            m = re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*prefetcht1\s',line)
            if not m: raise RuntimeError(f'cannot decode T1: {line}')
            addr = int(m[1],16); raw = bytes.fromhex(m[2])
            if len(raw) != 7 or raw[:3] != bytes.fromhex('0f1815'):
                raise RuntimeError('expected only seven-byte RIP-relative T1 instructions')
            matches = [off+addr-va for va,off,size in sections if va <= addr and addr+7 <= va+size]
            if len(matches) != 1: raise RuntimeError('ambiguous instruction address')
            offsets.append(matches[0])
        if not offsets: raise RuntimeError('no injected T1s found')
        a.index.write_text(json.dumps({'sha256':digest,'offsets':offsets}))
    kept = 0
    for i,off in enumerate(offsets):
        if data[off:off+3] != bytes.fromhex('0f1815') or struct.unpack_from('<i',data,off+3)[0] != a.source_distance:
            raise RuntimeError('source is not the expected sequential prefetch binary')
        if i % a.keep_every:
            data[off:off+7] = MULTI_NOP[7]
        else:
            data[off+2] = {'nta':0x05,'t0':0x0d,'t1':0x15,'t2':0x1d}[a.hint]
            struct.pack_into('<i',data,off+3,a.distance); kept += 1
    a.output.write_bytes(data)
    a.output.chmod(a.source.stat().st_mode | stat.S_IWUSR)
    meta = {'source':str(a.source),'source_sha256':digest,'sha256':hashlib.sha256(data).hexdigest(),
            'distance':a.distance,'hint':a.hint,'keep_every':a.keep_every,'prefetch_count':kept,
            'same_layout':True,'retuning':'binary displacement/hint/NOP only'}
    a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2))
    print(a.output.name,kept,flush=True)


if __name__ == '__main__': main()
