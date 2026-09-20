#!/usr/bin/env python3
"""Capacity/interleaving-only sweep table (deep C-states off on the server cores): per workload the pinned-alone MPKI (capacity),
the interleaved MPKI (all containers of a stack on an 8-/16-core pool), and the remedy that fits the code kind."""
import csv,os,collections
R=os.path.dirname(os.path.abspath(__file__))
def rd(f): return list(csv.DictReader(open(f))) if os.path.exists(f) else []
KIND={ # code kind → what our toolchain can do
 'jvm':'JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only',
 'php':'JIT (php-fpm opcache): AOT pass n/a',
 'lua':'OpenResty/LuaJIT + nginx: nginx AOT part only (rebuild with the pass)',
 'go':'Go toolchain: no pass; would need a Go-side inserter',
 'cpp':'C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link',
 'c':'C AOT (single link unit): cold plan with file-qualified sites',
 'sys':'system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source',
}
rows=[]
# databases (C6 off sweep)
for r in rd(f'{R}/c6off_sweep.csv'):
    rows.append((r['workload'],f"{r['clients']} clients, 4 cores, C6 off",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'c'))
# JVM (cause_diag noC6 rows)
seen={}
for r in rd(f'{R}/cause_diag.csv'):
    if r['config'].startswith('noC6') and '1core' not in r['config'] and r['cores']!='36' and (r['workload'].startswith('dacapo') or r['workload'].startswith('renaissance')):
        jdk=r['config'][5:].lstrip('_') or 'java-21'; key=r['workload']
        if key in seen and float(r['mpki'])<=seen[key]: continue
        seen[key]=float(r['mpki']); rows=[x for x in rows if x[0]!=key]
        rows.append((key,f"4 cores, C6 off, {jdk.replace('-openjdk-amd64','')}",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'jvm'))
    if r['config']=='noC6' and r['workload'].startswith('mariadb') and r['cores']=='36-39': pass
# stacks: pinned-alone C6 off vs shared pools
kind_of=lambda c: 'lua' if 'nginx-thrift' in c else 'sys' if any(k in c for k in ('redis','memcached','mongodb','dns')) else 'go' if c.startswith('hotel') else 'cpp'
alone={}
for f in ('dsb_social_noC6.csv','dsb_hotel_noC6.csv','dsb_media_noC6.csv'):
    for r in rd(f'{R}/{f}'):
        if float(r['instr'])>1e9: alone[(r['stack'],r['container'])]=r
shared=collections.defaultdict(dict)
for r in rd(f'{R}/c6off_shared.csv'):
    if float(r['instr'])>1e9: shared[(r['stack'],r['container'])][r['pool']]=r
for k in sorted(set(alone)|set(shared)):
    a=alone.get(k); s=shared.get(k,{}); s8=s.get('0-7'); s16=s.get('0-15')
    kind=kind_of(k[0]+'/'+k[1]); label=f"{k[0]}/{k[1]}"
    am=float(a['mpki']) if a else None; sm=float(s8['mpki']) if s8 else (float(s16['mpki']) if s16 else None)
    cfg=(f"alone {a['ncores']} core(s) {float(a['util_pct']):.0f}% util" if a else "alone n/a")+(f"; pool8 {float(s8['cpu_pct']):.0f}% cpu" if s8 else '')+(f"; pool16 {float(s16['cpu_pct']):.0f}% cpu" if s16 else '')
    rows.append((label,cfg,float(a['util_pct']) if a else 0,am if am is not None else 0,(float(s8['mpki']) if s8 else None, float(s16['mpki']) if s16 else None),float(a['ipc']) if a else (float(s8['ipc']) if s8 else 0),kind))
# cloudsuite noC6 rows
csg=collections.defaultdict(list)
for r in rd(f'{R}/cloudsuite_4core.csv'):
    if r['bench'].endswith('-noC6') and float(r['instr'])>1e9 and float(r['util_pct'])>=2: csg[r['bench']].append(r)
def _pick_cs(c):
    ok=[x for x in c if float(x['util_pct'])>=15]
    return max(ok,key=lambda x:(float(x['mpki']),float(x['util_pct']))) if ok else max(c,key=lambda x:(float(x['util_pct']),float(x['mpki'])))
