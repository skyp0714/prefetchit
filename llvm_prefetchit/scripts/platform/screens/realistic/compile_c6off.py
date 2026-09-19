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
seen=set()
for r in rd(f'{R}/cause_diag.csv'):
    if r['config']=='noC6' and r['cores']!='36' and (r['workload'].startswith('dacapo') or r['workload'].startswith('renaissance')) and r['workload'] not in seen:
        seen.add(r['workload']); rows.append((r['workload'],'4 cores, C6 off',float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'jvm'))
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
for r in rd(f'{R}/cloudsuite_4core.csv'):
    if r['bench'].endswith('-noC6') and float(r['instr'])>1e9:
        b=r['bench'][:-5]; kind={'web-serving':'php','web-search':'jvm','data-serving':'jvm','data-caching':'sys'}.get(b,'cpp')
        rows.append((f"CloudSuite {b}",f"{r['load']}, 4 cores, C6 off",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),kind))
# dcperf v2 noC6 rows
for r in rd(f'{R}/dcperf_v2.csv'):
    if r['config']=='noC6' and r['group']=='server': rows.append((f"DCPerf v2 {r['job']}",f"{r['cores']} server cores, C6 off @{r['delay_s']}s",float(r['util_pct']),float(r['mpki']),None,float(r['ipc']),'c' if 'django' in r['job'] else 'cpp'))
rows.sort(key=lambda x:-(x[3] if x[3] else 0))
out=["| workload | setting (C6 off) | util | MPKI alone (capacity) | MPKI interleaved pool8 / pool16 | IPC | code kind → remedy |","|---|---|---:|---:|---:|---:|---|"]
for w,cfg,u,am,sm,ipc,kind in rows:
    smt='—' if sm is None else ('/'.join('—' if x is None else f"{x:.2f}" for x in sm) if isinstance(sm,tuple) else f"{sm:.2f}")
    out.append(f"| {w} | {cfg} | {u:.0f}% | {am:.2f} | {smt} | {ipc:.2f} | {KIND[kind]} |")
open(f'{R}/C6OFF_TABLE.md','w').write("# Capacity/interleaving-only sweep (deep C-states disabled on the server cores)\n\n"+'\n'.join(out)+'\n'); print('\n'.join(out))
