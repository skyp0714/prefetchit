#!/usr/bin/env python3
"""Static (profile-free) cost-based prefetch plan — the static counterpart of the trace-guided cold plan.

The trace planner ranks a (site, target) pair by  misses_saved_per_second / site_executions_per_second  and keeps the pairs whose
cost per saved miss is below a threshold. This tool computes the same two quantities from the binary alone:

  freq(f)      relative execution count of a function: block weights from the loop structure recovered from the disassembly
               (LOOPMULT^loop_depth, the static analogue of BlockFrequencyInfo) propagated over the direct call graph from the roots.
  P_evict(g)   probability that g's code has been evicted from L2 since its previous execution. The code executed between two
               consecutive executions of g is  TotalDynamicBytes / freq(g); with an L2 of L bytes that is
               P_evict(g) = min(1, TotalDynamicBytes / (freq(g) * L)) — rare functions have a long reuse distance and miss,
               hot functions stay resident. This is what makes the model a *capacity*-miss model.
  benefit      freq_edge(f->g) * P_evict(g) * lines(g)      (misses actually avoided per unit of program execution)
  cost         freq(f) * lines_emitted                      (prefetch instructions actually executed)
  lead         weighted instructions executed inside f before the call, must be in [--min-lead, --max-lead] (too early = evicted
               again, too late = the fill does not arrive).

Pairs are ranked by benefit/cost and taken greedily until the dynamic prefetch budget is spent (--budget = prefetch executions as a
fraction of all executed instructions), with a per-site cap. The output is the same JSON the pass consumes for PREFETCHIT_COLD_PLAN,
so a static plan and a trace plan differ only in how the pairs were chosen.

usage: static_cost_plan.py BIN OUT.json [options]
"""
import sys,re,json,argparse,bisect,collections,subprocess,math

# an assembler symbol may not contain '-': 'prefetchit.tgt.Python-ast.c.f' parses as 'prefetchit.tgt.Python' MINUS 'ast.c.f'
def _sanitize_sym(x): return re.sub(r'[^A-Za-z0-9_.$]', '_', x)

ap=argparse.ArgumentParser()
ap.add_argument('binary'); ap.add_argument('out')
ap.add_argument('--l2-bytes',type=int,default=2*1024*1024)
ap.add_argument('--loop-mult',type=float,default=10.0,help='weight multiplier per loop nesting level (BFI-like)')
ap.add_argument('--max-loop-depth',type=int,default=3)
ap.add_argument('--scc-mult',type=float,default=10.0,help='recursion multiplier for a strongly connected component of the call graph')
ap.add_argument('--min-lead',type=float,default=60,help='estimated instructions executed in the site before the call')
ap.add_argument('--max-lead',type=float,default=4000)
ap.add_argument('--depth',type=int,default=2,help='call-graph distance from the site to a target (1 = direct callee)')
ap.add_argument('--lines',type=int,default=2,help='lines prefetched per target (the callee entry)')
ap.add_argument('--max-per-site',type=int,default=32)
ap.add_argument('--budget',type=float,default=0.01,help='dynamic prefetch executions / dynamic instructions')
ap.add_argument('--instrumentable',default=None,help='file of function names usable as sites (default: all defined functions)')
ap.add_argument('--global-syms',default=None,help='file of names referenceable by name from another TU (default: nm T/W symbols)')
ap.add_argument('--local-aliases',action='store_true',help='allow local (static) callees as targets via hidden aliases (needs nm -l)')
ap.add_argument('--exclude-sites',default=None)
ap.add_argument('--min-callee-bytes',type=int,default=64)
ap.add_argument('--report',action='store_true')
ap.add_argument('--emit-seq-functions',default=None,help='instead of a site plan, write the function list for the sequential-lookahead stream')
ap.add_argument('--min-pevict',type=float,default=0.5); ap.add_argument('--seq-min-bytes',type=int,default=256)
ap.add_argument('--seq-top',type=int,default=0); ap.add_argument('--seq-spacing',type=float,default=128.0)
ap.add_argument('--seq-rank',choices=['reach','exec','miss'],default='reach',help="reach = every function reachable from the roots, largest first (measured best: the magnitude of a static call-graph frequency estimate is not usable - multiplying loop weights along call chains spreads it over 18 orders of magnitude and ranks a small leaf in a deep loop above the 7.8 MB straight-line function that holds 69% of the misses); exec = rank by freq*size; miss = rank by freq*lines*P_evict (selects rarely-executed code: wrong for a stream)")
ap.add_argument('--max-static-frac',type=float,default=0.05,help='cap on the static code growth of the stream: injected bytes / text bytes. A function that never executes costs nothing dynamically but still enlarges the working set.')
ap.add_argument('--roots',default='auto',help="auto = every function never reached by a direct call (indirect-call-heavy code needs this), main = only main (tighter, but code reached only indirectly gets frequency 0), or a regex")
A=ap.parse_args()