for _b,c in csg.items():
    r=_pick_cs(c)
    if True:
        b=r['bench'][:-5]; kind={'web-serving':'php','web-search':'jvm','data-serving':'jvm','data-caching':'sys','graph-analytics':'jvm','in-memory-analytics':'jvm','data-analytics-master':'jvm','data-analytics-slave':'jvm'}.get(b,'cpp')
        rows.append((f"CloudSuite {b}",f"{r['load']}, 4 cores, C6 off",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),kind))
# dcperf v2 noC6 rows
dc=collections.defaultdict(dict)
for r in rd(f'{R}/dcperf_v2.csv'):
    if r['group']=='server': dc[r['job']][(r['config'],r['delay_s'])]=r
for job,d in dc.items():
    pick=[v for (c,dl),v in d.items() if c=='noC6'] or list(d.values()); r=max(pick,key=lambda x:float(x['delay_s']))
    dflt=[v for (c,dl),v in d.items() if c=='default']; note=f" (default {float(dflt[-1]['mpki']):.2f})" if dflt and r['config']=='noC6' else ''
    kind='c' if 'django' in job else 'cpp' if ('feedsim' in job or 'adsim' in job or 'cdn' in job) else 'sys'
    rows.append((f"DCPerf v2 {job}",f"{r['cores']} server cores, {r['config']}{note}, util {float(r['util_pct']):.0f}%",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),kind))
def pick_op(cands):
    ok=[c for c in cands if float(c['util_pct'])>=15]
    return max(ok,key=lambda c:(float(c['mpki']),float(c['util_pct']))) if ok else max(cands,key=lambda c:(float(c['util_pct']),float(c['mpki'])))
batch=collections.defaultdict(list); cdn=collections.defaultdict(list)
for r in rd(f'{R}/dcperf_v2.csv'):
    if r['group']=='all' and float(r['instr'])>1e9: batch[r['job']].append(r)
    if r['job']=='cdn_bench' and float(r['instr'])>1e9: cdn[r['group']].append(r)
for job,c in batch.items():
    r=pick_op(c); rows.append((f"DCPerf v2 {job} (batch)",f"{r['cores']}, C6 off, {r['delay_s']} s in",min(100.0,float(r['util_pct'])),float(r['mpki']),None,float(r['ipc']),'cpp'))
if cdn.get('proxy'):
    r=pick_op(cdn['proxy']); cs=pick_op(cdn['content']) if cdn.get('content') else None
    rows.append((f"DCPerf v2 cdn_bench proxy_server (proxygen)",f"{r['cores']} proxy cores, {r['config']}"+(f"; content_server {float(cs['mpki']):.2f}" if cs else ''),float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'cpp'))
# TailBench (integrated harness, 4 threads on 4 cores, C6 off): paper QPS and QPS/4
tb=collections.defaultdict(list)
for r in rd(f'{R}/tailbench.csv'):
    if float(r['instr'])>1e8: tb[r['app']].append(r)
for app,c in tb.items():
    r=pick_op(c); other=[x for x in c if x is not r]
    rows.append((f"TailBench {app}",f"{r['cores']}, C6 off, {r['qps']} qps"+(f" (other load {', '.join(f'{x['qps']} qps {float(x['mpki']):.2f}' for x in other)})" if other else ''),float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'cpp'))
# FleetBench (single core 36, C6 off)
for r in rd(f'{R}/fleetbench.csv'):
    if float(r['instr'])>1e8: rows.append((f"FleetBench {r['bench']}",f"core {r['cores']}, C6 off",100.0,float(r['mpki']),None,float(r['ipc']),'cpp'))
rows.sort(key=lambda x:-(x[3] if x[3] else 0))
out=["| workload | setting (C6 off) | util | MPKI alone (capacity) | MPKI interleaved pool8 / pool16 | IPC | code kind → remedy |","|---|---|---:|---:|---:|---:|---|"]
for w,cfg,u,am,sm,ipc,kind in rows:
    smt='—' if sm is None else ('/'.join('—' if x is None else f"{x:.2f}" for x in sm) if isinstance(sm,tuple) else f"{sm:.2f}")
    out.append(f"| {w} | {cfg} | {u:.0f}% | {am:.2f} | {smt} | {ipc:.2f} | {KIND[kind]} |")
open(f'{R}/C6OFF_TABLE.md','w').write("# Capacity/interleaving-only sweep (deep C-states disabled on the server cores)\n\n"+'\n'.join(out)+'\n'); print('\n'.join(out))
