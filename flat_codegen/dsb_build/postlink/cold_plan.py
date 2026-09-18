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
ap.add_argument('--got-only-sites',default=None,help='file of site functions compiled in shared-object modules: their bursts use the GOT form for every target')
ap.add_argument('--rates',default=None,help='rates.txt from cold_trace_rate.sh: per-function entry counts; sites are chosen by lowest entry rate and (site,target) pairs whose executions per saved miss exceed --max-cost are dropped')
ap.add_argument('--rate-ref-pattern',default='UserTimelineHandler16ReadUserTimeline'); ap.add_argument('--rate-ref-hz',type=float,default=6000.0); ap.add_argument('--max-cost',type=float,default=20.0)
ap.add_argument('--miss-period',type=float,default=1000.0); ap.add_argument('--trace-secs',type=float,default=25.0)
ap.add_argument('--epoch-gate',action='store_true',help='bursts are epoch-gated (guard bytes added to k)'); ap.add_argument('--epoch-fn',default=None,help='function whose entry increments the epoch (6 B added; becomes a site)'); ap.add_argument('--rate-cap',type=float,default=None,help='cap per-site entry rate (Hz) in the cost model, e.g. 6000 with epoch gating')
ap.add_argument('--base-plan',default=None,help='previous plan whose bursts are already in the traced layout (twin trace): keep each site k >= its old k and do not shift offsets')
ap.add_argument('--site-exec',default=None,help='site_exec.txt from cold_site_profile.sh (instruction samples on prefetch insns per site of the previous build)'); ap.add_argument('--exec-period',type=float,default=20000.0); ap.add_argument('--exec-secs',type=float,default=20.0); ap.add_argument('--max-exec-ratio',type=float,default=10.0,help='drop a site whose measured prefetch executions per second exceed R x the misses it saves per second')
ap.add_argument('--no-got',action='store_true',help='drop libc (GOT-anchored) targets')
ap.add_argument('--fallback',action='store_true',help='no entry in window: use the oldest instrumentable exe function seen in the LBR (its entry precedes the window)')
ap.add_argument('--drop-own-line0',action='store_true',help='never prefetch line 0 of the site itself')
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
rate_cnt={}; rate_ref=None
if A.rates:
    for l in open(A.rates):
        if l.startswith('#'): continue
        c,n=l.split(None,1); rate_cnt[n.strip()]=int(c)
    refs=[c for n,c in rate_cnt.items() if A.rate_ref_pattern in n]
    rate_ref=max(refs) if refs else None
def hz(fn):
    if not A.rates or rate_ref is None: return 0.0
    v=A.rate_ref_hz*rate_cnt.get(fn,0)/rate_ref
    return min(v,A.rate_cap) if A.rate_cap else v
# libc anchors: exported non-IFUNC FUNC symbols
lsyms=[]
for l in subprocess.run(['readelf','-sW','--dyn-syms',A.libc],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)>=8 and f[3]=='FUNC' and f[4] in ('GLOBAL','WEAK') and f[6]!='UND':
        nm=f[7]
        if '@' in nm and '@@' not in nm: continue   # compat (non-default) version: not linkable by bare name
        lsyms.append((int(f[1],16),nm.split('@')[0]))
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
    lead=0; best=None; best_lead=0; entry_hit=False
    for fr,to,cyc,ty in ents:
        c=int(cyc) if cyc!='-' else 0; lead+=max(0,c)
        tov=int(to,16); tdso,_=loc(tov)
        if tdso and tdso.endswith('UserTimelineService'):
            va2=off2va(tov-exe_base); fa2,fn2=func_of(va2)
            if fn2 is not None and va2==fa2 and fn2 in instr and A.min_lead<=lead<=A.max_lead:
                entry_hit=True
                if best is None or (hz(fn2),-lead)<(hz(best),-best_lead): best=fn2; best_lead=lead
        if lead>A.max_lead: break
    if entry_hit: stat['attributed: earlier entry']+=1
    if best is None and A.fallback:
        # oldest branch whose source or target lies in an instrumentable exe function: that function was running at the far end of the
        # window, so its entry happened even earlier (lead >= window)
        for fr,to,cyc,ty in reversed(ents):
            for a in (int(fr,16),int(to,16)):
                dso2,_=loc(a)
                if dso2 and dso2.endswith('UserTimelineService'):
                    fa2,fn2=func_of(off2va(a-exe_base))
                    if fn2 is not None and fn2 in instr and (best is None or hz(fn2)<hz(best)): best=fn2
            # keep scanning: choose the lowest-rate function seen anywhere in the window
        if best is not None: stat['attributed: oldest running function (fallback)']+=1
    if best is None:
        if fn is not None and kind=='exe' and fn in instr: best=fn; stat['attributed: own entry (no earlier entry in window)']+=1
        else: stat['drop: no instrumentable site in LBR window']+=1; continue
    if A.no_got and target[2]==1: stat['drop: got target (--no-got)']+=1; continue
    if A.drop_own_line0 and target[2]==0 and target[0]==best and target[1]==0: stat['drop: own line 0']+=1; continue
    if target[2]==0 and target[0] not in glob and best!=target[0]: stat['drop: local target from other site']+=1; continue
    plan[best][target]+=1; line_sites[target][best]+=1