# ---------- disassembly: streamed, one function at a time (binaries here reach 100 MB of text) ----------
HDR=re.compile(r'^([0-9a-f]+) <([^>]+)>:')
INS=re.compile(r'^\s*([0-9a-f]+):\s+([a-z][\w.]*)\s*(.*)$')
TGT=re.compile(r'^([0-9a-f]+)\s+<([^>+]+)(\+0x[0-9a-f]+)?>')
JCC=re.compile(r'^j')
sizes={}; SELF={}; NINS={}; CALLS=collections.defaultdict(list)

def finish(fn, start, ins):
    """aggregate one function: size, weighted instruction count, call edges with a lead estimate"""
    if not fn or not ins: return
    end=ins[-1][0]+1; sizes[fn]=end-start; NINS[fn]=len(ins)
    leaders={start}; back=[]
    for i,(a,mn,ops) in enumerate(ins):
        if JCC.match(mn) or mn.startswith('call') or mn.startswith('ret'):
            if i+1<len(ins): leaders.add(ins[i+1][0])
            if JCC.match(mn):
                m=TGT.match(ops.strip())
                if m:
                    t=int(m.group(1),16)
                    if start<=t<end:
                        leaders.add(t)
                        if t<=a: back.append((t,a))
    L=sorted(leaders)
    delta=[0]*(len(L)+1)                   # difference array: a function can have 10^5 backedges over 10^5 blocks
    for t,a in back:                       # blocks between a backedge target and the branch are one level deeper
        lo=bisect.bisect_left(L,t); hi=bisect.bisect_right(L,a)
        delta[lo]+=1; delta[hi]-=1
    depth=[0]*len(L); run=0
    for i in range(len(L)): run+=delta[i]; depth[i]=run
    wb=[A.loop_mult**min(d,A.max_loop_depth) for d in depth]
    cnt=[0]*len(L)
    for a,mn,ops in ins: cnt[bisect.bisect_right(L,a)-1]+=1
    SELF[fn]=sum(w*c for w,c in zip(wb,cnt))
    pref=[0.0]*len(L); acc=0.0
    for i in range(len(L)): pref[i]=acc; acc+=wb[i]*cnt[i]
    for a,mn,ops in ins:
        if not mn.startswith('call'): continue
        m=TGT.match(ops.strip())
        if not m: continue
        i=bisect.bisect_right(L,a)-1
        CALLS[fn].append((m.group(2).split('@')[0], wb[i], pref[i]))

proc=subprocess.Popen(['objdump','-d','--no-show-raw-insn',A.binary],stdout=subprocess.PIPE,text=True,bufsize=1<<20)
fn=None; start=0; ins=[]
for l in proc.stdout:
    m=HDR.match(l)
    if m:
        finish(fn,start,ins); fn=m.group(2); start=int(m.group(1),16); ins=[]; continue
    if fn is None: continue
    m=INS.match(l)
    if m: ins.append((int(m.group(1),16),m.group(2),m.group(3)))
finish(fn,start,ins); proc.stdout.close(); proc.wait()
funcs=sizes
called={g for f in CALLS for g,_,_ in CALLS[f]}
if A.roots=='auto': roots=[f for f in funcs if f not in called]+(['main'] if 'main' in funcs else [])
elif A.roots=='main': roots=[f for f in ('main','_start') if f in funcs] or [f for f in funcs if f not in called]
else:
    rx=re.compile(A.roots); roots=[f for f in funcs if rx.search(f)] or [f for f in funcs if f not in called]
