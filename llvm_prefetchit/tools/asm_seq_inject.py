#!/usr/bin/env python3
"""Exact-spacing sequential-lookahead injection at the assembly level (the machine-level counterpart of the IR seq mode).

Two passes over a clang -S output (AT&T syntax):
  mark   : in the selected functions, add local symbols `pfm_<n>` every MARK_EVERY instructions and at every direct call; assemble
           (caller does it) and read their addresses with nm.
  inject : using the mark addresses, insert `prefetcht1 D(%rip)` at the first mark at or beyond every S bytes of machine code of each
           selected function (constant rip-relative operand: no layout drift), and callee-entry bursts before direct calls
           (`prefetcht1 callee+64*i(%rip)`), optionally only when the callee entry is not already inside the stream window
           [call, call+D) of the caller (--burst-nonadjacent-only), and return-continuation prefetches after calls to listed callees
           (memset/memcpy PLT stubs: `prefetcht1 <retlabel>+64*i(%rip)`).
Functions are selected by --functions-file (mangled names, one per line) and/or --include/--exclude regexes.
Usage:
  asm_seq_inject.py mark   IN.s OUT.s  [--functions-file F] [--include RE] [--exclude RE] [--mark-every N]
  asm_seq_inject.py inject IN.s OUT.s  --marks NM_OUTPUT [--distance 4096] [--spacing 128] [--burst 4] [--burst-nonadjacent-only]
                    [--ret-burst 2 --ret-callees memset,memcpy] [--mnemonic prefetcht1] [same selection options; MARK_EVERY must match]
"""
import sys,re,argparse,bisect,collections
ap=argparse.ArgumentParser(); ap.add_argument('mode',choices=['mark','inject']); ap.add_argument('inp'); ap.add_argument('out')
ap.add_argument('--functions-file'); ap.add_argument('--include',default=''); ap.add_argument('--exclude',default='')
ap.add_argument('--mark-every',type=int,default=4)
ap.add_argument('--mark-include',default=None,help='inject mode: the function selection the MARK pass used (marks are numbered over it). Defaults to the emission selection; set it when the mark pass covered a wider set so that several function subsets can share one marks file.')
ap.add_argument('--marks'); ap.add_argument('--distance',type=int,default=4096); ap.add_argument('--spacing',type=int,default=128)
ap.add_argument('--burst',type=int,default=0); ap.add_argument('--burst-nonadjacent-only',action='store_true')
ap.add_argument('--burst-prev-adjacent',action='store_true',help='skip the burst when the previous direct call of the same caller targets a selected callee laid out within D bytes before this callee (its stream already covered this entry)')
ap.add_argument('--burst-lead',type=int,default=0,help='insert the burst this many instructions before the call (within the block)')
ap.add_argument('--ret-burst',type=int,default=0); ap.add_argument('--ret-callees',default='memset,memcpy,memmove')
ap.add_argument('--mnemonic',default='prefetcht1')
ap.add_argument('--skip-loop-bytes',type=int,default=0,help='with --skip-loops, only skip loop bodies SMALLER than this many bytes. A loop whose body fits in L2 is resident after the first iteration, so prefetching inside it is waste; a loop body larger than the cache evicts itself and still needs the stream.')
ap.add_argument('--skip-loops',action='store_true',help='do not emit stream prefetches inside a loop body (a backward branch target .. the branch). Code in a loop is re-executed, so its lines are resident after the first iteration and a prefetch there fires every iteration for nothing.')
ap.add_argument('--sizes',default=None,help="nm -S output of the marked object: function sizes, for --min-func-bytes")
ap.add_argument('--min-func-bytes',type=int,default=0,help='skip functions smaller than this. The stream prefetches site+D, so in a function shorter than D the target lands in whatever function the linker happened to place next, which is not what executes next.')
ap.add_argument('--no-compensate',action='store_true',help='do not subtract the injected bytes from the spacing step (mark addresses are pre-injection: without compensation the realized spacing is ~7 B larger per prefetch)')
A=ap.parse_args()
listed=set()
if A.functions_file: listed=set(l.strip() for l in open(A.functions_file) if l.strip())
inc=re.compile(A.include) if A.include else None; exc=re.compile(A.exclude) if A.exclude else None
def selected(fn):
    if listed and fn not in listed and not (inc and inc.search(fn)): return False
    if not listed and inc and not inc.search(fn): return False
    if exc and exc.search(fn): return False
    return True
