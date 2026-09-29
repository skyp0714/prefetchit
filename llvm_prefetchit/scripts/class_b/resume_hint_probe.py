#!/usr/bin/env python3
"""Separate a scheduler handoff from evicting the IT0 instruction itself."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import dense_build as b
from dense_causes import ev,fe,counters
from e2e_lbr import remove_generated
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
from call_stub_prefetch import Elf


def run(root):
    root.mkdir(exist_ok=False);b.space(root)
    assert not Path('/sys/module/prefetchit_sched_clock').exists(),'Do not overlap the service clock diagnostic'
    source=Path(__file__).with_suffix('.c');kinds=['nop','it0','t1'];artifacts=[];rows=[]
    events=','.join(['cycles:u','instructions:u',fe('FE_L2',0x13),ev('L2I',0x24,0x24),
        ev('SWPF_MISS',0x24,0x28),ev('ICACHE_DATA_STALL',0x80,4)])
    b.save(root/'protocol.json',dict(source_sha256=b.sha(source),runner_sha256=b.sha(__file__),
        events=events,repeats=3,iterations=20000,lead_imul=64,cpu=84,
        design='Both pipe endpoints inherit CPU84 affinity. The main task blocks and the helper replies; verify main-task switch counts. perf --no-inherit excludes helper execution. Same-address 7-byte NOP/IT0/T1 slots, target always flushed, hint line warm or flushed independently.',
        limitation='Artificial target flush and synchronous pipe handoff, not service performance or a direct fetch-queue/DSB occupancy measurement. User code between syscall return and hint is nonzero. Dependent IMUL count is not measured issue-to-fetch lead. No frequency/platform state is changed.'))
    (root/'source.c').write_text(source.read_text())
    try:
        texts=[];symbols=[]
        for index,kind in enumerate(kinds):
            binary=root/kind;artifacts.append(binary)
            b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fno-pie','-no-pie','-Wl,--build-id=none',
                '-DHINT='+str(index),source,'-o',binary],root/(kind+'_build.log'))
            b.run(['objdump','-d','--insn-width=16',binary],root/(kind+'.asm'))
            elf=Elf(binary.read_bytes());section,_=elf.section('.text')
            texts.append(binary.read_bytes()[section[4]:section[4]+section[5]])
            syms={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output(['nm','-n',binary],text=True).splitlines() if len(line.split())==3}
            symbols.append({k:syms[k] for k in ['resume_hint','resume_target']})
            offset=syms['resume_hint']-section[3]
        assert all(s==symbols[0] for s in symbols)
        for data in texts[1:]:
            assert len(data)==len(texts[0]) and data[:offset]==texts[0][:offset] and data[offset+7:]==texts[0][offset+7:]
        b.save(root/'binary_audit.json',dict(symbols=symbols[0],only_hint_slot_differs=True,
            binaries={kind:dict(sha256=b.sha(root/kind),bytes=(root/kind).stat().st_size) for kind in kinds}))
        settings=[(handoff,cold) for handoff in [0,1] for cold in [0,1]]
        for repeat in range(3):
            for handoff,cold in settings if repeat%2==0 else list(reversed(settings)):
                for kind in kinds if repeat%2==0 else list(reversed(kinds)):
                    b.space(root);stem=root/f'{repeat}_{kind}_s{handoff}_c{cold}'
                    b.run(['perf','stat','--no-inherit','-x,','-o',str(stem)+'.csv','-e',events,'--',
                        'taskset','-c','84',root/kind,kind,'20000',str(handoff),str(cold),'64'],Path(str(stem)+'.log'))
                    output=json.loads(next(line for line in Path(str(stem)+'.log').read_text().splitlines() if line.startswith('{')))
                    count=counters(Path(str(stem)+'.csv'));assert count['fully_scheduled']
                    if handoff:assert output['voluntary_switches']+output['involuntary_switches']>=.99*output['iterations']
                    rows.append(dict(repeat=repeat,**output,**count));b.save(root/'rows.json',rows)
        grouped=defaultdict(list)
        for row in rows:grouped[row['kind'],row['handoff'],row['cold_hint']].append(row)
        summary=[]
        for (kind,handoff,cold),records in grouped.items():
            summary.append(dict(kind=kind,handoff=handoff,cold_hint=cold,
                mean_call_tsc=statistics.mean(v['mean_call_tsc'] for v in records),
                counters_per_iteration={key:statistics.mean(v['counters'][key]/v['iterations'] for v in records) for key in records[0]['counters']},
                switch_range=[min(v['voluntary_switches']+v['involuntary_switches'] for v in records),max(v['voluntary_switches']+v['involuntary_switches'] for v in records)]))
        b.save(root/'summary.json',dict(records=summary,scope='Native mechanism probe; not application E2E speedup.'))
        b.save(root/'complete.json',dict(valid=True,trials=len(rows)))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        remove_generated([p for p in artifacts if p.exists()],root/'cleanup.json',
            'Resume-hint calibration complete or rejected. Preserve source, native checks, counts, commands, disassembly and hashes; no executable needed for the ongoing service measurements.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();run(a.root)
