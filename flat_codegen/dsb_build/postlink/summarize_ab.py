#!/usr/bin/env python3
import csv,statistics as st,sys,collections
rows=list(csv.DictReader(open(sys.argv[1])))
by=collections.defaultdict(list)
for r in rows: by[r['arm']].append(r)
def med(a,k): return st.median(float(r[k]) for r in a)
base=by.get('base')
print("| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |")
print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for arm,a in by.items():
    i=med(a,'instructions'); c=med(a,'cycles'); m=med(a,'l2i_miss')
    bc=med(base,'cycles') if base else c; bi=med(base,'instructions') if base else i
    print(f"| {arm} | {len(a)} | {med(a,'rps'):.0f} | {med(a,'non2xx'):.0f} | {med(a,'p50_ms'):.1f} | {med(a,'p99_ms'):.1f} | {c/1e9:.2f} | {bc/c:.4f}x | {1000*m/i:.2f} | {i/c:.3f} | {i/bi:.3f} |")