roots=set(roots)

# Static frequency over a cyclic call graph: condense the strongly connected components (recursion, mutual recursion through an
# interpreter loop) and propagate in topological order, giving each non-trivial component one bounded recursion multiplier. Plain
# relaxation diverges here — every cycle multiplies by the call-site weight on each iteration.
adj=collections.defaultdict(set)
for f,es in CALLS.items():
    for g,_,_ in es:
        if g in funcs and g!=f: adj[f].add(g)
index={}; low={}; onstk={}; stack=[]; comp={}; ncomp=0
for start in funcs:                     # iterative Tarjan (recursion depth would blow the Python stack)
    if start in index: continue
    work=[(start,iter(adj.get(start,())))]; index[start]=low[start]=len(index); stack.append(start); onstk[start]=True
    while work:
        v,it=work[-1]; advanced=False
        for w in it:
            if w not in index:
                index[w]=low[w]=len(index); stack.append(w); onstk[w]=True
                work.append((w,iter(adj.get(w,())))); advanced=True; break
            elif onstk.get(w): low[v]=min(low[v],index[w])
        if advanced: continue
        work.pop()
        if low[v]==index[v]:
            while True:
                w=stack.pop(); onstk[w]=False; comp[w]=ncomp
                if w==v: break
            ncomp+=1
        if work: low[work[-1][0]]=min(low[work[-1][0]],low[v])
members=collections.defaultdict(list)
for f,c in comp.items(): members[c].append(f)
cedge=collections.defaultdict(float); cin=collections.defaultdict(set)
for f,es in CALLS.items():
    cf=comp.get(f)
    for g,w,_ in es:
        cg=comp.get(g)
        if cg is None or cf is None or cf==cg: continue
        cedge[(cf,cg)]+=w; cin[cg].add(cf)
order=sorted(members, key=lambda c: -min(index[f] for f in members[c]))   # Tarjan emits reverse topological order
# Propagate in log space: a call inside a nested loop carries a weight of up to loop_mult^depth and the products along a call chain
# overflow any linear accumulator. Frequencies are then normalised so that the hottest function is 1, i.e. every quantity below is
# "per execution of the hottest code", which is the scale at which the L2 capacity argument is made.
NEG=float('-inf')
def lse(a,b):
    if a==NEG: return b
    if b==NEG: return a
    m=max(a,b); return m+math.log(math.exp(a-m)+math.exp(b-m))
lc=collections.defaultdict(lambda: NEG)
for c in order:
    v=NEG
    nroot=sum(1 for f in members[c] if f in roots)
    if nroot: v=math.log(nroot)
    for src in cin.get(c,()):
        w=cedge[(src,c)]
        if w>0 and lc[src]!=NEG: v=lse(v, lc[src]+math.log(w))
    if v!=NEG and len(members[c])>1: v+=math.log(A.scc_mult)
    lc[c]=v
lmax=max([v for v in lc.values() if v!=NEG] or [0.0])
freq=collections.defaultdict(float)
for c,ms in members.items():
    fv=math.exp(min(0.0, lc[c]-lmax)) if lc[c]!=NEG else 0.0
    for f in ms: freq[f]=fv
TOTB=sum(freq[f]*sizes.get(f,0) for f in freq)
TOTI=sum(freq[f]*SELF.get(f,0) for f in freq)
def p_evict(g):
    fr=freq.get(g,0.0)
    if fr<=0: return 1.0
    return min(1.0, TOTB/(fr*A.l2_bytes))