# prune: per line keep the top sites; per site keep weight>=min_w and cap
for t,ss in line_sites.items():
    keep=set(s for s,_ in ss.most_common(A.max_sites_per_line))
    for s in list(ss):
        if s not in keep: del plan[s][t]
site_exec={}
if A.site_exec:
    for l in open(A.site_exec):
        if l.startswith('#'): continue
        c,n=l.split(None,1); site_exec[n.strip()]=int(c)
sites={}; cost_dropped=0; cost_dropped_w=0; exec_dropped=0; exec_dropped_w=0
for s,ts in plan.items():
    if A.site_exec and s in site_exec:
        execs_per_s=site_exec[s]*A.exec_period/A.exec_secs
        saved_per_s=sum(w for t,w in ts.items() if w>=A.min_w)*A.miss_period/A.trace_secs
        if execs_per_s>A.max_exec_ratio*max(1e-9,saved_per_s):
            exec_dropped+=1; exec_dropped_w+=sum(ts.values()); continue
    kept=[]
    for t,w in ts.most_common():
        if w<A.min_w: continue
        if A.rates and rate_ref is not None:
            saved_per_s=w*A.miss_period/A.trace_secs; ratio=hz(s)/max(1e-9,saved_per_s)
            if ratio>A.max_cost: cost_dropped+=1; cost_dropped_w+=w; continue
        kept.append((t,w))
    kept=kept[:A.max_per_site]
    if kept: sites[s]=kept
gotonly=set(l.strip() for l in open(A.got_only_sites)) if A.got_only_sites else set()
def burst_bytes(ts,site=None):
    b=0; anchors=collections.defaultdict(list)
    for (sym,off,got),w in ts:
        if got or site in gotonly: anchors[sym].append(off)
        else: b+=7
    for a,offs in anchors.items():
        b+=7+sum(4 if o==0 else 5 if -128<=o<128 else 8 for o in offs)
    return b
if A.epoch_fn and A.epoch_fn not in sites: sites[A.epoch_fn]=[]
def site_bytes(s,ts):
    b=burst_bytes(ts,s)
    if A.epoch_fn and s==A.epoch_fn: b+=6
    if A.epoch_gate and ts: b+=(28 if s in gotonly else 31)
    return b
K={s:(site_bytes(s,ts)+15)//16*16 for s,ts in sites.items()}
baseK={}
if A.base_plan:
    import json as _j
    baseK={s:v['k'] for s,v in _j.load(open(A.base_plan))['sites'].items()}
    for s in list(K): K[s]=max(K[s],baseK.get(s,0))
    # sites that had a burst in the traced layout but have no targets now must keep an (empty) burst of the same size
    for s,k in baseK.items():
        if s not in sites: sites[s]=[]; K[s]=k
    grown=[s for s in sites if s in baseK and K[s]>baseK[s]]
    print(f"base plan: {len(baseK)} sites kept, {len(grown)} bursts grew beyond the traced layout (offsets inside them drift)")
out={"sites":{}}; ntargets=0; wcov=0
for s,ts in sites.items():
    tl=[]
    for (sym,off,got),w in ts:
        o=off
        if not got and sym in K and off>=16 and not A.base_plan: o=off+K[sym]
        elif not got and A.base_plan and sym in K and sym not in baseK and off>=16: o=off+K[sym]   # new site in an unshifted function
        tl.append([sym,o,got]); ntargets+=1; wcov+=w
    out["sites"][s]={"k":K[s],"t":tl}
json.dump(out,open(A.out,'w'))
tot_attr=sum(v for k,v in stat.items() if k.startswith('attributed'))
print(f"measured-exec filter: dropped {exec_dropped} sites, weight {exec_dropped_w} ({100*exec_dropped_w/max(1,n):.1f}% of samples)")
print(f"cost filter: dropped {cost_dropped} (site,target) pairs, weight {cost_dropped_w} ({100*cost_dropped_w/max(1,n):.1f}% of samples)")
print(f"samples={n} attributed={tot_attr} ({100*tot_attr/max(1,n):.1f}%) kept_weight={wcov} ({100*wcov/max(1,n):.1f}% of samples) sites={len(sites)} targets={ntargets} "
      f"avg_burst={sum(K.values())/max(1,len(K)):.0f}B got_targets={sum(1 for s in sites for (sym,off,got),w in sites[s] if got)}")
for k,v in stat.most_common(): print(f"  {100*v/max(1,n):5.1f}%  {k}")
top=sorted(sites.items(),key=lambda kv:-sum(w for _,w in kv[1]))[:8]
print("top sites: "+'; '.join(f"{s[:50]} ({len(ts)} lines, w={sum(w for _,w in ts)})" for s,ts in top))