LABEL=re.compile(r'^([A-Za-z_.$][\w.$@]*):'); TYPEF=re.compile(r'^\s*\.type\s+([\w.$@]+),\s*@function'); FEND=re.compile(r'^\.Lfunc_end\d+:')
INSN=re.compile(r'^\t([a-z][\w.]*)\b'); CALL=re.compile(r'^\tcallq?\s+([\w.$@]+)\s*$'); JMPLIKE=re.compile(r'^\t(j[a-z]+|ret|call)')
ret_callees=set(A.ret_callees.split(','))
lines=open(A.inp).read().split('\n')
# function extents
funcs=[]; cur=None; pending_type=set()
for i,l in enumerate(lines):
    m=TYPEF.match(l)
    if m: pending_type.add(m.group(1)); continue
    m=LABEL.match(l)
    if m and m.group(1) in pending_type and cur is None: cur=[m.group(1),i,None]; continue
    if cur and FEND.match(l): cur[2]=i; funcs.append(tuple(cur)); cur=None
sel=[(n,a,b) for n,a,b in funcs if selected(n)]
print(f"functions {len(funcs)}, selected {len(sel)}", file=sys.stderr)
if A.mode=='mark':
    out=[]
    selranges=[(a,b) for _,a,b in sel]; sr=0; k=0; cnt=0
    for i,l in enumerate(lines):
        while sr<len(selranges) and i>selranges[sr][1]: sr+=1
        inside = sr<len(selranges) and selranges[sr][0]<=i<=selranges[sr][1]
        if inside and INSN.match(l):
            if CALL.match(l) or cnt%A.mark_every==0:
                out.append(f"pfm_{k}:"); k+=1
            cnt+=1
        out.append(l)
    open(A.out,'w').write('\n'.join(out)); print(f"marks {k}", file=sys.stderr)