# ---------- stream (sequential-lookahead) function selection ----------
# For a stream the cost is one prefetch per S bytes of code executed and the benefit is the misses of that code, so
# benefit/cost = P_evict(f) * S: the efficiency of streaming a function depends only on its eviction probability.
# Ranking functions by expected misses (freq * lines * P_evict) and cutting at a P_evict threshold gives the static
# counterpart of "inject the stream only where the trace shows misses".
if A.emit_seq_functions:
    TEXT=sum(sizes.values())
    rows=[]
    for f in funcs:
        if sizes[f] < A.seq_min_bytes: continue
        fr=freq.get(f,0.0)
        if fr<=0: continue
        pe=p_evict(f); exp_miss=fr*(sizes[f]/64.0)*pe; exec_bytes=fr*sizes[f]
        if A.seq_rank=='miss' and pe<A.min_pevict: continue
        key = sizes[f] if A.seq_rank=='reach' else (exec_bytes if A.seq_rank=='exec' else exp_miss)
        rows.append((key, exp_miss, exec_bytes, pe, f))
    rows.sort(reverse=True)
    tot_miss=sum(freq.get(f,0.0)*(sizes[f]/64.0)*p_evict(f) for f in funcs)
    tot_exec=sum(freq.get(f,0.0)*sizes[f] for f in funcs)
    # static-size budget: injecting into code that never runs is free in the dynamic model but enlarges the text
    keep=[]; added=0.0
    for r in rows:
        b=sizes[r[4]]/A.seq_spacing*7.0
        if (added+b)/max(1.0,TEXT) > A.max_static_frac: continue
        keep.append(r); added+=b
        if A.seq_top and len(keep)>=A.seq_top: break
    with open(A.emit_seq_functions,'w') as fh:
        fh.write(f"# static cost selection (rank={A.seq_rank}): {len(keep)} of {len(funcs)} functions, "
                 f"{100*sum(r[1] for r in keep)/max(1e-30,tot_miss):.1f}% of expected misses, "
                 f"{100*sum(r[2] for r in keep)/max(1e-30,tot_exec):.1f}% of executed bytes, "
                 f"+{added/max(1.0,TEXT):.2%} text\n")
        for r in keep: fh.write(r[4]+"\n")
    print(f"seq selection ({A.seq_rank}): {len(keep)} of {len(funcs)} functions; covers {100*sum(r[2] for r in keep)/max(1e-30,tot_exec):.1f}% of executed bytes "
          f"and {100*sum(r[1] for r in keep)/max(1e-30,tot_miss):.1f}% of expected misses; static growth +{added/max(1.0,TEXT):.2%} of text, "
          f"estimated dynamic prefetches {sum(r[2] for r in keep)/A.seq_spacing:.3g} ({sum(r[2] for r in keep)/A.seq_spacing/max(1,TOTI):.2%} of executed instructions)")
    print("  top: "+", ".join(f"{r[4][:36]}(P={r[3]:.2f})" for r in keep[:5]))
    sys.exit(0)

# ---------- symbol classes ----------
def nm(args):
    return subprocess.run(['nm']+args+[A.binary],capture_output=True,text=True).stdout.splitlines()
glob=set(); local=set()
for l in nm(['--defined-only']):
    p=l.split()
    if len(p)==3 and p[1] in 'TtWw': (glob if p[1] in 'TW' else local).add(p[2])
if A.global_syms:
    glob |= set(x.strip() for x in open(A.global_syms) if x.strip()) & set(funcs)
localfile=collections.defaultdict(set)
if A.local_aliases:
    for l in nm(['-l','--defined-only']):
        p=l.split()
        if len(p)>=4 and p[1] in 'tw' and ':' in p[3]: localfile[p[2]].add(p[3].split(':')[0].rsplit('/',1)[-1])
ambiguous={n for n,fs in localfile.items() if len(fs)>1 or n in glob}
instr=set(x.strip() for x in open(A.instrumentable) if x.strip()) if A.instrumentable else set(funcs)
if A.exclude_sites: instr-=set(x.strip() for x in open(A.exclude_sites) if x.strip())
aliases={}
def target_name(g):
    if g in glob: return g
    if A.local_aliases and g in localfile and g not in ambiguous:
        (fb,)=tuple(localfile[g]); a=_sanitize_sym(f"prefetchit.tgt.{fb}.{g}"); aliases[a]={"file":fb,"fn":g}; return a
    return None

