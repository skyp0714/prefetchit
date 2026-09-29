#!/usr/bin/env python3
"""Test whether the observed IT0 positions follow a 32-byte end boundary."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import dense_build as b
from burst_hint_probe import assembly,Elf,NOP7
from dense_causes import ev,fe,counters
from e2e_lbr import remove_generated


def run(root):
    root.mkdir(exist_ok=False);b.space(root)
    assert not Path('/sys/module/prefetchit_sched_clock').exists()
    source=Path(__file__).with_name('burst_hint_probe.c')
    (root/'source.c').write_bytes(source.read_bytes());(root/'runner_used.py').write_bytes(Path(__file__).read_bytes())
    offsets=list(range(0,64,8));kinds=['nop','it0_8','end32_it0','mixed32'];artifacts=[];rows=[];audit={}
    events=','.join(['cycles:u','instructions:u',fe('FE_L2',0x13),ev('L2I',0x24,0x24),ev('SWPF_MISS',0x24,0x28),ev('ICACHE_DATA_STALL',0x80,4)])
    b.save(root/'protocol.json',dict(source_sha256=b.sha(source),runner_sha256=b.sha(__file__),
        assembly_generator_sha256=b.sha(Path(__file__).with_name('burst_hint_probe.py')),offsets=offsets,kinds=kinds,
        repeats=2,iterations=20000,handoff=1,dependent_demand=True,events=events,
        hypothesis='Earlier native data accelerated only targets 0 and 4 in an eight-IT0 contiguous burst. Those are the first IT0 instructions whose last bytes belong to successive 32-byte regions. Shift function placement by 0..56 bytes and compare all-eight, only predicted first-in-region, and those IT0 slots plus T1 in the others.',
        controls='Separate same-layout NOP for every offset. Identical main and target addresses across offsets; hint block address moves within existing alignment padding. Within an offset only audited hint-slot bytes change. All targets and repeated handoffs checked.',
        limitation='Observed positional rule is a processor-specific calibration hypothesis, not an architectural guarantee or queue occupancy measurement. Two repetitions, synthetic one-of-eight target choice, no service performance claim.'))
    try:
        target_identity=None
        for offset in offsets:
            predicted=[];seen=set()
            for j in range(8):
                region=(offset+3+j*7+6)//32
                if region not in seen:predicted.append(j);seen.add(region)
            baseline=None
            for kind in kinds:
                policy=[] if kind=='nop' else [(0,j,'it0' if kind=='it0_8' or j in predicted else 't1',j)
                    for j in range(8) if kind!='end32_it0' or j in predicted]
                stem=root/f'a{offset}_{kind}';asm=stem.with_suffix('.S');binary=stem
                asm.write_text(assembly(policy).replace('.global burst_hints',f'.space {offset},0x90\n.global burst_hints',1))
                artifacts.append(binary)
                b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fno-pie','-no-pie','-Wl,--build-id=none',source,asm,'-o',binary],Path(str(stem)+'_build.log'))
                syms={s[2]:int(s[0],16) for line in subprocess.check_output(['nm','-n',binary],text=True).splitlines() if len(s:=line.split())==3}
                assert syms['burst_hints']%4096==offset and syms['hint_0_0']==syms['burst_hints']+3
                target_syms={key:syms[key] for key in ['main',*[f'burst_target_{j}' for j in range(8)]]}
                if target_identity is None:target_identity=target_syms
                else:assert target_syms==target_identity
                data=binary.read_bytes();elf=Elf(data);section,_=elf.section('.text')
                normalized=bytearray(data[section[4]:section[4]+section[5]])
                for block in range(8):
                    for slot in range(8):
                        at=syms[f'hint_{block}_{slot}']-section[3];normalized[at:at+7]=NOP7
                if baseline is None:baseline=bytes(normalized)
                else:assert bytes(normalized)==baseline
                b.run(['objdump','-d','--insn-width=16','--start-address='+str(syms['burst_hints']),
                    '--stop-address='+str(syms['burst_hints']+64),binary],Path(str(stem)+'.asm'))
                audit[str(stem)]=dict(sha256=b.sha(binary),predicted_targets=predicted,
                    hint_addresses=[syms[f'hint_0_{j}'] for j in range(8)],target_symbols=target_syms)
        b.save(root/'binary_audit.json',audit)
        for repeat in range(2):
            for offset in offsets if not repeat else list(reversed(offsets)):
                for kind in kinds if not repeat else list(reversed(kinds)):
                    b.space(root);binary=root/f'a{offset}_{kind}';stem=root/f'r{repeat}_a{offset}_{kind}'
                    b.run(['perf','stat','--no-inherit','-x,','-o',str(stem)+'.csv','-e',events,'--',
                        'taskset','-c','84',binary,kind,'20000','1','1'],Path(str(stem)+'.log'))
                    result=json.loads(next(line for line in Path(str(stem)+'.log').read_text().splitlines() if line.startswith('{')))
                    count=counters(Path(str(stem)+'.csv'));assert count['fully_scheduled']
                    assert result['voluntary_switches']+result['involuntary_switches']>=.99*result['iterations']
                    assert sum(result['target_counts'])==result['iterations'] and min(result['target_counts'])>1000
                    rows.append(dict(offset=offset,repeat=repeat,**result,**count));b.save(root/'rows.json',rows)
        grouped=defaultdict(list)
        for row in rows:grouped[row['offset'],row['kind']].append(row)
        summary=[]
        for (offset,kind),values in grouped.items():
            summary.append(dict(offset=offset,kind=kind,predicted_targets=audit[str(root/f'a{offset}_{kind}')]['predicted_targets'],
                target_tsc=[statistics.mean(v['target_tsc'][j] for v in values) for j in range(8)],
                mean_calls_tsc=statistics.mean(v['mean_calls_tsc'] for v in values),mean_body_tsc=statistics.mean(v['mean_body_tsc'] for v in values),
                per_iteration={key:statistics.mean(v['counters'][key]/v['iterations'] for v in values) for key in values[0]['counters']}))
        b.save(root/'summary.json',dict(records=summary,scope='Synthetic positional calibration; not queue capacity or service speedup.'))
        b.save(root/'complete.json',dict(valid=True,trials=len(rows)))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        remove_generated([p for p in artifacts if p.exists()],root/'cleanup.json',
            'Alignment calibration completed or rejected. Retain source, slot disassembly, commands, return and switch checks, measurements and hashes; remove all generated executables.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();run(args.root)
