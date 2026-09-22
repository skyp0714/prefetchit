#!/usr/bin/env python3
"""Share of L2I code-miss samples by the type of the most recent taken branch (LBR[0]) and whether that branch brought execution onto the
missed line. Input: perf script -F ip,dso,brstack of L2I-miss samples (any perf version that prints the branch type field), plus the
process maps to tell PLT stubs (indirect jmp through the GOT = cross-DSO) from other indirect branches.
Usage: lbr_type_share.py samples_lbr.txt maps.txt [binary]  (binary: PLT ranges via readelf -S)"""
import re,sys,collections,subprocess
raw,maps=sys.argv[1],sys.argv[2]; binaries=sys.argv[3:]   # host copies of the traced executable / DSOs (matched by basename) for PLT detection
segs=[]
for ln in open(maps):
    p=ln.split(None,5)
    if len(p)>=6 and 'x' in p[1]:
        lo,hi=(int(x,16) for x in p[0].split('-')); off=int(p[2],16); name=p[5].strip().replace(' (deleted)','').split('/')[-1]; segs.append((lo,hi,off,name))
def loc(a):
    for lo,hi,off,name in segs:
        if lo<=a<hi: return name, a-lo+off
    return '?',a
plt={}   # basename -> [(section, file-offset lo, hi)]
for b in binaries:
    out=subprocess.run(['readelf','-SW',b],capture_output=True,text=True).stdout; L=[]
    for ln in out.splitlines():
        m=re.search(r'\]\s+(\.plt\S*|\.iplt)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)',ln)
        if m: L.append((m.group(1),int(m.group(3),16),int(m.group(3),16)+int(m.group(4),16)))   # file offsets
    plt[b.split('/')[-1]]=L
def in_plt(a):
    n,o=loc(a)
    return any(lo<=o<hi for _,lo,hi in plt.get(n,[]))
DSO=r'\((?:[^()]|\([^()]*\))*\)'
ENT=re.compile(r'0x([0-9a-f]+) '+DSO+r'/0x([0-9a-f]+) '+DSO+r'/[MPX-]/[^/]*/[^/]*/([0-9-]+)/(\w+)/')
n=0; typ=collections.Counter(); onl=collections.Counter(); ipdso=collections.Counter(); ind_from=collections.Counter(); ind_kind=collections.Counter(); cross=collections.Counter()
for ln in open(raw):
    m=re.match(r'\s*([0-9a-f]+)\s+\(([^)]*)\)\s*(.*)$',ln)
    if not m: continue
    ip=int(m.group(1),16); d0=m.group(2).replace(' (deleted)','').split('/')[-1]; ents=ENT.findall(m.group(3))
    if not ents: continue
    n+=1; ipdso[d0]+=1
    fr,to,cyc,t=ents[0]; fr=int(fr,16); to=int(to,16)
    same_line=(to>>6)==(ip>>6)
    k=t
    if t in ('IND','IND_CALL','IND_JMP'):
        if in_plt(fr): k='PLT(cross-DSO)'
        else: k='IND_CALL(vtable/fptr)' if t=='IND_CALL' else 'IND_JMP(table/tail)'
    typ[k]+=1
    if same_line: onl[k]+=1
    if k.startswith('IND') or k.startswith('PLT'):
        ind_from[(k,)+loc(fr)]+=1
        fn,_=loc(fr); tn,_=loc(to); cross[(k, 'cross-DSO' if fn!=tn else 'same-DSO')]+=1
print(f"samples with LBR: {n}")
print("miss IP by DSO: "+', '.join(f"{d} {100*c/n:.1f}%" for d,c in ipdso.most_common(6)))
print("\nLBR[0] type            share   miss-on-its-target-line")
for k,c in typ.most_common(): print(f"{k:22s} {100*c/n:6.2f}%  {100*onl[k]/max(1,c):6.1f}%")
print("\nindirect/PLT by DSO crossing: "+', '.join(f"{k[0]} {k[1]} {100*c/n:.2f}%" for k,c in cross.most_common()))
print("\ntop indirect/PLT from-sites (type, dso, offset, share):")
for k,c in ind_from.most_common(12): print(f"  {k[0]:22s} {k[1]:24s} {k[2]:#x} {100*c/n:.2f}%")
