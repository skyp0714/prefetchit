#!/usr/bin/env python3
"""Gather every screen CSV of the realistic campaign into one table: workload / config at its realistic operating point (highest
utilization step that is still clean), user-mode L2I MPKI, IPC; flag MPKI >= 1 as candidates."""
import csv,glob,os,collections
R=os.path.dirname(os.path.abspath(__file__)); rows=[]
def add(w,cfg,util,mpki,ipc,note=''): rows.append((w,cfg,util,mpki,ipc,note))
# databases: per (workload,config) pick the highest-util step with lat sane (tps within 90% of max)
f=f'{R}/db_4core.csv'
if os.path.exists(f):
    g=collections.defaultdict(list)
    for r in csv.DictReader(open(f)): g[(r['workload'],r['config'])].append(r)
    for k,v in g.items():
        mx=max(float(r['tps']) for r in v); ok=[r for r in v if float(r['tps'])>=0.9*mx]; r=max(ok,key=lambda r:float(r['util_pct']))
        add(k[0],f"{k[1]}, {r['clients']} clients, 4 cores",float(r['util_pct']),float(r['mpki']),float(r['ipc']),f"tps {r['tps']}")
        lo=min(v,key=lambda r:float(r['util_pct'])); add(k[0],f"{k[1]}, {lo['clients']} clients (under-utilized)",float(lo['util_pct']),float(lo['mpki']),float(lo['ipc']),'low-util reference')
# musuite: per app/tier, highest-util step with p99 < 3 ms and instr > 1e8
f=f'{R}/musuite_4core.csv'
if os.path.exists(f):
    g=collections.defaultdict(list)
    for r in csv.DictReader(open(f)):
        if float(r['instr'])>1e8 and float(r['p99us'])<3000: g[(r['app'],r['tier'])].append(r)
    for k,v in g.items():
        r=max(v,key=lambda r:float(r['util_pct'])); add(f"μSuite {k[0]} {k[1]}",f"{r['qps']} qps, 4 cores",float(r['util_pct']),float(r['mpki']),float(r['ipc']))
# jvm
for f,cores in ((f'{R}/jvm_4core.csv','4'),(f'{R}/jvm_4core_rerun.csv','4'),(f'{R}/jvm_8core.csv','8')):
    if os.path.exists(f):
        for r in csv.DictReader(open(f)):
            if r['note']=='ok' and float(r['instr'])>0: add(f"{r['suite']}/{r['bench']}",f"{cores} cores, heap {r['heap']}",100.0,float(r['mpki']),float(r['ipc']))
# stacks
for f in glob.glob(f'{R}/dsb_*.csv'):
    for r in csv.DictReader(open(f)):
        if float(r['instr'])>1e9: add(f"{r['stack']}/{r['container']}",f"{r['ncores']} cores, {r['rate']} req/s",float(r['util_pct']),float(r['mpki']),float(r['ipc']))
# cloudsuite: per bench highest-util step
f=f'{R}/cloudsuite_4core.csv'
if os.path.exists(f):
    g=collections.defaultdict(list)
    for r in csv.DictReader(open(f)): g[r['bench']].append(r)
    for k,v in g.items():
        r=max(v,key=lambda r:float(r['util_pct'])); add(f"CloudSuite {k}",f"{r['load']}, 4 cores",float(r['util_pct']),float(r['mpki']),float(r['ipc']),r['note'])
# dcperf
f=f'{R}/dcperf_default.csv'
if os.path.exists(f):
    for r in csv.DictReader(open(f)): add(f"DCPerf {r['job']}",f"{r['scope']} @{r['delay_s']}s (default job, whole machine)",100.0,float(r['mpki']),float(r['ipc']),r['note'])
rows.sort(key=lambda x:-x[3])
print("| workload | realistic config | util | L2I MPKI (user) | IPC | note |"); print("|---|---|---:|---:|---:|---|")
for w,cfg,u,m,i,n in rows:
    if 'under-utilized' in cfg: continue
    print(f"| {w} | {cfg} | {u:.0f}% | {'**%.2f**'%m if m>=1 else '%.2f'%m} | {i:.2f} | {n} |")
print("\nCandidates (MPKI >= 1 at the realistic point):", ', '.join(f"{w} ({m:.1f})" for w,cfg,u,m,i,n in rows if m>=1 and 'under-utilized' not in cfg))
