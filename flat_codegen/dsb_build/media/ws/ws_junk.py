#!/usr/bin/env python3
"""From the PT trace: per run, (a) distinct lines actually executed, (b) 'shadow' lines the front end fetches but the program does not
execute: the line(s) sequentially after each taken branch (fall-through fetched by next-line/FDIP before the redirect) and the fall-through
line after a taken conditional branch, when that line is not executed in the same run. Reports per-request totals against the counted misses."""
import sys, os, collections, statistics
sys.path.insert(0, '.'); import run_paths as rp
maps = rp.Maps('pt6/maps.txt', os.path.abspath('symfs_wsm'))
br, sw, sc, n = rp.parse('pt6')
LINE = 64
tot_exec = tot_sh1 = tot_sh2 = 0; nruns = 0; per = []
for tid in sw:
    for t_in, t_out, hook, recs, first in rp.runs_of(tid, br.get(tid, []), sw[tid], sc.get(tid, [])):
        if not recs: continue
        lines = rp.touched_lines(recs, maps); ex = set((d.name, va) for _, d, va in lines)
        sh1 = set(); sh2 = set()
        for t, ip, addr, fl in recs:
            if not ip or not addr: continue
            if 'jcc' not in fl and 'jmp' not in fl and 'call' not in fl and 'return' not in fl: continue
            if (ip & ~(LINE - 1)) == (addr & ~(LINE - 1)): continue           # short branch inside the line
            for k, s in ((1, sh1), (2, sh2)):
                a = (ip & ~(LINE - 1)) + k * LINE
                r = maps.resolve(a)
                if r:
                    key = (r[0].name, r[1] & ~(LINE - 1))
                    if key not in ex: s.add(key)
        sh2 -= sh1
        tot_exec += len(ex); tot_sh1 += len(sh1); tot_sh2 += len(sh2); nruns += 1; per.append((len(ex), len(sh1), len(sh2)))
reqs = 60  # ~0.1 s at 600 rps
print(f"runs {nruns}; per request (~{reqs} requests): executed lines {tot_exec/reqs:.0f}, shadow lines +1 after taken branches {tot_sh1/reqs:.0f}, +2 {tot_sh2/reqs:.0f}")
print(f"median per run: executed {statistics.median(p[0] for p in per):.0f}, shadow+1 {statistics.median(p[1] for p in per):.0f}, shadow+2 {statistics.median(p[2] for p in per):.0f}")
