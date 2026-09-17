#!/usr/bin/env python3
"""Timeline prefetch planner for wake-bound services.
Input: perf-script dump with L2I-miss samples (with -b LBR not needed), sched:sched_switch (switch-out) and raw_syscalls:sys_exit of the
process, plus /proc/pid/maps. Every miss sample is attributed to the most recent wake-up of its thread and gets an offset (µs after wake).
Sites  : per SLOT-µs slot after the wake, the top-K most frequently sampled IPs (code the thread reliably executes at that time).
Targets: lines whose median offset lies AHEAD_MIN..AHEAD_MAX µs after the site's slot, split round-robin over that slot's sites.
Output : prefetchit.plan.v1-style raw plans per binary (site = dso/file offset -> mangled+symbol_offset via nm; file:line via addr2line),
         to be passed through inline_fix_operands.py (operands) and built inline by the IR pass.
Usage: timeline_plan.py events.txt maps.txt OUTDIR --bins BIN=path,... [--slot 5] [--ahead-min 10] [--ahead-max 20] [--sites-per-slot 3] [--max-targets 48]"""
import re,sys,collections,statistics as st,subprocess,json,os,argparse,bisect
ap=argparse.ArgumentParser(); ap.add_argument('events'); ap.add_argument('maps'); ap.add_argument('outdir')
ap.add_argument('--bins',required=True,help='comma list dsoname=path (dso name as in maps basename, or MAIN=path for the executable)')
ap.add_argument('--slot',type=float,default=5); ap.add_argument('--ahead-min',type=float,default=10); ap.add_argument('--ahead-max',type=float,default=20)
ap.add_argument('--sites-per-slot',type=int,default=3); ap.add_argument('--max-targets',type=int,default=48); ap.add_argument('--min-samples',type=int,default=3)
ap.add_argument('--max-offset',type=float,default=200)
ap.add_argument('--target-bins',default='',help='comma list dsoname=path usable only as prefetch TARGETS (not rebuilt; exported symbols only)')
a=ap.parse_args()
bins={}
for kv in a.bins.split(','):
    k,v=kv.split('='); bins[k]=v
tbins={}
for kv in [x for x in a.target_bins.split(',') if x]:
    k,v=kv.split('='); tbins[k]=v
allbins={**bins,**tbins}
segs=[]
for ln in open(a.maps):
    p=ln.split(None,5)
    if len(p)>=6 and 'x' in p[1]:
        lo,hi=(int(x,16) for x in p[0].split('-')); off=int(p[2],16); name=p[5].strip().split('/')[-1]; segs.append((lo,hi,off,name))
def loc(addr):
    for lo,hi,off,name in segs:
        if lo<=addr<hi: return ('MAIN' if name=='UserTimelineService' else name), addr-lo+off
    return None,None
def binkey(d,table=None):
    for k in (table or bins):
        if k==d or d.startswith(k) or k.startswith(d): return k
    return None
def anykey(d): return binkey(d) or binkey(d,tbins)
events=[]
for ln in open(a.events):
    m=re.match(r'\s*\S*\s+(\d+)\s+([0-9.]+):\s+(\S+):\s*(.*)',ln)
    if not m: continue
    tid=int(m.group(1)); t=float(m.group(2)); kind=m.group(3); rest=m.group(4)
    if kind.startswith('sched:sched_switch'):
        mm=re.search(r'\S+:(\d+) \[\d+\] (\S+) ==>',rest)
        if mm and int(mm.group(1))==tid: events.append((t,tid,'out',mm.group(2)))
    elif kind.startswith('raw_syscalls:sys_exit'): events.append((t,tid,'exit',0))
    elif kind.startswith('L2I_CODE_RD_MISS'):
        mm=re.match(r'\s*([0-9a-f]+)\s',rest)
        if mm: events.append((t,tid,'miss',int(mm.group(1),16)))
events.sort()
asleep={}; wake={}; ipoff=collections.defaultdict(list); lineoff=collections.defaultdict(list)
for t,tid,k,v in events:
    if k=='out':
        if v[0] in 'SD': asleep[tid]=True
        wake.pop(tid,None)
    elif k=='exit':
        if asleep.get(tid): asleep[tid]=False; wake[tid]=t
    elif k=='miss' and tid in wake:
        d,o=loc(v)
        if d and anykey(d):
            off=(t-wake[tid])*1e6
            if off<=a.max_offset:
                if binkey(d): ipoff[(d,o)].append(off)
                lineoff[(d,o&~63)].append(off)