# ---------- candidate pairs ----------
pairs=[]; stat=collections.Counter()
for f in funcs:
    if f not in instr or f in ambiguous: stat['site not instrumentable']+=1; continue
    if freq.get(f,0)<=0: stat['site unreachable']+=1; continue
    seen={f}
    frontier=[(g,w,lead) for g,w,lead in CALLS.get(f,())]
    for d in range(1,A.depth+1):
        nxt=[]
        for g,w,lead in frontier:
            if g in seen or g not in funcs: continue
            seen.add(g)
            if sizes.get(g,0)>=A.min_callee_bytes and A.min_lead<=lead<=A.max_lead:
                tn=target_name(g)
                if tn is None: stat['target not referenceable']+=1
                else:
                    pe=p_evict(g); nl=min(A.lines, max(1,sizes[g]//64))
                    benefit=freq[f]*w*pe*nl            # misses avoided per unit of program execution
                    cost=freq[f]*nl                    # prefetch instructions executed
                    if benefit>0: pairs.append((benefit/cost, benefit, cost, f, tn, g, nl, pe, lead))
            else: stat['lead or size out of range']+=1
            for g2,w2,lead2 in CALLS.get(g,()):        # deeper: lead accumulates the callee's own prefix
                nxt.append((g2,w*w2,lead+SELF.get(g,0)*0.5+lead2))
        frontier=nxt
pairs.sort(key=lambda t:-t[0])
budget=A.budget*max(1.0,TOTI); used=0.0; per_site=collections.Counter(); sites=collections.defaultdict(list); taken=0
for score,ben,cost,f,tn,g,nl,pe,lead in pairs:
    if used+cost>budget: continue
    if per_site[f]>=A.max_per_site: continue
    sites[f].append((tn,nl,g)); per_site[f]+=1; used+=cost; taken+=1
# ---------- emit ----------
out={"sites":{}}; ntargets=0
for f,ts in sites.items():
    tl=[]
    for tn,nl,g in ts:
        for i in range(nl): tl.append([tn,64*i,0]); ntargets+=1
    k=(7*len(tl)+15)//16*16
    e={"k":k,"t":tl}
    if A.local_aliases and f in localfile and f not in glob: e["file"]=next(iter(localfile[f]))
    out["sites"][f]=e
if aliases: out["aliases"]={a:v for a,v in aliases.items() if any(t[0]==a for s in out["sites"].values() for t in s["t"])}
json.dump(out,open(A.out,'w'))
# What the model predicts before anything is built: the misses this plan avoids as a fraction of all the misses the model expects.
# A target line can only miss once per execution of its function, so the per-target benefit is capped at freq(g)*P_evict(g)*lines and
# several sites prefetching the same line do not add up. This is the static answer to "is there headroom here at all".
TOTMISS=sum(freq.get(f,0.0)*(sizes[f]/64.0)*p_evict(f) for f in funcs)
by_t=collections.defaultdict(float); cap={}
chosen={(f,tn) for f,ts in sites.items() for tn,nl,g in ts}
for score,ben,cost,f,tn,g,nl,pe,lead in pairs:
    if (f,tn) not in chosen: continue
    by_t[g]+=ben; cap[g]=freq.get(g,0.0)*pe*min(nl, max(1,sizes.get(g,64)//64))
gained=sum(min(v,cap.get(g,v)) for g,v in by_t.items())
print(f"static cost plan: {len(out['sites'])} sites, {ntargets} targets, {len(out.get('aliases',{}))} aliases; "
      f"budget {A.budget:.3%} of {TOTI:.3g} weighted insns → used {used:.3g} ({used/max(1,TOTI):.3%}); candidate pairs {len(pairs)}, taken {taken}")
print(f"  PREDICTION: avoids {gained:.4g} of {TOTMISS:.4g} expected misses = {100*gained/max(1e-30,TOTMISS):.2f}%; "
      f"cost {used/max(1,TOTI):.3%} of executed instructions, {used/max(1e-30,gained):.1f} prefetch executions per avoided miss")
print(f"  functions {len(funcs)}, roots {len(set(roots))}, reachable {sum(1 for f in freq if freq[f]>0)}, code bytes/exec {TOTB:.3g}, L2 {A.l2_bytes}")
if A.report:
    top=pairs[:10]
    for s,b,c,f,tn,g,nl,pe,lead in top: print(f"  {f[:44]:44s} -> {g[:34]:34s} score={s:.3g} P_evict={pe:.2f} lead={lead:.0f} freq_site={freq[f]:.3g} freq_t={freq.get(g,0):.3g}")
    for k,v in stat.most_common(5): print(f"  skip: {k} {v}")
