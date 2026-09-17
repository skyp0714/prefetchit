#!/usr/bin/env python3
"""From a perf-script dump with L2I-miss samples + sched:sched_switch (switch-out) + raw_syscalls:sys_exit of one process,
attribute each miss to the most recent wake-up of its thread (a sys_exit that follows a sleep switch-out) and order the missed
code lines by their typical time offset after the wake. Writes a WARMUP_LIST ("hook dso vaddr") for the LD_PRELOAD warm-up.
Usage: wake_lines.py events.txt maps.txt out.list [--top N] [--min-samples K]"""
import re,sys,collections,statistics as st
ev,mapsf,out=sys.argv[1:4]; TOP=256; MINS=2
if '--top' in sys.argv: TOP=int(sys.argv[sys.argv.index('--top')+1])
if '--min-samples' in sys.argv: MINS=int(sys.argv[sys.argv.index('--min-samples')+1])
NR={45:'recv',0:'read',19:'read',17:'read',7:'poll',232:'epoll_wait',202:'cond',270:'poll',23:'poll',44:'send',1:'send',20:'send',74:'poll',75:'poll',18:'poll',230:'cond'}  # fsync/fdatasync/pwrite -> the library's poll-hook list; pread -> read; clock_nanosleep -> cond
segs=[]
for ln in open(mapsf):
    p=ln.split(None,5)
    if len(p)>=6 and 'x' in p[1]:
        lo,hi=(int(x,16) for x in p[0].split('-')); off=int(p[2],16); name=p[5].strip().split('/')[-1]; segs.append((lo,hi,off,name))
def loc(a):
    for lo,hi,off,name in segs:
        if lo<=a<hi:
            import os
            return ('MAIN' if name==os.environ.get('MAIN_NAME','UserTimelineService') else name), a-lo+off   # link-time vaddr (PIE main, DSOs)
    return None,None
events=[]
for ln in open(ev):
    m=re.match(r'\s*\S*\s+(\d+)\s+([0-9.]+):\s+(\S+):\s*(.*)',ln)
    if not m: continue
    tid=int(m.group(1)); t=float(m.group(2)); kind=m.group(3); rest=m.group(4)
    if kind.startswith('sched:sched_switch'):
        mm=re.search(r'\S+:(\d+) \[\d+\] (\S+) ==>',rest)
        if mm and int(mm.group(1))==tid: events.append((t,tid,'out',mm.group(2)))
    elif kind.startswith('raw_syscalls:sys_exit'):
        mm=re.search(r'NR (\d+)',rest); events.append((t,tid,'exit',int(mm.group(1)) if mm else -1))
    elif kind.startswith('L2I_CODE_RD_MISS'):
        mm=re.match(r'\s*([0-9a-f]+)\s',rest)
        if mm: events.append((t,tid,'miss',int(mm.group(1),16)))
events.sort()
asleep={}; wake={}; per_hook=collections.defaultdict(lambda: collections.defaultdict(list)); wakes=collections.Counter(); misses_after=collections.Counter(); unattributed=0
for t,tid,k,v in events:
    if k=='out':
        if v.startswith('S') or v.startswith('D'): asleep[tid]=True
        wake.pop(tid,None)
    elif k=='exit':
        if asleep.get(tid):
            asleep[tid]=False; hook=NR.get(v,'other'); wake[tid]=(t,hook); wakes[hook]+=1
    elif k=='miss':
        if tid in wake:
            t0,hook=wake[tid]; d,o=loc(v)
            if d: per_hook[hook][(d,o&~63)].append((t-t0)*1e6); misses_after[hook]+=1
        else: unattributed+=1
tot=sum(misses_after.values())
print(f"events {len(events)}; wakes by hook: {dict(wakes)}; sampled misses after wakes: {tot} ({100*tot/(tot+unattributed):.0f}% of misses attributed; x2003 = misses/wake: " + ", ".join(f"{h} {2003*misses_after[h]/wakes[h]:.0f}" for h in wakes if wakes[h]) + ")")
with open(out,'w') as f:
    allines=collections.defaultdict(list)
    for hook,lines in per_hook.items():
        ranked=sorted(((st.median(v),len(v),k) for k,v in lines.items() if len(v)>=MINS), key=lambda x:(x[0]))
        # rank by (median offset) but keep only the TOP most sampled lines first
        top=sorted(ranked,key=lambda x:-x[1])[:TOP]; top.sort(key=lambda x:x[0])
        cov=sum(n for _,n,_ in top); print(f"  {hook}: {len(lines)} distinct lines, top{len(top)} cover {100*cov/max(1,misses_after[hook]):.0f}% of this hook's misses; median offsets {top[0][0]:.1f}..{top[-1][0]:.1f} us" if top else f"  {hook}: no lines")
        for med,n,(d,o) in top: f.write(f"{hook} {d} {o:#x}\n"); allines[(d,o)].append(n)
    top=sorted(((sum(v),k) for k,v in allines.items()),key=lambda x:-x[0])[:TOP]
    for n,(d,o) in top: f.write(f"any {d} {o:#x}\n")
print("written", out)