nslots=int(a.max_offset//a.slot)+1
# sites per slot: IPs by sample count within the slot
slot_ips=collections.defaultdict(collections.Counter)
for (d,o),offs in ipoff.items():
    for off in offs: slot_ips[int(off//a.slot)][(d,o)]+=1
line_med={k:(st.median(v),len(v)) for k,v in lineoff.items() if len(v)>=a.min_samples}
plans=collections.defaultdict(list); assigned=collections.Counter(); nsite=0; ntgt=0
for s in range(nslots):
    sites=[ip for ip,_ in slot_ips[s].most_common(a.sites_per_slot)]
    if not sites: continue
    lo=(s*a.slot)+a.ahead_min; hi=(s*a.slot)+a.ahead_max
    tg=sorted([(n,k) for k,(med,n) in line_med.items() if lo<=med<hi],reverse=True)
    if not tg: continue
    per=max(1,min(a.max_targets, (len(tg)+len(sites)-1)//len(sites)))
    for i,site in enumerate(sites):
        mine=[k for _,k in tg[i::len(sites)]][:per]
        if not mine: continue
        plans[site[0]].append({'site':site,'targets':mine}); nsite+=1; ntgt+=len(mine)
print(f"wake-attributed samples: {sum(len(v) for v in ipoff.values())}; lines with >= {a.min_samples} samples: {len(line_med)}; sites {nsite}, targets {ntgt} (slot {a.slot} us, ahead {a.ahead_min}-{a.ahead_max} us)")
# symbolize: site -> mangled + symbol_offset + file:line ; target -> mangled + symbol_offset (line start)
def symtab(path,dynamic=False):
    out=subprocess.run(['nm','-D','--defined-only',path] if dynamic else ['nm','--defined-only',path],capture_output=True,text=True).stdout
    syms=[]
    for ln in out.splitlines():
        p=ln.split()
        if len(p)==3 and p[1] in 'TtWw': syms.append((int(p[0],16),p[2]))
    syms.sort(); return syms
tabs={k:symtab(v) for k,v in bins.items()}
tabs.update({k:symtab(v,True) for k,v in tbins.items()})
def sym(d,vaddr):
    tab=tabs[d]; i=bisect.bisect_right([x[0] for x in tab],vaddr)-1
    if i<0: return None,None
    return tab[i][1], vaddr-tab[i][0]
def a2l(path,addrs):
    if not addrs: return {}
    out=subprocess.run(['addr2line','-e',path]+[hex(x) for x in addrs],capture_output=True,text=True).stdout.splitlines()
    return {x:o for x,o in zip(addrs,out)}
os.makedirs(a.outdir,exist_ok=True); summary={}
for d,entries in plans.items():
    path=bins[binkey(d)]; addrs=sorted({e['site'][1] for e in entries}); fl=a2l(path,addrs); inj=[]
    for e in entries:
        s_sym,s_off=sym(binkey(d),e['site'][1]); floc=fl.get(e['site'][1],'??:0'); f,_,l=floc.rpartition(':')
        if not s_sym or f.startswith('??') or not l.isdigit(): continue
        for td,to in e['targets']:
            tk=anykey(td)
            if not tk: continue
            t_sym,t_off=sym(tk,to)
            if not t_sym or (tk in tbins and t_off>0x10000): continue   # exported-symbol anchor must be near
            inj.append({'prefetch_mnemonic':'prefetcht1','samples':1,
                        'site':{'mangled':s_sym,'function':s_sym,'symbol_offset':hex(s_off),'addr':hex(e['site'][1]),'file':f,'line':int(l),'branch_type':'TIMELINE'},
                        'target':{'mangled':t_sym,'function':t_sym,'symbol_offset':hex(t_off),'addr':hex(to),'dso':tk}})
    plan={'schema':'prefetchit.plan.v1','binary':path,'injections':inj,'prefetch':{'mnemonic':'prefetcht1','byte_offsets':[0],'operand':'pc-relative-symbol-offset'}}
    json.dump(plan,open(os.path.join(a.outdir,f'{binkey(d)}.raw.plan.json'),'w')); summary[binkey(d)]=len(inj)
print("injections per binary:",summary)
