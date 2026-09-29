#!/usr/bin/env python3
"""Calibrate bounded IT0 bursts against spaced and mixed hint emission."""
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
from call_stub_prefetch import Elf,NOP7

POLICIES={'nop':[],**{f'it0_{n}':[(0,j,'it0',j) for j in range(n)] for n in [1,2,4,8]},
    't1_8':[(0,j,'t1',j) for j in range(8)],
    'it0_spaced8':[(j,0,'it0',j) for j in range(8)],
    'mixed_1it0_7t1':[(0,j,'it0' if j==0 else 't1',j) for j in range(8)]}


def assembly(policy):
    hints={(block,slot):(kind,target) for block,slot,kind,target in policy}
    lines=['.text','.p2align 12','.global burst_hints','burst_hints:','mov %rdi,%rax']
    for block in range(8):
        for slot in range(8):
            lines += [f'.global hint_{block}_{slot}',f'hint_{block}_{slot}:']
            if (block,slot) in hints:
                kind,target=hints[block,slot];lines += [f'prefetch{kind} burst_target_{target}(%rip)']
            else:lines += ['.byte 0x0f,0x1f,0x80,0,0,0,0']
        lines += ['.rept 64','imul $3,%rax,%rax','.endr']
    lines += ['ret']
    for target in range(8):
        lines += ['.p2align 12','.space 4096,0x90',f'.global burst_target_{target}',
                  f'burst_target_{target}:',f'mov ${target},%eax','ret','.space 4090,0x90']
    lines += ['.section .note.GNU-stack,"",@progbits']
    return '\n'.join(lines)+'\n'


def run(root,dependent=False):
    root.mkdir(exist_ok=False);b.space(root)
    assert not Path('/sys/module/prefetchit_sched_clock').exists()
    source=Path(__file__).with_suffix('.c');(root/'source.c').write_bytes(source.read_bytes())
    events=','.join(['cycles:u','instructions:u',fe('FE_L2',0x13),ev('L2I',0x24,0x24),
        ev('SWPF_MISS',0x24,0x28),ev('ICACHE_DATA_STALL',0x80,4)])
    b.save(root/'protocol.json',dict(source_sha256=b.sha(source),runner_sha256=b.sha(__file__),
        events=events,policies=POLICIES,repeats=3,iterations=20000,cpu=84,dependent_demand=dependent,
        demand='One of eight targets selected from the returned dependent-IMUL result on a varying xorshift input.' if dependent else 'All eight targets, fixed order.',
        design='Eight targets, each cache-line flushed. Actual same-CPU blocking handoff versus no handoff. Eight 7-byte hint slots per block, eight blocks, identical 64 dependent IMUL instructions per block. Vary only hint bytes. Compare first-block bursts of 1/2/4/8 against one hint per block, T1 and one IT0 plus seven T1. Verify every target return on every iteration; exclude helper with perf --no-inherit.',
        limitation='Artificial cold targets; not service E2E. Timing includes serial stamps. IMUL counts and hint spacing are not measured fetch lead. No direct queue or DSB observation; do not infer hardware queue capacity from saturation. The hint code is not explicitly flushed, but kernel execution can change its residency.'))
    (root/'runner_used.py').write_bytes(Path(__file__).read_bytes())
    artifacts=[];rows=[];audit={};reference=None
    try:
        for kind,policy in POLICIES.items():
            asm=root/(kind+'.S');asm.write_text(assembly(policy));binary=root/kind;artifacts.append(binary)
            b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fno-pie','-no-pie','-Wl,--build-id=none',source,asm,'-o',binary],root/(kind+'_build.log'))
            b.run(['objdump','-d','--insn-width=16',binary],root/(kind+'.asm'))
            syms={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output(['nm','-n',binary],text=True).splitlines() if len(line.split())==3}
            data=binary.read_bytes();elf=Elf(data);section,_=elf.section('.text')
            text=bytearray(data[section[4]:section[4]+section[5]])
            for block in range(8):
                for slot in range(8):
                    offset=syms[f'hint_{block}_{slot}']-section[3];text[offset:offset+7]=NOP7
            identity={key:value for key,value in syms.items() if key.startswith(('hint_','burst_'))}
            if reference is None:reference=(bytes(text),identity)
            else:assert bytes(text)==reference[0] and identity==reference[1]
            audit[kind]=dict(sha256=b.sha(binary),bytes=binary.stat().st_size,symbols=identity)
        b.save(root/'binary_audit.json',dict(only_hint_slots_differ=True,binaries=audit))
        kinds=list(POLICIES)
        for repeat in range(3):
            for handoff in [0,1] if repeat%2==0 else [1,0]:
                for kind in kinds if repeat%2==0 else list(reversed(kinds)):
                    b.space(root);stem=root/f'{repeat}_{kind}_s{handoff}'
                    b.run(['perf','stat','--no-inherit','-x,','-o',str(stem)+'.csv','-e',events,'--',
                        'taskset','-c','84',root/kind,kind,'20000',str(handoff),str(int(dependent))],Path(str(stem)+'.log'))
                    result=json.loads(next(line for line in Path(str(stem)+'.log').read_text().splitlines() if line.startswith('{')))
                    count=counters(Path(str(stem)+'.csv'));assert count['fully_scheduled']
                    if handoff:assert result['voluntary_switches']+result['involuntary_switches']>=.99*result['iterations']
                    assert sum(result['target_counts'])==result['iterations']*(1 if dependent else 8)
                    assert all(n>1000 for n in result['target_counts'])
                    rows.append(dict(repeat=repeat,**result,**count));b.save(root/'rows.json',rows)
        grouped=defaultdict(list)
        for row in rows:grouped[row['kind'],row['handoff']].append(row)
        summary=[]
        for (kind,handoff),records in grouped.items():
            summary.append(dict(kind=kind,handoff=handoff,
                mean_calls_tsc=statistics.mean(r['mean_calls_tsc'] for r in records),
                mean_body_tsc=statistics.mean(r['mean_body_tsc'] for r in records),
                target_tsc=[statistics.mean(r['target_tsc'][i] for r in records) for i in range(8)],
                per_iteration={key:statistics.mean(r['counters'][key]/r['iterations'] for r in records) for key in records[0]['counters']}))
        b.save(root/'summary.json',dict(records=summary,scope='Mechanism calibration only; no service speedup claim.'))
        b.save(root/'complete.json',dict(valid=True,trials=len(rows)))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        remove_generated([p for p in artifacts if p.exists()],root/'cleanup.json',
            'Completed or rejected burst calibration. Preserve source, exact generated assembly, disassembly, commands, binary audits and measurements; remove unused generated executables.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--dependent-demand',action='store_true')
    args=parser.parse_args();run(args.root,args.dependent_demand)
