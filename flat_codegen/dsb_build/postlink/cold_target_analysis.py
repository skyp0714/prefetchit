#!/usr/bin/env python3
"""Compare the cold-path pass's static prefetch targets with the L2I-miss lines seen in a trace of the same layout.
usage: cold_target_analysis.py EXE TWIN_TRACE_DIR [PF_TRACE_DIR] [--own-cap 16]
  EXE            binary with the prefetches (its NOP twin has the identical layout)
  TWIN_TRACE_DIR cold_trace_funcs.sh output for the twin (baseline misses in this layout): samples.txt + maps.txt
  PF_TRACE_DIR   same for the prefetch binary (residual misses)"""
import sys,re,bisect,collections,subprocess
exe=sys.argv[1]; twin=sys.argv[2]; pf=sys.argv[3] if len(sys.argv)>3 and not sys.argv[3].startswith('--') else None
def base_of(d):
    for l in open(f"{d}/maps.txt"):
        f=l.split()
        if len(f)>=6 and f[5].endswith('/custom/UserTimelineService') and f[2]=='00000000': return int(f[0].split('-')[0],16)
def misses(d):
    b=base_of(d); c=collections.Counter(); tot=0
    for l in open(f"{d}/samples.txt"):
        f=l.split()
        if len(f)<2: continue
        tot+=1
        if f[1].strip('()').endswith('/custom/UserTimelineService'): c[(int(f[0],16)-b)>>6]+=1
    return c,tot
syms=[]
for l in subprocess.run(['nm','--defined-only',exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw': syms.append((int(f[0],16),f[2]))
syms.sort(); addrs=[a for a,_ in syms]
def func_of(addr):
    i=bisect.bisect_right(addrs,addr)-1
    return syms[i] if i>=0 else (0,'?')
# static prefetch sites and targets
sites=[]; got_sites=0
rx=re.compile(r'^\s*([0-9a-f]+):\s+prefetcht1\s+(?:0x)?([0-9a-f]+)?\(%rip\)\s+#\s*([0-9a-f]+)')
for l in subprocess.run(['objdump','-d','--no-show-raw-insn',exe],capture_output=True,text=True).stdout.splitlines():
    if 'prefetcht1' not in l: continue
    m=rx.match(l)
    if m: sites.append((int(m.group(1),16),int(m.group(3),16)))
    elif '%r11' in l: got_sites+=1
T=collections.defaultdict(list)          # target line -> list of site addrs
own_by_func=collections.defaultdict(set)  # function start -> set of own-line targets (site and target in same function)
entry_targets=set(); interior_targets=set()
for s,t in sites:
    T[t>>6].append(s)
    fs=func_of(s); ft=func_of(t)
    if fs[0]==ft[0]: own_by_func[fs[0]].add(t>>6)
    elif t==ft[0]: entry_targets.add(ft[0])
    else: interior_targets.add(t>>6)
instrumented={func_of(s)[0] for s,_ in sites}
print(f"static: rip-relative prefetch sites={len(sites)} (distinct target lines={len(T)}), GOT-form sites={got_sites}, instrumented functions={len(instrumented)}, callee-entry targets={len(entry_targets)}")
Mt,tot_t=misses(twin)
exe_t=sum(Mt.values()); print(f"twin trace: samples={tot_t}, exe={exe_t} ({100*exe_t/max(1,tot_t):.1f}%), distinct exe miss lines={len(Mt)}")
covered=sum(n for ln,n in Mt.items() if ln in T)
print(f"twin misses on lines the pass targets: {100*covered/max(1,exe_t):.1f}% of exe misses ({sum(1 for ln in Mt if ln in T)} lines)")
cat=collections.Counter(); catl=collections.Counter(); examples=collections.defaultdict(collections.Counter)
for ln,n in Mt.items():
    if ln in T: k='covered'
    else:
        a=ln<<6; f=func_of(a); fstart=f[0]; fline=fstart>>6
        if fstart not in instrumented and fstart not in entry_targets: k='function not instrumented (no site, no entry target)'
        elif ln==fline and fstart not in entry_targets and fstart in instrumented: k='entry line, no caller prefetches it (indirect/virtual or loop-only call)'
        elif fstart in own_by_func and ln>max(own_by_func[fstart]): k='beyond own-lines cap'
        elif fstart in entry_targets and fstart not in instrumented: k='callee interior (only entry targeted; callee too small to self-prefetch)'
        elif fstart in instrumented and ln>fline and (fstart not in own_by_func): k='instrumented function with no own-lines (size estimate too small)'
        else: k='other'
    cat[k]+=n; catl[k]+=1; examples[k][f"{func_of(ln<<6)[1][:60]}+{(ln<<6)-func_of(ln<<6)[0]:#x}"]+=n
print("\nuncovered twin misses by cause (share of exe misses, distinct lines):")
for k,n in cat.most_common(): print(f"  {100*n/max(1,exe_t):5.1f}%  {catl[k]:5d} lines  {k}")
for k in cat:
    if k!='covered': print(f"    e.g. {k[:40]}: "+'; '.join(f"{e} ({100*c/exe_t:.1f}%)" for e,c in examples[k].most_common(4)))
# waste: targets whose line never misses in the twin
never=[ln for ln in T if ln not in Mt]; nsites=sum(len(T[ln]) for ln in never)
print(f"\nwaste: {len(never)}/{len(T)} target lines ({nsites}/{len(sites)} sites) never miss in the twin trace")
if pf:
    Mp,tot_p=misses(pf); exe_p=sum(Mp.values())
    print(f"\nprefetch-binary trace: samples={tot_p}, exe={exe_p} ({100*exe_p/max(1,tot_p):.1f}%), distinct exe miss lines={len(Mp)}")
    still=sum(n for ln,n in Mp.items() if ln in T); print(f"residual misses on targeted lines: {100*still/max(1,exe_p):.1f}% of exe misses (prefetched too late / evicted / dropped)")
    top=collections.Counter()
    for ln,n in Mp.items():
        if ln in T: top[f"{func_of(ln<<6)[1][:60]}+{(ln<<6)-func_of(ln<<6)[0]:#x}"]+=n
    print("  top residual targeted lines: "+'; '.join(f"{e} ({100*c/exe_p:.1f}%)" for e,c in top.most_common(6)))
