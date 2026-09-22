#!/usr/bin/env python3
"""Which first touches does the plan NOT cover, and why? Re-runs the p6c site/target assignment on the pt6 lists and classifies every
listed line (p >= p_min) as covered / run-start (before the first eligible site + d) / gap (no eligible site within [rank-dmax, rank-d]) /
cap (a site was in range but its k was exhausted), plus the share of first touches that never make a list (p < p_min), by DSO family."""
import collections, glob, os, re, sys, bisect
sys.argv = ['x']
import importlib.util
spec = importlib.util.spec_from_file_location('pp', 'ws_plan_pass.py'); pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
symfs = os.path.abspath('symfs_wsm'); exe = pp.Syms(symfs + '/custom/MovieIdService'); exe_name = 'MovieIdService'
instr = set(open('instrumentable2.txt').read().split())
d, dmax, k, gapk, pmin, sitep = 16, 48, 8, 12, 0.5, 0.8
runs = [l.rstrip('\n').split('\t') for l in open('pt6/runs/runs.tsv')][1:]
ntype = collections.Counter(f"{r[4]}__m{r[6]}" for r in runs)
def fam(dso, sym):
    if dso != exe_name: return dso.split('.so')[0]
    s = sym
    if 'jaegertracing' in s or 'opentracing' in s: return 'exe:jaeger'
    if 'apache::thrift' in s: return 'exe:thrift'
    if 'boost::' in s: return 'exe:boost'
    if s.startswith('std::') or 'std::' in s[:12]: return 'exe:libstdc++'
    if 'media_service' in s: return 'exe:service'
    if 'mongoc' in s or 'bson' in s: return 'exe:mongoc'
    return 'exe:other'
tot = collections.Counter(); cov = collections.Counter(); why = collections.Counter(); whyfam = collections.defaultdict(collections.Counter)
lowp = collections.Counter(); lowp_fam = collections.Counter()
# calls per appearance (as in the planner) — approximate with the same rule: use planner's helper by recomputing quickly
calls = collections.Counter(); appear = collections.Counter()
maps = []
for l in open('pt6/maps.txt'):
    p = l.split()
    if len(p) >= 6 and p[5].endswith(exe_name) and 'x' in p[1]:
        a, b = (int(x, 16) for x in p[0].split('-')); maps.append((a, b, int(p[2], 16)))
segs = []
for l in pp.sh(f"readelf -lW {symfs}/custom/MovieIdService").splitlines():
    m = re.match(r"\s+LOAD\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x[0-9a-f]+\s+0x([0-9a-f]+)", l)
    if m: segs.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)))
def exe_va(addr):
    for a, b, off in maps:
        if a <= addr < b:
            fo = addr - a + off
            for so, sv, sz in segs:
                if so <= fo < so + sz: return fo - so + sv
rb = re.compile(r"^\s*\d+\s+\d+\.\d+:\s+call\S*\s+[0-9a-f]+\s+=>\s+([0-9a-f]+)\s*$")
for l in open('pt6/branches.txt'):
    m = rb.match(l)
    if not m: continue
    va = exe_va(int(m.group(1), 16))
    if va is None: continue
    i = bisect.bisect_left(exe.aa, va)
    if i < len(exe.all) and exe.all[i][0] == va: calls[exe.all[i][3]] += 1
types = {}
for f in sorted(glob.glob('pt6/runs/list_*.tsv')):
    name = os.path.basename(f)[5:-4]
    if '__all' in name: continue
    rows = pp.load_list(f); types[name] = rows
    for r in rows:
        if r['dso'] == exe_name and r['p'] >= pmin:
            fn = exe.func_at_line(r['line'])
            if fn: appear[fn[3]] += r['p'] * ntype.get(name, 0)
for name, rows in types.items():
    w = ntype.get(name, 0)
    for r in rows:
        if r['p'] < pmin: lowp[name] += r['p'] * w; lowp_fam[fam(r['dso'], r['sym'])] += r['p'] * w
    rows = [r for r in rows if r['p'] >= pmin]; n = len(rows)
    sites = []
    for i, r in enumerate(rows):
        if r['dso'] != exe_name or r['p'] < sitep: continue
        fn = exe.func_at_line(r['line'])
        if not fn or fn[3] not in instr: continue
        cpr = calls[fn[3]] / appear[fn[3]] if appear[fn[3]] else 99
        if cpr > 1.5: continue
        sites.append(i)
    assigned = [False] * n; c = 0
    for si, i in enumerate(sites):
        start = max(c, i + d); end = min(n, i + dmax)
        nxt = sites[si + 1] if si + 1 < len(sites) else n
        kk = gapk if nxt - i > dmax else k
        take = []; j = start
        while j < end and len(take) < kk:
            if not assigned[j]: take.append(j); assigned[j] = True
            j += 1
        if take: c = max(c, take[-1] + 1)
    first_site = sites[0] if sites else n
    for j, r in enumerate(rows):
        f = fam(r['dso'], r['sym']); tot[f] += r['p'] * w
        if assigned[j]: cov[f] += r['p'] * w; continue
        if j < first_site + d: reason = 'run-start'
        elif any(j - dmax < s <= j - d for s in sites): reason = 'site-cap'
        else: reason = 'gap(no site)'
        why[reason] += r['p'] * w; whyfam[reason][f] += r['p'] * w
T = sum(tot.values()); L = sum(lowp.values()); G = T + L
print(f"first touches (run-weighted, per trace): listed p>=0.5 {T:.0f}, below p 0.5 {L:.0f} ({100*L/G:.0f}% of all)")
print(f"covered by plan: {100*sum(cov.values())/G:.0f}% of all first touches; uncovered reasons: " + ", ".join(f"{k} {100*v/G:.0f}%" for k, v in why.most_common()))
print("\nby family: share of all first touches | covered | run-start | site-cap | gap | p<0.5")
for f, v in sorted(tot.items(), key=lambda x: -(x[1] + lowp_fam.get(x[0], 0)))[:12]:
    print(f"  {f:18s} {100*(v+lowp_fam.get(f,0))/G:5.1f}% | {100*cov[f]/G:5.1f} | {100*whyfam['run-start'][f]/G:5.1f} | {100*whyfam['site-cap'][f]/G:5.1f} | {100*whyfam['gap(no site)'][f]/G:5.1f} | {100*lowp_fam.get(f,0)/G:5.1f}")
