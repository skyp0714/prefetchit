#!/usr/bin/env python3
"""Trace-guided cold-path plan. For every L2I-miss sample (with LBR) in a trace of the pass-free fat-static binary, attribute the missed
line to the oldest function entry in its branch history that is instrumentable and gives MIN..MAX cycles of lead; emit a plan
{"sites": {fn: {"k": burst_bytes, "t": [[anchor, off, got], ...]}}} for PREFETCHIT_COLD_PLAN. Offsets are measured on the pass-free
layout and shifted by the burst size k of the anchor function (bursts sit after the prologue, so offsets < 16 are not shifted).
usage: cold_plan.py TRACE_DIR EXE LIBC INSTRUMENTABLE_SYMS OUT.json [--min-w 3] [--max-per-site 32] [--min-lead 60] [--max-lead 4000]"""
import sys,re,bisect,collections,json,subprocess,argparse
ap=argparse.ArgumentParser(); ap.add_argument('trace'); ap.add_argument('exe'); ap.add_argument('libc'); ap.add_argument('instr'); ap.add_argument('out')
ap.add_argument('--min-w',type=int,default=3); ap.add_argument('--max-per-site',type=int,default=32); ap.add_argument('--min-lead',type=int,default=60); ap.add_argument('--max-lead',type=int,default=4000)
ap.add_argument('--max-sites-per-line',type=int,default=2)
A=ap.parse_args()
# maps
segs=[]
for l in open(f"{A.trace}/maps.txt"):
    p=l.split(None,5)
    if len(p)>=6 and 'x' in p[1]:
        lo,hi=(int(x,16) for x in p[0].split('-')); segs.append((lo,hi,int(p[2],16),p[5].strip()))
def loc(a):
    for lo,hi,off,name in segs:
        if lo<=a<hi: return name.rsplit('/',1)[-1], a-lo+off   # file offset
    return None,None
exe_base=next(lo for lo,hi,off,n in segs if n.endswith('/custom/UserTimelineService') and off==0) if any(n.endswith('/custom/UserTimelineService') and off==0 for lo,hi,off,n in segs) else None
if exe_base is None:
    lo=min(lo for lo,hi,off,n in segs if n.endswith('/custom/UserTimelineService')); off=min(off for lo,hi,off,n in segs if n.endswith('/custom/UserTimelineService')); exe_base=lo-off
libc_segs=[(lo,hi,off) for lo,hi,off,n in segs if n.endswith('libc.so.6')]
# exe symbols (vaddr == file offset + segment delta; for a PIE the first LOAD has vaddr 0 == offset 0, and objdump/nm addresses are vaddrs)
def ph_delta(exe):
    d={}
    for l in subprocess.run(['readelf','-lW',exe],capture_output=True,text=True).stdout.splitlines():
        f=l.split()
        if f and f[0]=='LOAD': d[(int(f[1],16),int(f[1],16)+int(f[4],16))]=int(f[2],16)-int(f[1],16)
    return d
delta=ph_delta(A.exe)
def off2va(o):
    for (lo,hi),dv in delta.items():
        if lo<=o<hi: return o+dv
    return o
