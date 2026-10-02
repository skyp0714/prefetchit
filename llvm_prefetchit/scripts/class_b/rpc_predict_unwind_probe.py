#!/usr/bin/env python3
"""Diagnose perf's flat file-offset load bias using offline-only ELF views.

No executable deployment or timing uses the generated non-executable views.
Every allocated section keeps its VA and contents. Only file layout and the
matching target-process MMAP offsets in a temporary perf copy are normalized.
"""
import argparse
import collections
import gzip
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

import dense_build as b
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
import call_stub_prefetch as stubs
from e2e_lbr import remove_generated
from rpc_predict_callchain import RpcAttribution, extract
from rpc_route_study import load
from wake_miss_timeline import LINE


def normalized_elf(source,output):
    raw=source.read_bytes();elf=stubs.Elf(raw)
    loads=[p for p in elf.ph if p[0]==1]
    data=bytearray(max(p[3]+p[5] for p in loads))
    for p in loads:data[p[3]:p[3]+p[5]]=raw[p[2]:p[2]+p[5]]
    sections=[];preserved=[]
    for name,original in zip(elf.names,elf.sh):
        row=list(original)
        if row[1]==0:pass
        elif row[2]&2:
            row[4]=row[3]
            if row[1]!=8:
                assert data[row[4]:row[4]+row[5]]==raw[original[4]:original[4]+original[5]],name
                preserved.append(dict(name=name,va=row[3],bytes=row[5]))
        elif row[1]!=8 and row[5]:
            offset=stubs.align(len(data),max(1,row[8]));data.extend(b'\0'*(offset-len(data)))
            row[4]=offset;data.extend(raw[original[4]:original[4]+original[5]])
        sections.append(row)
    ph=[list(p) for p in elf.ph]
    for p in ph:
        if p[5]:p[2]=p[3]
    phoff=next(p[3] for p in ph if p[0]==6)
    for i,p in enumerate(ph):stubs.PH.pack_into(data,phoff+i*stubs.PH.size,*p)
    shoff=stubs.align(len(data),8);data.extend(b'\0'*(shoff-len(data)))
    for s in sections:data.extend(stubs.SH.pack(*s))
    struct.pack_into('<QQ',data,32,phoff,shoff)
    # ELF/program headers are the only allocated bytes changed. Instructions,
    # original and appended CFI, dynamic tables and all other sections are exact.
    for name,old,new in zip(elf.names,elf.sh,sections):
        if old[2]&2 and old[1]!=8 and old[5]:
            assert raw[old[4]:old[4]+old[5]]==data[new[4]:new[4]+new[5]],name
    output.write_bytes(data);output.chmod(0o600)
    b.save(Path(str(output)+'.json'),dict(source=str(source),source_sha256=b.sha(source),
        sha256=b.sha(output),bytes=len(data),allocated_sections_verified=preserved,
        interpretation='Offline metadata view only; no execution. VAs and all allocated section bytes unchanged. File offsets, ELF/program/section headers and nonallocated section placement normalized.'))


def quick(root,out,path):
    attribution=RpcAttribution(root,load(out/'catalog.json'));rows=[];current=None
    pattern=re.compile(r'^\s+((?:0x)?[0-9a-fA-F]{1,16})\s+(.+)$')
    def finish():
        if current is not None:
            assert current['frames'];rows.append(current)
    with path.open() as stream:
        for line in stream:
            header=LINE.match(line)
            if header:
                finish();current=dict(identity=list(header.groups()[1:8]),frames=[]);continue
            match=pattern.match(line)
            if match and not re.match(r'^\([^)]*\)/(?:0x)?[0-9a-fA-F]+(?:\s|/)',match[2]):
                current['frames'].append(dict(address=attribution.resolve(int(match[1],16)),
                    inlined=match[2].endswith('(inlined)')))
    finish();counts=collections.Counter();rpc=collections.Counter()
    for row in rows:
        dso,ip=row['frames'][0]['address']
        kind='main_stub' if dso==attribution.main and any(p['stub']<=ip<max(p['terminal_jumps'])+5 for p in attribution.patches) else 'main_original' if dso==attribution.main else 'dso'
        physical=sum(not f['inlined'] for f in row['frames'])
        counts[kind,'samples']+=1;counts[kind,'two_physical_frames']+=physical>=2
        label=attribution.nearest([f['address'] for f in row['frames']])['labels']
        rpc['unique' if len(label)==1 else 'ambiguous' if label else 'missing']+=1
    return rows,dict(by_leaf={kind:{k:counts[kind,k] for k in ('samples','two_physical_frames')}
        for kind in ('main_stub','main_original','dso')},rpc_stack_context=dict(rpc),samples=len(rows))


