#!/usr/bin/env python3
"""Summarize a media A/B csv: per arm median rps / MPKI / IPC / cycles-per-request, ratios vs the first arm."""
import sys,csv,statistics as st,collections
rows=[r for r in csv.DictReader(open(sys.argv[1])) if float(r['instr'] or 0)>0]; arms=collections.OrderedDict()
for r in rows: arms.setdefault(r['arm'],[]).append(r)
def med(a,k): return st.median(float(r[k]) for r in a)
base=next(iter(arms)); b=arms[base]; brps=med(b,'rps'); bcpr=med(b,'cycles')/max(1,med(b,'rps')); binstr=med(b,'instr')
print(f"{'arm':10s} {'n':>2s} {'rps':>7s} {'vs_base':>8s} {'cyc/req':>8s} {'vs_base':>8s} {'MPKI':>6s} {'IPC':>6s} {'instr':>8s} {'p99ms':>6s}")
for a,rs in arms.items():
    i=med(rs,'instr'); c=med(rs,'cycles'); l=med(rs,'l2i'); rps=med(rs,'rps'); cpr=c/max(1,rps)
    print(f"{a:10s} {len(rs):2d} {rps:7.0f} {rps/brps:8.3f}x {cpr/1e3:8.1f}k {bcpr/cpr:8.3f}x {1000*l/i:6.2f} {i/c:6.3f} {i/binstr:8.3f}x {med(rs,'p99_ms'):6.1f}")
