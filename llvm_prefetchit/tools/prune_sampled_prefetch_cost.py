#!/usr/bin/env python3
"""Prune entry-plan sites using precise instruction samples on emitted T1s.

Instruction and miss profiles must use the same workload and operation count.
This estimates executions per selected baseline miss, not measured saved misses.
The input perf script must contain MMAP events and `-F ip,dso` samples.
"""
import argparse
import bisect
from collections import Counter
import json
from pathlib import Path
import re
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('binary', type=Path)
    ap.add_argument('samples', type=Path)
    ap.add_argument('plan', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--instruction-period', type=int, default=20003)
    ap.add_argument('--miss-period', type=int, default=1009)
    ap.add_argument('--max-ratio', type=float, default=10)
    a = ap.parse_args()
    plan = json.loads(a.plan.read_text())
    path = str(a.binary.resolve())
    loads = []
    for line in subprocess.check_output(['readelf','-lW',path],text=True).splitlines():
        f = line.split()
        if f and f[0] == 'LOAD':
            loads.append((int(f[1],16),int(f[4],16),int(f[2],16)))
    symbols = {}
    for line in subprocess.check_output(['nm','--defined-only',path],text=True).splitlines():
        f = line.split()
        if len(f) == 3 and f[1] in 'TtWw':
            addr = int(f[0],16)
            if addr not in symbols or f[2] in plan['sites']: symbols[addr] = f[2]
    addresses = sorted(symbols)
    pf = set()
    dis = subprocess.check_output(['objdump','-d','--no-show-raw-insn',path],text=True)
    for line in dis.splitlines():
        m = re.match(r'^\s*([0-9a-f]+):\s+prefetcht1\s',line)
        if m: pf.add(int(m[1],16))
    maps = []; counts = Counter(); total = mapped = on_pf = 0
    for line in a.samples.open():
        m = re.search(r'PERF_RECORD_MMAP2 .*?\[(0x[0-9a-f]+)\((0x[0-9a-f]+)\) @ (0x[0-9a-f]+).*?\]: (\S+) (.*)',line)
        if m:
            if m[5].strip() == path and 'x' in m[4]:
                maps.append(tuple(int(m[i],16) for i in (1,2,3)))
            continue
        m = re.match(r'^\s*([0-9a-f]+) \(([^)]+)\)\s*$',line)
        if not m: continue
        total += 1
        if m[2] != path: continue
        ip = int(m[1],16); va = None
        for lo,size,off in reversed(maps):
            if lo <= ip < lo+size:
                file_offset = ip-lo+off
                for foff,fsize,vaddr in loads:
                    if foff <= file_offset < foff+fsize:
                        va = file_offset-foff+vaddr; break
                break
        if va is None: raise RuntimeError(f'unmapped executable IP {ip:#x}')
        mapped += 1
        if va in pf:
            on_pf += 1
            i = bisect.bisect_right(addresses,va)-1
            if i >= 0: counts[symbols[addresses[i]]] += 1
    if not on_pf: raise RuntimeError('no samples on prefetch instructions; check event and mappings')
    decisions = []
    for site, entry in plan['sites'].items():
        weight = sum(t[3] for t in entry['t'])
        # Three samples is a conservative floor for unobserved/low-count sites.
        ratio = max(3,counts[site])*a.instruction_period/(weight*a.miss_period)
        decisions.append({'site':site,'samples':counts[site],'weight':weight,
                          'estimated_cost_ratio':ratio,'keep':ratio <= a.max_ratio})
    kept = {d['site'] for d in decisions if d['keep']}
    plan['sites'] = {k:v for k,v in plan['sites'].items() if k in kept}
    if not kept: raise RuntimeError('cost filter retained no sites')
    a.output.write_text(json.dumps(plan,indent=2))
    audit = {'total_samples':total,'mapped_samples':mapped,'samples_on_t1':on_pf,
             'sites_before':len(decisions),'sites_after':len(kept),
             'instruction_period':a.instruction_period,'miss_period':a.miss_period,
             'max_ratio':a.max_ratio,'decisions':decisions,
             'top_prefetch_sites':counts.most_common(20)}
    a.output.with_suffix('.cost.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps({k:v for k,v in audit.items() if k not in ('decisions','top_prefetch_sites')}))


if __name__ == '__main__': main()
