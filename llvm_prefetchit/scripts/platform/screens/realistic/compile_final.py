#!/usr/bin/env python3
"""Final table: workload, realistic (high-MPKI, pinned) point, MPKI, IPC, and the dominant miss cause from the diagnostics:
 cold  = disappears with deep C-states off (idle-wake L2 flush);  capacity = survives C6-off and one-core;  multi-thread = survives on
 one core only / drops when threads no longer share a core;  mixed / n.d. otherwise."""
import csv,os,glob,collections,re
R=os.path.dirname(os.path.abspath(__file__))
def rd(f): return list(csv.DictReader(open(f))) if os.path.exists(f) else []
def classify(d,noc6,one_noc6,one_def):
    if d is None: return 'n.d.'
    if noc6 is not None and noc6<=0.35*d: 
        return 'cold (C6 wake)' if (one_noc6 is None or one_noc6<=0.5*d) else 'cold + multi-thread'
    if noc6 is not None and noc6>=0.6*d:
        if one_noc6 is not None and one_noc6>=0.6*d: return 'capacity'
        if one_noc6 is not None and one_noc6<0.6*d: return 'multi-thread (spread)'
        return 'capacity?'
    if noc6 is not None: return 'mixed (cold+capacity)'
    return 'n.d.'
rows=[]
# diagnostics keyed by workload
diag=collections.defaultdict(dict)
for r in rd(f'{R}/cause_diag.csv'): diag[r['workload']][r['config']]=(float(r['mpki']),float(r['ipc']),float(r['util_pct']))
# PG: from db_lowutil (c4_default, c4_noC6, c4_backend_pinned)
pg={r['config']:(float(r['mpki']),float(r['ipc']),float(r['util_pct'])) for r in rd(f'{R}/db_lowutil.csv') if r['workload']=='postgresql_diag'}
if pg:
    d=pg.get('c4_default'); n=pg.get('c4_noC6'); p=pg.get('c4_backend_pinned')
    rows.append(('PostgreSQL 16 TPC-B','4 backends on 4 cores, 28% util',d[0],d[1],f"cold (C6 wake): C6 off → {n[0]:.2f}; backends pinned → {p[0]:.1f}" if n and p else 'cold (C6 wake)'))
# MariaDB
md=[r for r in rd(f'{R}/db_lowutil.csv') if r['workload']=='mariadb_oltp_read_write_diag' and r['config']=='durable_t4']
if md:
    d=float(md[0]['mpki']); g=diag.get('mariadb_oltp_read_write',{}); n=g.get('noC6'); o=g.get('noC6_1core'); od=g.get('default_1core')
    rows.append(('MariaDB 10.11 oltp_read_write (durable)','4 threads on 4 cores, 40% util',d,float(md[0]['ipc']),classify(d,n and n[0],o and o[0],od and od[0])+(f" (C6 off {n[0]:.2f}, 1 core {o[0]:.2f})" if n and o else (f" (C6 off {n[0]:.2f})" if n else ''))))
ro=[r for r in rd(f'{R}/db_lowutil.csv') if r['workload']=='mariadb_oltp_read_only_diag' and r['config']=='durable_t4']
if ro: rows.append(('MariaDB oltp_read_only (durable)','4 threads on 4 cores, 42% util',float(ro[0]['mpki']),float(ro[0]['ipc']),'same mechanism as read-write (not separately diagnosed)'))
# Router
for tier in ('leaf','midtier'):
    base=[r for r in rd(f'{R}/musuite_4core.csv') if r['app']=='Router' and r['tier']==tier and r['qps']=='1000' and float(r['instr'])>1e8]
    if base:
        d=float(base[-1]['mpki']); g=diag.get(f'μSuite Router {tier}',{}); n=g.get('noC6'); o=g.get('noC6_1core'); od=g.get('default_1core')
        rows.append((f'μSuite Router {tier}','1k qps, 4 cores, 3–8% util',d,float(base[-1]['ipc']),classify(d,n and n[0],o and o[0],od and od[0])+(f" (C6 off {n[0]:.1f}, 1 core {o[0]:.1f})" if n and o else '')))
