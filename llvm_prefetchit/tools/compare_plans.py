#!/usr/bin/env python3
"""Compare a static cost plan with the trace-guided plan it is supposed to approach: site/target overlap, and how much of the trace
plan's attributed miss weight the static plan covers (the trace plan's 4th target field carries that weight).
usage: compare_plans.py STATIC.json TRACE.json"""
import json,sys,collections
S=json.load(open(sys.argv[1])); T=json.load(open(sys.argv[2]))
def lines(p):
    d=collections.defaultdict(float)
    for s,v in p['sites'].items():
        for t in v['t']:
            w=t[3] if len(t)>3 else 1.0
            d[(t[0],t[1]//64*64,t[2])]+=w
    return d
sl,tl=lines(S),lines(T); ss,ts=set(S['sites']),set(T['sites'])
tw=sum(tl.values()); cov=sum(w for k,w in tl.items() if k in sl)
print(f"static: {len(ss)} sites, {len(sl)} target lines | trace: {len(ts)} sites, {len(tl)} target lines")
print(f"site overlap {len(ss&ts)} ({100*len(ss&ts)/max(1,len(ts)):.1f}% of the trace plan's sites)")
print(f"target-line overlap {len(set(sl)&set(tl))} ({100*len(set(sl)&set(tl))/max(1,len(tl)):.1f}% of lines, {100*cov/max(1e-9,tw):.1f}% of the trace plan's attributed miss weight)")
print(f"static-only lines {len(set(sl)-set(tl))}, trace-only lines {len(set(tl)-set(sl))}")
