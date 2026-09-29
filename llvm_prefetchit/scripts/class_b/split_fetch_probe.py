#!/usr/bin/env python3
"""Calibrate sampled IP versus the missing half of a split instruction."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
import dense_build as b
from dense_causes import ev,fe,counters
from e2e_lbr import remove_generated
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))


def run(root):
    root.mkdir(exist_ok=False);b.space(root)
    source=Path(__file__).with_suffix('.c');kinds=['nop','first','second','both']
    events=','.join(['cycles:u','instructions:u',fe('FE_L2',0x13),
        ev('L2I',0x24,0x24),ev('SWPF_MISS',0x24,0x28),ev('ICACHE_DATA_STALL',0x80,4)])
    b.save(root/'protocol.json',dict(source=str(source),source_sha256=b.sha(source),
        runner_sha256=b.sha(__file__),events=events,repeats=3,iterations=100000,lead_imul=64,
        design='Same-address NOP, first-line T1, continuation-line T1 and both. Flush only continuation line; MOVABS starts at byte 61 and spans both lines. Native return value checked every iteration.',
        limitation='Artificial CLFLUSH calibration, not service speedup. The continuation target is an arbitrary valid byte for data T1, not an instruction start suitable for IT0. A successful probe motivates service validation; it does not identify every real sample\'s missing line.'))
    (root/'source.c').write_text(source.read_text());binaries=[];rows=[];sample_rows=[]
    try:
        texts=[];symbols=[]
        for index,kind in enumerate(kinds):
            binary=root/kind;binaries.append(binary)
            b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fno-pie','-no-pie','-Wl,--build-id=none',
                '-DHINT='+str(index),source,'-o',binary],root/(kind+'_build.log'))
            b.run(['objdump','-d','--insn-width=16',binary],root/(kind+'.asm'))
            syms={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output(['nm','-n',binary],text=True).splitlines() if len(line.split())==3 and line.split()[0].isalnum()}
            symbols.append({k:syms[k] for k in ['split_target','split_next','split_hints','split_line']})
            assert syms['split_target']%64==61 and syms['split_next']==syms['split_target']+3
            raw=root/(kind+'.text');binaries.append(raw)
            b.run(['objcopy','--dump-section','.text='+str(raw),binary],root/(kind+'_text.log'));texts.append(raw.read_bytes())
        assert all(s==symbols[0] for s in symbols)
        # Same compiled main and targets: only the two hint slots may differ.
        from call_stub_prefetch import Elf
        elf=Elf((root/'nop').read_bytes());section,_=elf.section('.text')
        offset=symbols[0]['split_hints']-section[3]
        for data in texts[1:]:
            assert len(data)==len(texts[0])
            assert data[:offset]==texts[0][:offset] and data[offset+14:]==texts[0][offset+14:]
        b.save(root/'binary_audit.json',dict(symbols=symbols[0],only_hint_slots_differ=True,
            binaries={k:dict(sha256=b.sha(root/k),bytes=(root/k).stat().st_size) for k in kinds}))
        for repeat in range(3):
            for kind in kinds if repeat%2==0 else list(reversed(kinds)):
                b.space(root);stem=root/f'{repeat}_{kind}'
                command=['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'--',
                    'taskset','-c','84',root/kind,kind,'100000','64']
                b.run(command,Path(str(stem)+'.log'))
                output=json.loads(next(line for line in Path(str(stem)+'.log').read_text().splitlines() if line.startswith('{')))
                count=counters(Path(str(stem)+'.csv'));assert count['fully_scheduled']
                row=dict(repeat=repeat,**output,**count)
                rows.append(row);b.save(root/'rows.json',rows)
        for kind in kinds:
            stem=root/('sample_'+kind);raw=Path(str(stem)+'.data');binaries.append(raw)
            event='cpu/event=0xc6,umask=3,config1=0x13,name=FE_L2,period=257/upp'
            b.run(['perf','record','--no-buildid','--no-buildid-cache','-m','8M','-e',event,'-o',raw,'--',
                'taskset','-c','84',root/kind,kind,'250000','64'],Path(str(stem)+'.log'))
            decoded=Path(str(stem)+'.txt');binaries.append(decoded)
            b.run(['perf','script','-i',raw,'-F','ip,dso','--show-lost-events'],decoded)
            types=Counter()
            proc=subprocess.Popen(['perf','script','-D','-i',str(raw)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            for line in proc.stdout:
                match=re.search(r'PERF_RECORD_(\w+)',line)
                if match:types[match[1]]+=1
            assert proc.wait()==0 and not any(types[k] for k in ['LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'])
            ips=Counter();other=0
            for line in decoded.read_text().splitlines():
                match=re.match(r'^\s*([0-9a-f]+)\s+\((.*?)\)\s*$',line)
                if not match:continue
                if Path(match[2]).name==kind:ips[int(match[1],16)]+=1
                else:other+=1
            sample_rows.append(dict(kind=kind,record_types=dict(types),main_ip_counts=dict(ips),other_dso_samples=other,
                split_start_samples=ips[symbols[0]['split_target']],continuation_ret_samples=ips[symbols[0]['split_next']+7],
                raw_sha256=b.sha(raw),decoded_sha256=b.sha(decoded)))
            b.save(root/'samples.json',sample_rows)
        b.save(root/'complete.json',dict(valid=True,stat_trials=len(rows),sampling_trials=len(sample_rows)))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        remove_generated([p for p in binaries if p.exists()],root/'cleanup.json',
            'Completed or rejected split-fetch calibration: keep source, commands, disassembly, binary hashes, compact counts and PEBS IP histogram; remove generated executable/text/trace copies.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root)