def probe(root):
    out=root/'callchain/unwind_probe';assert load(out/'decode_ready.json')['valid']
    assert load(out/'unwind_debug_complete.json')['valid'];b.space(root)
    source=Path(__file__);(root/'source_versions'/(b.sha(source)+'.py')).write_bytes(source.read_bytes())
    debug=(out/'unwind_debug.log').read_text().splitlines()
    opens=[line for line in (out/'elf_open.log').read_text().splitlines() if '/custom/ComposeReviewService' in line]
    b.save(out/'unwind_debug_summary.json',dict(main_elf_open_attempts=opens,
        no_map_messages=sum('unwind: no map for' in line for line in debug),
        first_no_map_messages=[line for line in debug if 'unwind: no map for' in line][:8],
        main_proc_info_lookups=sum('unwind: find_proc_info dso /custom/ComposeReviewService' in line for line in debug),
        interpretation='The target main ELF opens successfully; the unwinder then asks for unmapped addresses while locating CFI. Unrelated process metadata from verbose perf/strace output is discarded.'))
    remove_generated([out/'unwind_debug.log',out/'elf_open.log'],out/'debug_cleanup.json',
        'Target-ELF open results and aggregate unwind failure diagnostics retained; verbose decoded logs no longer needed.')
    exact_rows,exact=quick(root,out,out/'events.txt')
    pids={int(v['identity'][0]) for v in exact_rows};assert len(pids)==1 and min(pids)>0
    pid=next(iter(pids));catalog=load(out/'catalog.json');views=out/'offline_views';views.mkdir()
    raw_copy=out/'normalized.perf.data';alternate=out/'events_normalized.txt';changes=[];mapped=[]
    b.save(out/'normalization_protocol.json',dict(epoch=time.time(),source_sha256=b.sha(source),target_pid=pid,
        reason='perf 6.8 libunwind uses min(map.start-map.pgoff) as a flat ELF bias. Appended PT_LOAD can have file offsets larger than VAs, making this estimate smaller than the true bias.',
        source='https://raw.githubusercontent.com/torvalds/linux/v6.8/tools/perf/util/unwind-libunwind-local.c',
        scope='Offline-only file-layout control on the identical capture. SAMPLE bytes, runtime virtual addresses and allocated ELF section contents unchanged. Not an endpoint experiment.'))
    try:
        for index,(name,entry) in enumerate(catalog.items()):
            binary=Path(entry['binary']);elf=stubs.Elf(binary.read_bytes())
            if not any(p[0]==1 and p[2]>p[3] for p in elf.ph):continue
            view=views/str(index);normalized_elf(binary,view)
            biases={m['bias'] for m in entry['mappings']};assert len(biases)==1
            mapped.append(dict(name=name,binary=str(binary),view=str(view),bias=next(iter(biases)),
                source_sha256=entry['sha256'],sha256=b.sha(view),loads=[p for p in elf.ph if p[0]==1]))
        assert any(v['name']=='/custom/ComposeReviewService' for v in mapped)
        shutil.copyfile(out/'perf.data',raw_copy);records=0
        by_name={v['name']:v for v in mapped}
        with raw_copy.open('r+b') as stream:
            with mmap.mmap(stream.fileno(),0) as data:
                header=struct.unpack_from('<9Q',data);offset,size=header[5:7];end=offset+size
                while offset<end:
                    kind,misc,length=struct.unpack_from('<IHH',data,offset);assert length>=8 and offset+length<=end
                    if kind in (1,10):
                        owner=struct.unpack_from('<I',data,offset+8)[0]
                        name_offset=offset+(40 if kind==1 else 72)
                        end_name=data.find(b'\0',name_offset,offset+length);assert end_name>=0
                        name=data[name_offset:end_name].decode(errors='replace')
                        if owner==pid and name in by_name:
                            entry=by_name[name];address,span,old=struct.unpack_from('<QQQ',data,offset+16)
                            new=address-entry['bias'];assert new>=0
                            assert any((p[2]&~4095)<=old<stubs.align(p[2]+p[5],4096)
                                and new==(p[3]&~4095)+old-(p[2]&~4095) for p in entry['loads']),(name,hex(old),hex(new))
                            if old!=new:
                                struct.pack_into('<Q',data,offset+32,new)
                                changes.append(dict(file_offset=offset+32,name=name,old_pgoff=old,new_pgoff=new,address=address,bytes=span))
                    records+=1;offset+=length
                assert offset==end;data.flush()
        assert changes
        # Exact file equality after reversing only recorded MMAP pgoff edits.
        with raw_copy.open('rb') as a,(out/'perf.data').open('rb') as bfile:
            offset=0
            while chunk:=a.read(2**20):
                original=bfile.read(len(chunk));edited=bytearray(chunk)
                for row in changes:
                    start=row['file_offset']-offset
                    if 0<=start and start+8<=len(edited):struct.pack_into('<Q',edited,start,row['old_pgoff'])
                    elif start<0<start+8 or start<len(edited)<start+8:raise AssertionError('MMAP edit crosses verification chunk; use smaller targeted verification')
                assert edited==original,offset;offset+=len(chunk)
            assert not bfile.read(1)
        b.save(out/'normalization_manifest.json',dict(mapped=mapped,changes=changes,records=records,
            original_perf_sha256=b.sha(out/'perf.data'),normalized_perf_sha256=b.sha(raw_copy),
            unchanged_except_recorded_mmap_offsets=True))
        for entry in mapped:
            link=out/'symfs'/entry['name'].lstrip('/');assert link.is_symlink();link.unlink();link.symlink_to(entry['view'])
        command=load(out/'decode_command.json');command[command.index('-i')+1]=str(raw_copy)
        b.save(out/'normalized_decode_command.json',command)
        with alternate.open('w') as output,(out/'normalized_decode.log').open('w') as err:
            subprocess.run(command,stdout=output,stderr=err,check=True)
        corrected_rows,corrected=quick(root,out,alternate)
        assert len(exact_rows)==len(corrected_rows)
        assert all(a['identity']==c['identity'] and a['frames'][0]['address']==c['frames'][0]['address'] for a,c in zip(exact_rows,corrected_rows))
        result=dict(valid=True,exact=exact,normalized=corrected,
            same_sample_identities_and_leaf_addresses=True,source_sha256=b.sha(source),
            interpretation='Compare identical raw samples; only offline ELF file layout and corresponding MMAP offsets changed. No measured program or hardware counter result changed.')
        b.save(out/'normalization_comparison.json',result)
        # Preserve the original decoder result and its hash before using the
        # verified offline mapping correction for compact stack extraction.
        b.save(out/'decode_ready_exact.json',load(out/'decode_ready.json'))
        remove_generated([out/'events.txt'],out/'exact_decoded_cleanup.json',
            'Exact-layout frame quality and event identity comparison retained; corrected decoding is the active extraction input.')
        alternate.rename(out/'events.txt')
        b.save(out/'decode_ready.json',dict(valid=True,raw_sha256=b.sha(out/'perf.data'),decoded_sha256=b.sha(out/'events.txt'),
            offline_mapping_correction='normalization_manifest.json',same_sample_identities_and_leaf_addresses=True))
        extract(dict(root=str(root),out=str(out)))
        print(json.dumps(result))
    except BaseException as error:
        b.save(out/'normalization_failure.json',dict(error=repr(error)));raise
    finally:
        paths=[p for p in [raw_copy,alternate,*views.glob('*')] if p.is_file() and p.suffix!='.json']
        if paths:remove_generated(paths,out/'normalization_cleanup.json','Offline normalization controls extracted or rejected; executable targets never modified.')
        if (out/'normalization_failure.json').exists():
            from rpc_predict_callchain import clean_symfs
            paths=[p for p in (out/'perf.data',out/'events.txt') if p.exists()]
            if paths:remove_generated(paths,out/'normalization_failure_cleanup.json','Rejected offline diagnosis; settings, failure and hashes retained.')
            clean_symfs(out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);probe(p.parse_args().root)