# JVM
jv={ (r['suite'],r['bench']):r for r in rd(f'{R}/jvm_4core.csv')+rd(f'{R}/jvm_4core_rerun.csv') if r['note']=='ok'}
j8={ (r['suite'],r['bench']):r for r in rd(f'{R}/jvm_8core.csv') if r['note']=='ok'}
for k,r in sorted(jv.items(), key=lambda kv:-float(kv[1]['mpki'])):
    d=float(r['mpki'])
    if d<1: continue
    w=f"{k[0]}/{k[1]}"; g=diag.get(w,{}); n=g.get('noC6'); o=g.get('noC6_1core'); od=g.get('default_1core')
    e=j8.get(k); extra=f"; 8 cores {float(e['mpki']):.1f}" if e else ''
    rows.append((w,'4 pinned cores, JDK 21, 8 GB heap',d,float(r['ipc']),classify(d,n and n[0],o and o[0],od and od[0])+(f" (C6 off {n[0]:.1f}, 1 core {o[0]:.1f}{extra})" if n and o else extra)))
# stacks: default vs noC6 per container (instr > 1e9)
for stack,f,fn in (('socialnetwork','dsb_social_pool43.csv','dsb_social_noC6.csv'),('hotelreservation','dsb_hotel.csv','dsb_hotel_noC6.csv'),('mediamicroservices','dsb_media.csv','dsb_media_noC6.csv')):
    base={r['container']:r for r in rd(f'{R}/{f}') if float(r['instr'])>1e9}
    if not base: continue
    noc={r['container']:r for r in rd(f'{R}/{fn}') if float(r['instr'])>1e9} if fn else {}
    for c,r in sorted(base.items(), key=lambda kv:-float(kv[1]['mpki'])):
        d=float(r['mpki'])
        if d<1: continue
        n=noc.get(c); nm=float(n['mpki']) if n else None
        cause=classify(d,nm,None,None) if n else 'n.d.'
        if n and nm<=0.35*d: cause='cold (C6 wake)'
        elif n and nm>=0.6*d: cause='capacity / interleaving (survives C6 off)'
        rows.append((f"{stack}/{c}",f"{r['ncores']} core(s), {r['rate']} req/s, {float(r['util_pct']):.0f}% util",d,float(r['ipc']),cause+(f" (C6 off {nm:.1f})" if n else '')))
# cloudsuite: highest-MPKI step with util >= 2%
g=collections.defaultdict(list)
for r in rd(f'{R}/cloudsuite_4core.csv'):
    if re.match(r'^workers=\d+$',r['note']) or r['note'].startswith('salvaged'): continue   # first-attempt web-search rows, duplicate salvage row
    if float(r['instr'])>1e9: g[r['bench']].append(r)
for b,v in g.items():
    if b.endswith('-noC6'): continue
    cand=[x for x in v if float(x['util_pct'])>=15] or v; r=max(cand,key=lambda x:float(x['mpki'])); d=float(r['mpki'])
    n=[x for x in g.get(b+'-noC6',[]) if float(x['instr'])>1e9]; cause='n.d. (no C6 pass)'
    if n:
        m=float(n[0]['mpki']); ref=[x for x in v if x['load']==n[0]['load']]; dref=float(ref[0]['mpki']) if ref else d
        cause=('cold (C6 wake)' if m<=0.35*dref else 'capacity' if m>=0.7*dref else 'mixed (cold %d%% / capacity %d%%)'%(round(100*(1-m/dref)),round(100*m/dref)))+f" (at {n[0]['load']}: {dref:.2f} → {m:.2f})"
        if n[0]['load']!=r['load'] and dref<1: cause=f"n.d. at this point; at {n[0]['load']} the misses are gone anyway ({dref:.2f} → {m:.2f}) — low-load cold-wake regime"
    rows.append((f"CloudSuite {b}",f"{r['load']}, 4 cores, {float(r['util_pct']):.0f}% util",d,float(r['ipc']),cause))
# dcperf
for r in []:   # DCPerf v1 default-job rows dropped: superseded by the v2 screen (see dcperf_v2.csv)
    if r['scope']=='process' or (r['scope']=='system' and float(r['mpki'])>=1): rows.append((f"DCPerf {r['job']}",f"default job, whole machine ({r['scope']} @{r['delay_s']}s)",float(r['mpki']),float(r['ipc']),'n.d. (whole-machine default job)'))
rows.sort(key=lambda x:-x[2])
lines=["| workload | realistic point (pinned) | L2I MPKI (user) | IPC | dominant cause |","|---|---|---:|---:|---|"]+[f"| {w} | {cfg} | {m:.2f} | {i:.2f} | {c} |" for w,cfg,m,i,c in rows]
print("\n".join(lines)); open(f"{R}/FINAL_TABLE.md","w").write("# Realistic-setting screen — final table (pinned cores, high-MPKI operating point; cause from the C6-off / one-core diagnostics)\n\n"+"\n".join(lines)+"\n")