syms=[]; glob=set()
for l in subprocess.run(['nm','--defined-only',A.exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw':
        syms.append((int(f[0],16),f[2]))
        if f[1] in 'TW': glob.add(f[2])
syms.sort(); saddr=[a for a,_ in syms]; sname={n:a for a,n in syms}
def func_of(va):
    i=bisect.bisect_right(saddr,va)-1
    return syms[i] if i>=0 else (None,None)
instr=set(l.strip() for l in open(A.instr) if l.strip())
# libc anchors: exported non-IFUNC FUNC symbols
lsyms=[]
for l in subprocess.run(['readelf','-sW','--dyn-syms',A.libc],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)>=8 and f[3]=='FUNC' and f[4] in ('GLOBAL','WEAK') and f[6]!='UND': lsyms.append((int(f[1],16),f[7].split('@')[0]))
lsyms.sort(); laddr=[a for a,_ in lsyms]
def libc_anchor(va):
    i=bisect.bisect_right(laddr,va)-1
    return lsyms[i] if i>=0 else (None,None)
def libc_va(a):
    for lo,hi,off in libc_segs:
        if lo<=a<hi: return a-lo+off      # libc: vaddr == file offset for the text segment (delta 0 in glibc builds)
    return None
DSO=r'\((?:[^()]|\([^()]*\))*\)'
ENT=re.compile(r'0x([0-9a-f]+) '+DSO+r'/0x([0-9a-f]+) '+DSO+r'/[MPX-]/[^/]*/[^/]*/([0-9-]+)/(\w+)/')
HEAD=re.compile(r'\s*([0-9a-f]+)\s+(?:\S+\s+)?\(([^)]*)\)')
n=0; stat=collections.Counter(); plan=collections.defaultdict(collections.Counter); line_sites=collections.defaultdict(collections.Counter)
for ln in open(f"{A.trace}/samples_lbr.txt"):
    m=HEAD.match(ln)
    if not m: continue
    n+=1; ip=int(m.group(1),16); d=m.group(2).rsplit('/',1)[-1]
    if d.endswith('UserTimelineService'):
        va=off2va(ip-exe_base); fa,fn=func_of(va); tline=(va>>6)<<6
        if fn is None: stat['drop: no exe symbol']+=1; continue
        if fn in glob: target=(fn, tline-fa, 0)
        elif fn in instr: target=(fn, tline-fa, 0)   # local function: only its own entry may reference it (checked below)
        else: stat['drop: local non-instrumentable function']+=1; continue
        kind='exe'
    elif d=='libc.so.6':
        lva=libc_va(ip)
        if lva is None: stat['drop: libc unmapped']+=1; continue
        aa,an=libc_anchor(lva)
        if an is None: stat['drop: libc no anchor']+=1; continue
        target=(an, ((lva>>6)<<6)-aa, 1); kind='libc'
    else: stat['drop: other dso']+=1; continue
    ents=ENT.findall(ln)
    # walk branch history newest->oldest; candidate sites = call/jump targets that are instrumentable function entries
    lead=0; best=None
    for fr,to,cyc,ty in ents:
        c=int(cyc) if cyc!='-' else 0; lead+=max(0,c)
        tov=int(to,16); tdso,_=loc(tov)
        if tdso and tdso.endswith('UserTimelineService'):
            va2=off2va(tov-exe_base); fa2,fn2=func_of(va2)
            if fn2 is not None and va2==fa2 and fn2 in instr and A.min_lead<=lead<=A.max_lead:
                best=fn2   # keep the oldest acceptable entry
        if lead>A.max_lead: break
    if best is None:
        if fn is not None and kind=='exe' and fn in instr: best=fn; stat['attributed: own entry (no earlier entry in window)']+=1
        else: stat['drop: no instrumentable site in LBR window']+=1; continue
    else: stat['attributed: earlier entry']+=1
    if target[2]==0 and target[0] not in glob and best!=target[0]: stat['drop: local target from other site']+=1; continue
    plan[best][target]+=1; line_sites[target][best]+=1
# prune: per line keep the top sites; per site keep weight>=min_w and cap
for t,ss in line_sites.items():
    keep=set(s for s,_ in ss.most_common(A.max_sites_per_line))
    for s in list(ss):
        if s not in keep: del plan[s][t]
sites={}
for s,ts in plan.items():
    kept=[(t,w) for t,w in ts.most_common() if w>=A.min_w][:A.max_per_site]
    if kept: sites[s]=kept
def burst_bytes(ts):
    b=0; anchors=collections.defaultdict(list)
    for (sym,off,got),w in ts:
        if got: anchors[sym].append(off)
        else: b+=7
    for a,offs in anchors.items():
        b+=7+sum(4 if o==0 else 5 if -128<=o<128 else 8 for o in offs)
    return b
K={s:(burst_bytes(ts)+15)//16*16 for s,ts in sites.items()}
out={"sites":{}}; ntargets=0; wcov=0
for s,ts in sites.items():
    tl=[]
    for (sym,off,got),w in ts:
        o=off
        if not got and sym in K and off>=16: o=off+K[sym]
        tl.append([sym,o,got]); ntargets+=1; wcov+=w
    out["sites"][s]={"k":K[s],"t":tl}
json.dump(out,open(A.out,'w'))
tot_attr=sum(v for k,v in stat.items() if k.startswith('attributed'))
print(f"samples={n} attributed={tot_attr} ({100*tot_attr/max(1,n):.1f}%) kept_weight={wcov} ({100*wcov/max(1,n):.1f}% of samples) sites={len(sites)} targets={ntargets} "
      f"avg_burst={sum(K.values())/max(1,len(K)):.0f}B got_targets={sum(1 for s in sites for (sym,off,got),w in sites[s] if got)}")
for k,v in stat.most_common(): print(f"  {100*v/max(1,n):5.1f}%  {k}")
top=sorted(sites.items(),key=lambda kv:-sum(w for _,w in kv[1]))[:8]
print("top sites: "+'; '.join(f"{s[:50]} ({len(ts)} lines, w={sum(w for _,w in ts)})" for s,ts in top))
