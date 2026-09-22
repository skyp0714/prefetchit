#!/usr/bin/env python3
"""Per-round medians over reps: speedup vs that round's base, MPKI, instruction ratio, real-fill share. Usage: ws_rounds.py ab1 ab2 ..."""
import csv, sys, statistics as st, collections, os
for d in sys.argv[1:]:
    p = os.path.join(d, 'ab.csv')
    if not os.path.exists(p): continue
    rows = [r for r in csv.DictReader(open(p)) if float(r['instr']) > 1e9 and float(r['cycles']) > 1e9]; by = collections.defaultdict(list)   # truncated perf files (full disk) show up as tiny counts; by = collections.defaultdict(list)
    for r in rows: by[r['arm']].append(r)
    base = 'base' if 'base' in by else next(iter(by))
    cyc = lambda a: st.median(float(r['cycles']) / (float(r['rps']) * 30) for r in by[a])
    ins = lambda a: st.median(float(r['instr']) for r in by[a])
    print(f"== {d} (base {base}, n={len(by[base])})")
    for a in by:
        mp = st.median(1000 * float(r['l2i']) / float(r['instr']) for r in by[a])
        fill = st.median(100 * float(r['swpf_miss']) / max(1, float(r['swpf_miss']) + float(r['swpf_hit'])) for r in by[a])
        print(f"   {a:10s} n={len(by[a])} {cyc(base)/cyc(a):6.3f}x  MPKI {mp:5.1f}  instr {ins(a)/ins(base):5.3f}x  fill {fill:3.0f}%")
