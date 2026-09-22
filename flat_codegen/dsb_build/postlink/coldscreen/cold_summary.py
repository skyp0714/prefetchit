#!/usr/bin/env python3
import csv,sys,collections
rows=collections.defaultdict(dict)
for r in csv.DictReader(open(sys.argv[1])): rows[r['container']][r['mode']]=r
print("| container | cs/s | instr/s (G) | MPKI shared | MPKI isolated | ΔMPKI | IPC sh→iso | cycles sh/iso | I-side headroom ≈0.7%×ΔMPKI |")
print("|---|---:|---:|---:|---:|---:|---|---:|---:|")
out=[]
for c,m in rows.items():
    if 'shared' not in m or 'isolated' not in m: continue
    s,i=m['shared'],m['isolated']; fs=lambda r,k: float(r[k]); win=30
    if fs(s,'instr')<1e8: continue
    ms=1000*fs(s,'l2i')/fs(s,'instr'); mi=1000*fs(i,'l2i')/fs(i,'instr')
    out.append((ms-mi,c,fs(s,'cs')/win,fs(s,'instr')/win/1e9,ms,mi,fs(s,'instr')/fs(s,'cycles'),fs(i,'instr')/fs(i,'cycles'),fs(s,'cycles')/fs(i,'cycles')))
for d,c,cs,ips,ms,mi,ipcs,ipci,cyc in sorted(out,reverse=True):
    print(f"| {c} | {cs:.0f} | {ips:.2f} | {ms:.1f} | {mi:.1f} | {d:.1f} | {ipcs:.2f}→{ipci:.2f} | {cyc:.2f}x | {0.7*d:.1f}% |")
