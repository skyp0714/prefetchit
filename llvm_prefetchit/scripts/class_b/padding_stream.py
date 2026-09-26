#!/usr/bin/env python3
"""Trace-ranked T1s in existing in-function NOPs, including static libraries.

Original load addresses, branches, instruction lengths and register/flag effects
are preserved. The unchanged baseline is the exact NOP control. Consensus-line
occurrence is a candidate proxy: it does not prove execution of an individual NOP.
"""
import argparse
import bisect
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess

REPO=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('wake_elf',REPO/'llvm_prefetchit/kernel/wake_prefetch/control.py')
elf=importlib.util.module_from_spec(spec);spec.loader.exec_module(elf)
NOPS={7:bytes.fromhex('0f1f8000000000'),8:bytes.fromhex('0f1f840000000000')}


def digest(data):return hashlib.sha256(data).hexdigest()


def read_types(runs,pmin):
    counts=collections.Counter()
    for line in (runs/'runs.tsv').read_text().splitlines()[1:]:
        r=line.split('\t');counts[r[4]+'__m'+r[6]]+=1
    types={}
    for p in sorted(runs.glob('list_*.tsv')):
        name=p.stem[5:]
        if '__all' in name or '__shadow' in name or not counts[name]:continue
        rows=[]
        for line in p.read_text().splitlines():
            if line.startswith('#'):continue
            r=line.split('\t')
            if len(r)>=7 and float(r[1])>=pmin:
                rows.append(dict(p=float(r[1]),dso=r[4],line=int(r[5],16),rank=float(r[2])))
        types[name]=(counts[name],rows)
    return types


def inventory(binary,data,allow_loops=False):
    symbols={}
    for line in subprocess.check_output(['nm','-nS','--defined-only',str(binary)],text=True).splitlines():
        r=line.split()
        if len(r)==4 and r[2] in 'TtWw' and int(r[1],16):
            symbols.setdefault(int(r[0],16),(int(r[1],16),r[3]))
    starts=sorted(symbols);segments=elf.executable_segments(data)
    slots=[];backedges=[]
    command=['objdump','-d','--insn-width=16',str(binary)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,text=True)
    for line in process.stdout:
        m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$',line)
        if not m:continue
        va=int(m[1],16);raw=bytes.fromhex(m[2]);asm=m[3]
        i=bisect.bisect_right(starts,va)-1
        if i<0:continue
        start=starts[i];size,name=symbols[start]
        if va+len(raw)>start+size:continue
        branch=re.match(r'j\w+\s+([0-9a-f]+)\s',asm)
        if branch and start<=int(branch[1],16)<=va:
            backedges.append((int(branch[1],16),va))
        if raw!=NOPS.get(len(raw)) or not re.match(r'nop[wl]?\b',asm):continue
        offsets=[off+va-address for off,address,length in segments if address<=va and va+len(raw)<=address+length]
        assert len(offsets)==1 and data[offsets[0]:offsets[0]+len(raw)]==raw
        slots.append(dict(va=va,offset=offsets[0],size=len(raw),function=name,start=start))
    assert process.wait()==0
    # A direct backward branch is sufficient to exclude a slot. Irreducible or
    # indirect loops and dynamic call frequency are not inferred from this test.
    eligible=[s for s in slots if not any(lo<=s['va']<=hi for lo,hi in backedges)]
    return (slots if allow_loops else eligible),dict(canonical_in_function_slots=len(slots),
        outside_direct_backedge_loops=len(eligible),allow_loops=allow_loops,commands=[command])


def choose(slots,types,exe,lead,window,cap,per_function):
    by_line=collections.defaultdict(list)
    for slot in slots:by_line[slot['va']&~63].append(slot)
    scores=collections.defaultdict(collections.Counter)
    for count,rows in types.values():
        if count<12:continue
        for i,row in enumerate(rows):
            if row['dso']!=exe or row['p']<.8:continue
            candidates=[v for v in rows[i+lead:i+window] if v['dso']==exe and v['line']!=row['line']]
            for slot in by_line.get(row['line'],[]):
                for distance,target in enumerate(candidates,lead):
                    scores[slot['va']][target['line']]+=count*target['p']/(1+distance/window)
    ranked=[]
    for slot in slots:
        if scores[slot['va']]:
            target,score=max(scores[slot['va']].items(),key=lambda x:(x[1],-x[0]))
            ranked.append(dict(**slot,target=target,score=score))
    ranked.sort(key=lambda x:(-x['score'],x['va']))
    used_lines=set();used_targets=set();functions=collections.Counter();selected=[]
    for slot in ranked:
        line=slot['va']&~63
        if line in used_lines or slot['target'] in used_targets or functions[slot['start']]>=per_function:continue
        used_lines.add(line);used_targets.add(slot['target']);functions[slot['start']]+=1
        selected.append(slot)
        if len(selected)==cap:break
    return selected


def patch(data,slots):
    result=bytearray(data);segments=elf.executable_segments(data);patches=[]
    for slot in slots:
        size=slot['size'];offset=slot['offset'];target=slot['target']
        assert data[offset:offset+size]==NOPS[size]
        assert any(va<=target<va+n for _,va,n in segments),'target outside executable segment'
        raw=b'\x66'*(size-7)+b'\x0f\x18\x15'+struct.pack('<i',target-slot['va']-size)
        assert len(raw)==size
        result[offset:offset+size]=raw
        patches.append(dict(**slot,before=NOPS[size].hex(),after=raw.hex()))
    reverse=bytearray(result)
    for p in patches:reverse[p['offset']:p['offset']+p['size']]=bytes.fromhex(p['before'])
    assert reverse==data
    return bytes(result),patches


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path);p.add_argument('runs',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--lead',type=int,default=8);p.add_argument('--window',type=int,default=48)
    p.add_argument('--cap',type=int,default=256);p.add_argument('--per-function',type=int,default=2)
    p.add_argument('--p-min',type=float,default=.8)
    p.add_argument('--allow-loops',action='store_true',help='explicit coverage experiment; hints may execute repeatedly')
    a=p.parse_args()
    assert not a.output.exists() and 0<a.lead<a.window and a.cap>0 and a.per_function>0
    source=a.binary.read_bytes();slots,meta=inventory(a.binary,source,a.allow_loops)
    selected=choose(slots,read_types(a.runs,a.p_min),a.binary.name,a.lead,a.window,a.cap,a.per_function)
    assert selected,'no eligible trace-ranked NOPs'
    result,patches=patch(source,selected)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(result);a.output.chmod(0o755)
    record=dict(source=str(a.binary),source_sha256=digest(source),sha256=digest(result),baseline_is_exact_nop_twin=True,
        tool_sha256=digest(Path(__file__).read_bytes()),
        training_sha256={p.name:digest(p.read_bytes()) for p in sorted(a.runs.glob('*.tsv'))},
        scope='All statically linked in-image functions with supported NOP slots; no shared-library rewrite',
        settings=dict(**vars(a),minimum_type_runs=12),inventory=meta,sites=len(patches),patches=patches,
        limitations=['Consensus first-touch paths do not prove NOP execution or joint target accuracy.',
                    'Loop exclusion follows allow_loops. Dynamic repeated execution is not measured by consensus marginals.',
                    'Original ELF layout and code bytes outside recorded NOP slots are unchanged.'])
    a.output.with_name(a.output.name+'.json').write_text(json.dumps(record,indent=2,default=str)+'\n')
    print(json.dumps(dict(sites=len(patches),sha256=digest(result),inventory=meta)),flush=True)


if __name__=='__main__':main()
