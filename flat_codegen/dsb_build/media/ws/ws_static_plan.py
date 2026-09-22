#!/usr/bin/env python3
"""ws_static_plan.py — trace-free ("static") wake-stream plan from the binary alone. The expected execution order is approximated by a
depth-first walk of the DIRECT call graph from the request roots (thrift process_<Method> functions and the handler's std::async lambdas),
visiting callees in address order at their first call and taking each function's first `--fn-lines` lines as its footprint. Sites = functions
in that order (instrumentable, non-tiny); each site prefetches the next k lines that lie d..dmax lines ahead in the static order, exactly as
the trace-guided planner does with the first-touch order. PLT calls become GOT-form targets on the library function's entry lines.

Usage: ws_static_plan.py BIN OUT.json --instrumentable F --pic-sites F --symfs SYMFS [--roots regex] [--d 16 --dmax 48 --k 8 --fn-lines 6]
"""
import argparse, bisect, collections, glob, json, os, re, subprocess

def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('bin'); ap.add_argument('out'); ap.add_argument('--instrumentable', required=True); ap.add_argument('--pic-sites')
    ap.add_argument('--symfs', required=True); ap.add_argument('--roots', default=r'Processor::process_|_Async_state_impl.*_M_run|_Function_handler.*_Async_state')
    ap.add_argument('--d', type=int, default=16); ap.add_argument('--dmax', type=int, default=48); ap.add_argument('--k', type=int, default=8)
    ap.add_argument('--fn-lines', type=int, default=6); ap.add_argument('--max-depth', type=int, default=12); ap.add_argument('--max-lines', type=int, default=3000)
    ap.add_argument('--kmerge', type=int, default=12)
    A = ap.parse_args()
    instr = set(open(A.instrumentable).read().split()); pic = set(open(A.pic_sites).read().split()) if A.pic_sites else set()
    # symbols (mangled) with sizes, demangled names for root matching, globals for anchors
    syms = []; glob_syms = []; dem = {}
    for l in sh(f"nm -nS --defined-only {A.bin}").splitlines():
        p = l.split()
        if len(p) == 4 and p[2] in 'TtWwV': syms.append((int(p[0], 16), int(p[1], 16), p[2], p[3])); (glob_syms.append((int(p[0], 16), p[3])) if p[2] == 'T' else None)
    for l in sh(f"nm -nS --defined-only -C {A.bin}").splitlines():
        p = l.split(None, 3)
        if len(p) == 4 and p[2] in 'TtWwV': dem[int(p[0], 16)] = p[3]
    syms.sort(); sa = [s[0] for s in syms]; ga = [g[0] for g in glob_syms]
    byname = {}
    for a, s, t, n in syms: byname.setdefault(n, (a, s))
    # direct call graph from the disassembly, callees in address order per function
    calls = collections.defaultdict(list); cur = None
    for l in sh(f"objdump -d --no-show-raw-insn {A.bin}").splitlines():
        m = re.match(r"^([0-9a-f]+) <([^>]+)>:$", l)
        if m: cur = m.group(2); continue
        if cur is None: continue
        m = re.match(r"^\s+([0-9a-f]+):\s+call\S*\s+([0-9a-f]+) <([^>+@]+)(@plt)?>", l)
        if m: calls[cur].append((int(m.group(1), 16), m.group(3), bool(m.group(4))))
    # library exports for PLT targets (GOT form): default-version, non-IFUNC
    libs = {}
    for f in glob.glob(A.symfs + '/usr/lib/x86_64-linux-gnu/*.so*'):
        for l in sh(f"nm -D -nS --defined-only {f} 2>/dev/null").splitlines():
            p = l.split()
            if len(p) == 4 and p[2] in 'TW' and '@@' in p[3] or len(p) == 4 and p[2] in 'TW' and '@' not in p[3]:
                n = p[3].split('@')[0]
                libs.setdefault(n, (os.path.basename(f), int(p[0], 16)))
    roots = [n for a, s, t, n in syms if re.search(A.roots, dem.get(a, '')) and '.cold' not in n]
    print(f"roots: {len(roots)}");
    for r in roots[:8]: print("   ", dem.get(byname[r][0], r)[:90])
    # DFS: static "first-touch" order of (dso, line); sites = instrumentable functions at their first visit
    order = []; seen_lines = set(); visited = set(); sites = []   # order entries: dict(dso, line, anchor, off, got, fn)
    def anchor_exe(va):
        i = bisect.bisect_right(ga, va) - 1
        return (glob_syms[i][1], va - glob_syms[i][0]) if i >= 0 and va - glob_syms[i][0] < (1 << 22) else None
    def add_fn_lines(fn, a, s):
        n = max(1, min(A.fn_lines, (s + 63) // 64 if s else 1))
        for i in range(n):
            line = (a & ~63) + 64 * i
            if ('exe', line) in seen_lines: continue
            seen_lines.add(('exe', line)); an = anchor_exe(line)
            if an: order.append(dict(dso='exe', line=line, anchor=an[0], off=an[1], got=0, fn=fn))
    def visit(fn, depth):
        if fn in visited or fn not in byname or depth > A.max_depth or len(order) > A.max_lines: return
        visited.add(fn); a, s = byname[fn]
        if fn in instr and s >= 32 and '.cold' not in fn: sites.append((len(order), fn, a))
        add_fn_lines(fn, a, s)
        for caddr, callee, plt in calls.get(fn, []):
            if plt:
                if callee in libs:
                    dso, va = libs[callee]
                    for i in range(2):
                        key = (dso, (va & ~63) + 64 * i)
                        if key in seen_lines: continue
                        seen_lines.add(key); order.append(dict(dso=dso, line=key[1], anchor=callee, off=key[1] - va, got=1, fn=None))
            else:
                visit(callee, depth + 1)
    for r in roots: visit(r, 0)
    print(f"static order: {len(order)} lines ({sum(1 for o in order if o['got'])} library), sites {len(sites)}, visited functions {len(visited)}")
    # assignment (same greedy as the trace-guided planner)
    n = len(order); assigned = [False] * n; c = 0; plan = collections.defaultdict(list); entry = {}
    for si, (i, fn, a) in enumerate(sites):
        start = max(c, i + A.d); end = min(n, i + A.dmax); take = []; j = start
        while j < end and len(take) < A.k:
            if not assigned[j]: take.append(j); assigned[j] = True
            j += 1
        if not take: continue
        c = max(c, take[-1] + 1); entry[fn] = a
        for j in take: plan[fn].append(order[j])
    def burst_bytes(tl, pic_module):
        direct = 0 if pic_module else sum(1 for t in tl if not t['got']) * 7
        groups = collections.defaultdict(list)
        for t in tl:
            if t['got'] or pic_module: groups[t['anchor']].append(t['off'])
        b = direct + sum(7 + sum(4 if o == 0 else 5 if -128 <= o < 128 else 8 for o in offs) for offs in groups.values())
        return ((b + 15) // 16) * 16 if b else 0
    K = {fn: burst_bytes(tl[:A.kmerge], fn in pic) for fn, tl in plan.items()}
    ins = sorted((entry[fn] + 16, K[fn]) for fn in plan); ins_a = [x[0] for x in ins]; pref = [0]
    for _, k in ins: pref.append(pref[-1] + k)
    def shift(anchor_name, line):
        av = byname.get(anchor_name, (None,))[0]
        if av is None: return 0
        lo = bisect.bisect_right(ins_a, av); hi = bisect.bisect_right(ins_a, line)
        return pref[hi] - pref[lo] if hi > lo else 0
    out = {"sites": {}}
    for fn, tl in plan.items():
        t = [[x['anchor'], x['off'] + (shift(x['anchor'], x['line']) if not x['got'] else 0), x['got']] for x in tl[:A.kmerge]]
        out["sites"][fn] = {"k": K[fn], "t": t}
    json.dump(out, open(A.out, 'w'), indent=0)
    cov = sum(assigned) / n if n else 0
    print(f"plan: {len(out['sites'])} sites, {sum(len(v['t']) for v in out['sites'].values())} targets ({sum(1 for v in out['sites'].values() for x in v['t'] if x[2])} GOT), covers {100*cov:.0f}% of the static order; written {A.out}")

if __name__ == '__main__':
    main()