else:
    addr={}
    for l in open(A.marks):
        f=l.split()
        if len(f)==3 and f[2].startswith('pfm_'): addr[int(f[2][4:])]=int(f[0],16)
        elif len(f)==3 and f[1] in 'tTwW': addr.setdefault(('f',f[2]),int(f[0],16))
    fstart={k[1]:v for k,v in addr.items() if isinstance(k,tuple)}
    # marks are numbered over the MARK pass's selection; emission happens only inside the (possibly narrower) emission selection
    if A.mark_include:
        mrx=re.compile(A.mark_include)
        marksel=[(n,a,b) for n,a,b in funcs if mrx.search(n) and not (exc and exc.search(n))]
    else:
        marksel=sel
    sizes={}
    if A.sizes:
        for l in open(A.sizes):
            f=l.split()
            if len(f)==4 and f[2] in 'TtWw':
                try: sizes[f[3]]=int(f[1],16)
                except ValueError: pass
    if A.min_func_bytes and sizes:
        before=len(sel); sel=[t for t in sel if sizes.get(t[0],0)>=A.min_func_bytes]
        print(f"min-func-bytes {A.min_func_bytes}: {len(sel)} of {before} selected functions kept", file=sys.stderr)
    # line -> address, from the mark pass (marks are placed every --mark-every instructions and at every call)
    line_addr={}
    if A.skip_loops and A.skip_loop_bytes:
        mr0=0; k0=0; cnt0=0
        mranges=[(a,b) for _,a,b in (marksel if A.mark_include else sel)]
        for i,l in enumerate(lines):
            while mr0<len(mranges) and i>mranges[mr0][1]: mr0+=1
            if not (mr0<len(mranges) and mranges[mr0][0]<=i<=mranges[mr0][1]): continue
            if not INSN.match(l): continue
            if CALL.match(l) or cnt0%A.mark_every==0:
                if k0 in addr: line_addr[i]=addr[k0]
                k0+=1
            cnt0+=1
    # loop bodies: a jump to a label defined earlier in the same function closes a loop; [label, jump] is inside it
    loop_lines=set()
    if A.skip_loops:
        LAB=re.compile(r'^(\.L\S+):'); JMP=re.compile(r'^\tj[a-z]+\s+(\.L\S+)')
        for n,a,b in sel:
            pos={}
            for i in range(a,b+1):
                m=LAB.match(lines[i])
                if m: pos[m.group(1)]=i
            iv=[]
            for i in range(a,b+1):
                m=JMP.match(lines[i])
                if m:
                    t=pos.get(m.group(1))
                    if t is not None and t<=i: iv.append((t,i))
            for t,i in iv:
                if A.skip_loop_bytes:
                    # byte span of the loop body, from the mark addresses that bracket it
                    lo=[line_addr[x] for x in range(t,i+1) if x in line_addr]
                    if not lo or (max(lo)-min(lo)) >= A.skip_loop_bytes: continue
                loop_lines.update(range(t,i+1))
        print(f"skip-loops: {len(loop_lines)} lines inside loop bodies"+(f" smaller than {A.skip_loop_bytes} B" if A.skip_loop_bytes else ""), file=sys.stderr)
    markranges=[(a,b) for _,a,b in marksel]; mr=0
    selranges=[(a,b,n) for n,a,b in sel]; sr=0; k=0; cnt=0
    out=[]; st=collections.Counter(); next_at=None; fn_cur=None; retn=0; prev_callee=None
    for i,l in enumerate(lines):
        while mr<len(markranges) and i>markranges[mr][1]: mr+=1
        in_mark = mr<len(markranges) and markranges[mr][0]<=i<=markranges[mr][1]
        while sr<len(selranges) and i>selranges[sr][1]: sr+=1
        inside = sr<len(selranges) and selranges[sr][0]<=i<=selranges[sr][1]
        if inside and selranges[sr][2]!=fn_cur:
            fn_cur=selranges[sr][2]; next_at=fstart.get(fn_cur,0)+A.spacing; prev_callee=None
        if in_mark and INSN.match(l):
            m=CALL.match(l); marked = m or cnt%A.mark_every==0
            here=addr.get(k) if marked else None
            if marked: k+=1
            cnt+=1
            if not inside: out.append(l); continue
            if here is not None and here>=next_at and not (A.skip_loops and i in loop_lines):
                out.append(f"\t{A.mnemonic}\t{A.distance}(%rip)"); st['seq']+=1
                next_at=here+(A.spacing if A.no_compensate else max(8,A.spacing-7))
            if m:
                callee=m.group(1); base=callee.split('@')[0]
                if A.burst and callee in fstart and selected(callee):
                    adjacent = here is not None and 0<=fstart[callee]-here<A.distance
                    if A.burst_prev_adjacent and prev_callee in fstart and 0<=fstart[callee]-fstart[prev_callee]<A.distance: adjacent=True
                    if not ((A.burst_nonadjacent_only or A.burst_prev_adjacent) and adjacent):
                        for L in range(A.burst): out.append(f"\t{A.mnemonic}\t{callee}+{64*L}(%rip)")
                        st['burst']+=A.burst
                    else: st['burst_skipped_adjacent']+=1
                    prev_callee=callee
                if A.ret_burst and base in ret_callees:
                    out.append(l); retn+=1
                    out.append(f".Lpfret_{retn}:")
                    for L in range(A.ret_burst): out.append(f"\t{A.mnemonic}\t.Lpfret_{retn}+{64*(L+1)}(%rip)")
                    st['ret']+=A.ret_burst; continue
        out.append(l)
    open(A.out,'w').write('\n'.join(out))
    nmarks=sum(1 for x in addr if not isinstance(x,tuple))
    if k!=nmarks: print(f"WARNING: consumed {k} marks but nm has {nmarks} (mark/inject selection or --mark-every differ)", file=sys.stderr)
    print("injected: "+', '.join(f"{a}={b}" for a,b in sorted(st.items()))+f"; marks {k}", file=sys.stderr)
