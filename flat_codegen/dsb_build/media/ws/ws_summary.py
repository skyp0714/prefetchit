#!/usr/bin/env python3
import csv, sys, statistics as st, collections
rows = list(csv.DictReader(open(sys.argv[1]))); by = collections.defaultdict(list)
for r in rows:
    if float(r['instr']) > 1e9 and float(r['cycles']) > 1e9: by[r['arm']].append(r)   # drop rows from truncated perf files
base = next(iter(by)); 
def med(a, f): return st.median(f(r) for r in a)
cyc_req = lambda r: float(r['cycles']) / max(1.0, float(r['rps']) * 30)
print(f"{'arm':10s} {'n':>2s} {'rps':>5s} {'cyc/req':>9s} {'vs_base':>8s} {'MPKI':>6s} {'IPC':>6s} {'instr':>7s} {'fill%':>6s} {'p99ms':>7s}")
b = med(by[base], cyc_req); bi = med(by[base], lambda r: float(r['instr']))
for arm, a in by.items():
    mp = med(a, lambda r: 1000 * float(r['l2i']) / float(r['instr'])); ipc = med(a, lambda r: float(r['instr']) / float(r['cycles']))
    fill = med(a, lambda r: 100 * float(r['swpf_miss']) / max(1, float(r['swpf_miss']) + float(r['swpf_hit'])))
    print(f"{arm:10s} {len(a):2d} {med(a, lambda r: float(r['rps'])):5.0f} {med(a, cyc_req)/1e3:8.1f}k {b/med(a, cyc_req):7.3f}x {mp:6.2f} {ipc:6.3f} {med(a, lambda r: float(r['instr']))/bi:6.3f}x {fill:5.0f}% {med(a, lambda r: float(r['p99_ms'])):7.1f}")
