#!/usr/bin/env python3
"""Miss-structure analysis of a perf-script LBR dump (-F ip,sym,dso,brstack) for L2I code-miss samples.
Args: lbr_raw.txt maps.txt
Prints: miss IP share by DSO; last-branch type; distance from the last taken-branch target to the miss IP;
lead cycles available at the k-th most recent CALL in the stack; top (site -> target line) pairs."""
import re,sys,collections
raw,maps=sys.argv[1],sys.argv[2]
segs=[]
for ln in open(maps):
    p=ln.split(None,5)
    if len(p)>=6 and 'x' in p[1]:
        lo,hi=(int(x,16) for x in p[0].split('-')); off=int(p[2],16); name=p[5].strip().replace(' (deleted)','').split('/')[-1]; segs.append((lo,hi,off,name))
def loc(a):
    for lo,hi,off,name in segs:
        if lo<=a<hi: return name, a-lo+off
    return '?',a
DSO=r'\((?:[^()]|\([^()]*\))*\)'
ENT=re.compile(r'0x([0-9a-f]+) '+DSO+r'/0x([0-9a-f]+) '+DSO+r'/[MPX-]/[^/]*/[^/]*/([0-9-]+)/(\w+)/')
n=0; ipdso=collections.Counter(); typ=collections.Counter(); dist=collections.Counter(); lead=collections.Counter()
pairs=collections.Counter(); k_at=collections.Counter(); samedso=collections.Counter()
LEAD_MIN=40
for ln in open(raw):
    m=re.match(r'\s*([0-9a-f]+)\s+\S+\s+\(([^)]*)\)',ln)
    if not m: continue
    ip=int(m.group(1),16); d0=m.group(2).replace(' (deleted)','').split('/')[-1]; n+=1; ipdso[d0]+=1
    ents=ENT.findall(ln)
    if not ents: continue
    fr0,to0,cyc0,ty0=int(ents[0][0],16),int(ents[0][1],16),int(ents[0][2]),ents[0][3]
    typ[ty0]+=1
    d=ip-to0
    b='neg' if d<0 else '<64' if d<64 else '<256' if d<256 else '<1K' if d<1024 else '<4K' if d<4096 else '>=4K'
    dist[b]+=1
    # walk back: accumulate cycles; find earliest CALL with lead >= LEAD_MIN (k = index)
    acc=0; chosen=None
    for k,(fr,to,cyc,ty) in enumerate(ents):
        acc+=int(cyc) if cyc!='-' else 0
        if ty=='CALL' and acc>=LEAD_MIN:
            chosen=(k,int(fr,16),acc); break
    if chosen is None:
        lead['none(<%d cyc in stack)'%LEAD_MIN]+=1; continue
    k,fr,acc=chosen
    k_at[k]+=1
    lead['<100' if acc<100 else '<300' if acc<300 else '<1000' if acc<1000 else '>=1000']+=1
    sd,so=loc(fr); td,to_=loc(ip&~63)
    pairs[(sd,so,td,to_)]+=1; samedso['same' if sd==td else 'cross']+=1
print(f"samples={n}")
print("miss IP by DSO: "+", ".join(f"{k} {100*v/n:.1f}%" for k,v in ipdso.most_common(9)))
print("last taken branch type: "+", ".join(f"{k} {100*v/n:.1f}%" for k,v in typ.most_common(8)))
print("miss IP - last branch target: "+", ".join(f"{k} {100*v/n:.1f}%" for k,v in sorted(dist.items(),key=lambda x:-x[1])))
print(f"earliest CALL in LBR stack with >= {LEAD_MIN} cycles lead: "+", ".join(f"{k} {100*v/n:.1f}%" for k,v in sorted(lead.items(),key=lambda x:-x[1])))
print("  that CALL is LBR entry k: "+", ".join(f"k={k} {100*v/n:.1f}%" for k,v in sorted(k_at.items())[:8]))
print("  site DSO vs target DSO: "+", ".join(f"{k} {100*v/n:.1f}%" for k,v in samedso.items()))
tot=sum(pairs.values()); cum=0; print(f"top (call site -> miss line) pairs, {len(pairs)} distinct, {tot} samples:")
for (sd,so,td,to_),v in pairs.most_common(20):
    cum+=v; print(f"  {sd:22s} {so:#x} -> {td:22s} {to_:#x}  {100*v/n:5.2f}% (cum {100*cum/n:5.1f}%)")
# coverage curve
cum=0; marks={}
for i,((sd,so,td,to_),v) in enumerate(pairs.most_common()):
    cum+=v
    for t in (25,50,75,90):
        if t not in marks and cum>=t/100*tot: marks[t]=i+1
print("pairs needed for coverage: "+", ".join(f"{t}% -> {marks.get(t,'n/a')}" for t in (25,50,75,90)))
