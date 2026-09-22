#!/usr/bin/env python3
"""ws_plan_pass.py — dense wake-stream plan for the PrefetchIT pass (PREFETCHIT_COLD_PLAN): sites = exe function entries that lie on a
run type's first-touch path and execute ~once per run; each site prefetches the next unassigned lines that lie d..Dmax lines ahead
in that run type's consensus first-touch order (k per site). Targets: exe lines as global-symbol+offset (pc-relative), shared-library
lines as exported-symbol+offset via the GOT (got=1). Offsets are corrected for the bursts the pass inserts (k bytes at each site entry,
16 B multiples) between the anchor symbol and the line.

Usage: ws_plan_pass.py RUNS_DIR TRACE_DIR --symfs SYMFS --exe /custom/MovieIdService OUT.json [--d 8] [--dmax 24] [--k 6]
       [--p-min 0.5] [--site-p 0.8] [--max-calls 1.5] [--types 'UploadMovieId__m*,none__m*']
"""
import argparse, bisect, collections, fnmatch, glob, json, os, re, statistics, subprocess, sys

def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout

class Syms:
    """mangled symbol tables of one ELF: all function symbols (for site keys) and global/exported ones (for anchors)."""
    def __init__(self, path, dynamic=False):
        self.all = []; self.glob = []
        for l in sh(f"nm {'-D' if dynamic else ''} -nS --defined-only {path} 2>/dev/null").splitlines():
            p = l.split()
            if len(p) == 4 and p[2] in 'TtWwVvi': a, s, t, n = int(p[0], 16), int(p[1], 16), p[2], p[3]
            elif len(p) == 3 and p[1] in 'TtWwVvi': a, s, t, n = int(p[0], 16), 0, p[1], p[2]
            else: continue
            if 'GLIBC_PRIVATE' in n or ('@' in n and '@@' not in n): continue   # private or compat (non-default) version: not linkable by name
            n = n.split('@')[0]
            if '.cold' in n or n.startswith('.L'): continue
            self.all.append((a, s, t, n))
            if (t == 'T') or (dynamic and t in 'TW'): self.glob.append((a, s, t, n))   # exe: strong globals only (COMDAT/weak instantiations may not exist in the next link); DSO exports: T or W
        self.all.sort(); self.glob.sort(); self.aa = [x[0] for x in self.all]; self.ga = [x[0] for x in self.glob]
    def func_at_line(self, line):
        """a function whose entry lies inside this 64 B line (first such), or None."""
        i = bisect.bisect_left(self.aa, line)
        while i < len(self.all) and self.all[i][0] < line + 64:
            a, s, t, n = self.all[i]
            if s >= 16 or t in 'TtWw': return self.all[i]
            i += 1
        return None
    def anchor(self, va, maxoff=1 << 22):
        i = bisect.bisect_right(self.ga, va) - 1
        if i < 0: return None
        a, s, t, n = self.glob[i]
        return (n, va - a, a) if va - a <= maxoff else None

def load_list(path):
    rows = []
    for l in open(path):
        if l.startswith('#'): continue
        p = l.rstrip('\n').split('\t')
        if len(p) >= 7: rows.append(dict(p=float(p[1]), idx=float(p[2]), us=float(p[3]), dso=p[4], line=int(p[5], 16), sym=p[6], pseq=float(p[7]) if len(p) > 7 else 0.0))
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('runs'); ap.add_argument('trace'); ap.add_argument('out'); ap.add_argument('--symfs', required=True)
    ap.add_argument('--exe', default='/custom/MovieIdService'); ap.add_argument('--d', type=int, default=8); ap.add_argument('--dmax', type=int, default=24)
    ap.add_argument('--k', type=int, default=6); ap.add_argument('--kmerge', type=int, default=12); ap.add_argument('--p-min', type=float, default=0.5)
    ap.add_argument('--site-p', type=float, default=0.8); ap.add_argument('--max-calls', type=float, default=1.5); ap.add_argument('--types', default='*')
    ap.add_argument('--no-lib', action='store_true', help='exe targets only (no GOT-form library lines)')
    ap.add_argument('--pair', action='store_true', help='one prefetch per 128 B pair (L2 adjacent-line prefetcher brings the other half)')
    ap.add_argument('--seq-skip', type=float, default=0, help='skip lines entered by fall-through in >= this share of runs (HW next-line territory)')
    ap.add_argument('--gap-k', type=int, default=0, help='allow up to this many targets at a site when no eligible site follows within dmax')
    ap.add_argument('--shadow', action='store_true', help='also prefetch the lines fetched by fall-through after taken branches but never executed (list_*__shadow.tsv)')
    ap.add_argument('--page-touch', type=int, default=0, help='per site, first take up to this many first-lines-of-new-pages within page-dmax (ITLB warm-up)')
    ap.add_argument('--page-dmax', type=int, default=64)
    ap.add_argument('--post-call', type=int, default=0, help='add a burst right after the call the run resumes from (entry_<type>.tsv), issuing this many run-start lines')
    ap.add_argument('--pic-sites', help='file of mangled names compiled as PIC (static archives): their bursts use the GOT form for every target, so k must be sized accordingly')
    ap.add_argument('--instrumentable', help='file of mangled names the pass can instrument (nm of the service objects); other functions are never sites')
    A = ap.parse_args()
    instr = set(open(A.instrumentable).read().split()) if A.instrumentable else None
    pic = set(open(A.pic_sites).read().split()) if A.pic_sites else set()
    exe = Syms(A.symfs + A.exe); exe_name = os.path.basename(A.exe)
    libs = {}
    for f in glob.glob(A.symfs + '/usr/lib/x86_64-linux-gnu/*.so*'):
        libs[os.path.basename(f)] = Syms(f, dynamic=True)
    # ---- run counts per type and per request (requests ~ runs of the dispatch type)
    runs = [l.rstrip('\n').split('\t') for l in open(os.path.join(A.runs, 'runs.tsv'))][1:]
    ntype = collections.Counter(f"{r[4]}__m{r[6]}" for r in runs)
    # ---- calls per appearance for exe function entries (how often a site fires per run in which it appears)
    calls = collections.Counter(); maps = []
    for l in open(os.path.join(A.trace, 'maps.txt')):
        p = l.split()
        if len(p) >= 6 and p[5].endswith(exe_name) and 'x' in p[1]:
            a, b = (int(x, 16) for x in p[0].split('-')); maps.append((a, b, int(p[2], 16)))
    segs = []
    for l in sh(f"readelf -lW {A.symfs + A.exe}").splitlines():
        m = re.match(r"\s+LOAD\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x[0-9a-f]+\s+0x([0-9a-f]+)", l)
        if m: segs.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)))
    def exe_va(addr):
        for a, b, off in maps:
            if a <= addr < b:
                fo = addr - a + off
                for so, sv, sz in segs:
                    if so <= fo < so + sz: return fo - so + sv
        return None
    rb = re.compile(r"^\s*\d+\s+\d+\.\d+:\s+call\S*\s+[0-9a-f]+\s+=>\s+([0-9a-f]+)\s*$")
    with open(os.path.join(A.trace, 'branches.txt')) as f:
        for l in f:
            m = rb.match(l)
            if not m: continue
            va = exe_va(int(m.group(1), 16))
            if va is None: continue
            i = bisect.bisect_left(exe.aa, va)
            if i < len(exe.all) and exe.all[i][0] == va: calls[exe.all[i][3]] += 1
    appear = collections.Counter()
    types = {}; rawlen = {}
    for f in sorted(glob.glob(os.path.join(A.runs, 'list_*.tsv'))):
        name = os.path.basename(f)[5:-4]
        if '__all' in name or '__shadow' in name or not fnmatch.fnmatch(name, A.types) and not any(fnmatch.fnmatch(name, t) for t in A.types.split(',')): continue
        rows = [r for r in load_list(f) if r['p'] >= A.p_min]
        for r in rows: r['kind'] = 'exec'
        if A.shadow:
            sf = f[:-4] + '__shadow.tsv'
            if os.path.exists(sf):
                shrows = [r for r in load_list(sf) if r['p'] >= A.p_min]
                for r in shrows: r['kind'] = 'shadow'
                have = set((r['dso'], r['line']) for r in rows)
                shrows = [r for r in shrows if (r['dso'], r['line']) not in have]
                rows = sorted(rows + shrows, key=lambda r: (r['idx'], r['kind'] == 'shadow'))
        nraw = len(rows)
        if A.seq_skip: rows = [r for r in rows if r['pseq'] < A.seq_skip or exe.func_at_line(r['line']) is not None or r['dso'] != exe_name and False]
        if A.pair:
            seenp = set(); kept = []
            for r in rows:
                kp = (r['dso'], r['line'] & ~127)
                if kp in seenp: continue
                seenp.add(kp); kept.append(r)
            rows = kept
        types[name] = rows; rawlen[name] = nraw
        for r in rows:
            if r['dso'] == exe_name:
                fn = exe.func_at_line(r['line'])
                if fn: appear[fn[3]] += r['p'] * ntype.get(name, 0)
    # ---- assignment per run type
    plan = collections.defaultdict(list)          # site fn -> [(anchor, off, got, raw_line, dso)]
    site_entry = {}                                # site fn -> entry va
    report = []; totals = []
    for name, rows in types.items():
        n = len(rows); nruns = ntype.get(name, 0)
        sites = []
        seen_pages = set(); pagefirst = [False] * n
        for i, r in enumerate(rows):
            pg = (r['dso'], r['line'] >> 12)
            if pg not in seen_pages: seen_pages.add(pg); pagefirst[i] = True
        for i, r in enumerate(rows):
            if r.get('kind') == 'shadow' or r['dso'] != exe_name or r['p'] < A.site_p: continue
            fn = exe.func_at_line(r['line'])
            if not fn: continue
            if instr is not None and fn[3] not in instr: continue
            cpr = calls[fn[3]] / appear[fn[3]] if appear[fn[3]] else 99
            if cpr > A.max_calls: continue
            if fn[3] in site_entry and site_entry[fn[3]] != fn[0]: continue
            sites.append((i, fn))
        assigned = [False] * n; c = 0; issued = 0
        for si, (i, fn) in enumerate(sites):
            nxt = sites[si + 1][0] if si + 1 < len(sites) else n
            gap = bool(A.gap_k) and nxt - i > A.dmax
            kk = A.gap_k if gap else A.k
            start = max(c, i + A.d); end = min(n, i + (2 * A.dmax if gap else A.dmax))   # a gap site may reach twice as far
            take = []
            if A.page_touch:      # ITLB: the first line of each page coming up, with a longer lookahead, before the regular lines
                j = start
                while j < min(n, i + A.page_dmax) and len(take) < A.page_touch:
                    if not assigned[j] and pagefirst[j]: take.append(j); assigned[j] = True
                    j += 1
            j = start
            while j < end and len(take) < kk:
                if not assigned[j]: take.append(j); assigned[j] = True
                j += 1
            if not take: continue
            c = max(c, take[-1] + 1)
            site_entry[fn[3]] = fn[0]
            for j in take:
                r = rows[j]
                if r['dso'] == exe_name:
                    an = exe.anchor(r['line'])
                    if an: plan[fn[3]].append((an[0], an[1], 0, r['line'], exe_name, an[2])); issued += 1
                elif not A.no_lib and r['dso'] in libs:
                    an = libs[r['dso']].anchor(r['line'], maxoff=1 << 20)
                    if an: plan[fn[3]].append((an[0], an[1], 1, r['line'], r['dso'], an[2])); issued += 1
        cov = sum(assigned) / n if n else 0
        report.append(f"{name:24s} runs {nruns:3d} lines {n:4d} (raw {rawlen.get(name, n)}) sites {len(sites):3d} assigned {sum(assigned):4d} ({100*cov:.0f}%) prefetches {issued}")
        totals.append((nruns, n, sum(assigned), issued))
    # ---- post-call sites: the exe frame each run type resumes in; burst right after that call with the run's first lines
    post = {}   # key -> dict(fn, callee, nth, eff_addr, targets)
    if A.post_call:
        dis = sh(f"objdump -d --no-show-raw-insn {A.symfs + A.exe}").splitlines()
        addr_of_line = {}; fn_start = {}; cur_fn = None; ins_list = []
        for l in dis:
            m = re.match(r"^([0-9a-f]+) <([^>]+)>:$", l)
            if m: cur_fn = m.group(2); fn_start[cur_fn] = int(m.group(1), 16); continue
            m = re.match(r"^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$", l)
            if m and cur_fn: ins_list.append((int(m.group(1), 16), cur_fn, m.group(2), m.group(3)))
        ins_addr = [x[0] for x in ins_list]
        for name, rows in types.items():
            ef = os.path.join(A.runs, f"entry_{name}.tsv")
            if not os.path.exists(ef): continue
            ent = [l.split('\t') for l in open(ef) if not l.startswith('#')]
            if not ent or float(ent[0][0]) < 0.5: continue
            fn, ret = ent[0][2], int(ent[0][3].rstrip('\n'), 16)
            if instr is not None and fn not in instr: continue
            j = bisect.bisect_left(ins_addr, ret) - 1
            if j < 0 or ins_list[j][1] != fn or not ins_list[j][2].startswith('call'): continue
            mm = re.search(r"<([^>+]+)(?:@plt)?>", ins_list[j][3])
            if not mm: continue
            callee = mm.group(1).split('@')[0]
            nth = sum(1 for a, f_, op, arg in ins_list if f_ == fn and a < ret and op.startswith('call') and re.search(r"<" + re.escape(callee) + r"(@plt)?>", arg))
            tg = [r for r in rows[2:2 + A.post_call] if r.get('kind') != 'shadow']
            key = fn + '@1'
            v = 1
            while key in post and post[key]['callee'] != callee: v += 1; key = f"{fn}@{v}"
            if key in post: continue
            post[key] = dict(fn=fn, callee=callee, nth=nth, eff=ret, rows=tg, type=name)
            report.append(f"post-call site {key[:50]} after {callee[:40]} #{nth} (resume of {name}): {len(tg)} run-start lines")
    # ---- merge, dedup, cap per site; compute burst bytes and offset shifts
    def burst_bytes(tl, pic_module=False):
        direct = 0 if pic_module else sum(1 for t in tl if t[2] == 0) * 7
        groups = collections.defaultdict(list)
        for t in tl:
            if t[2] == 1 or pic_module: groups[t[0]].append(t[1])     # in a PIC module the pass emits every target via the GOT (direct_via_got)
        got = 0
        for an, offs in groups.items():
            got += 7 + sum(4 if o == 0 else 5 if -128 <= o < 128 else 8 for o in offs)
        b = direct + got
        return ((b + 15) // 16) * 16 if b else 0
    sites = {}
    for fn, tl in plan.items():
        seen = set(); uniq = []
        for t in tl:
            key = (t[4], t[3])
            if key in seen: continue
            seen.add(key); uniq.append(t)
        sites[fn] = uniq[:A.kmerge]
    for key, pc in post.items():
        tl = []
        for r in pc['rows']:
            if r['dso'] == exe_name:
                an = exe.anchor(r['line'])
                if an: tl.append((an[0], an[1], 0, r['line'], exe_name, an[2]))
            elif not A.no_lib and r['dso'] in libs:
                an = libs[r['dso']].anchor(r['line'], maxoff=1 << 20)
                if an: tl.append((an[0], an[1], 1, r['line'], r['dso'], an[2]))
        sites[key] = tl
    K = {fn: burst_bytes(tl, fn.split('@')[0] in pic) for fn, tl in sites.items()}
    # burst insertion points: entry sites act from E+16 (after the prologue), post-call sites from the return address
    ins = sorted([(site_entry[fn] + 16, K[fn]) for fn in sites if fn in site_entry and site_entry.get(fn) is not None] +
                 [(post[k]['eff'], K[k]) for k in post])
    ins_a = [x[0] for x in ins]; pref = [0]
    for _, k in ins: pref.append(pref[-1] + k)
    def shift(anchor_va, line_va):
        # a burst inserted at X moves lines L >= X relative to anchors A < X
        lo = bisect.bisect_right(ins_a, anchor_va); hi = bisect.bisect_right(ins_a, line_va)
        return pref[hi] - pref[lo] if hi > lo else 0
    out = {"sites": {}}
    nd = ng = 0
    for fn, tl in sites.items():
        t = []
        for an, off, got, line, dso, an_va in tl:
            if got == 0:
                off2 = off + shift(an_va, line)
                t.append([an, off2, 0]); nd += 1
            else:
                t.append([an, off, 1]); ng += 1
        out["sites"][fn] = {"k": K[fn], "t": t}
        if fn in post: out["sites"][fn]["after_call"] = post[fn]['callee']; out["sites"][fn]["nth"] = post[fn]['nth']
    json.dump(out, open(A.out, 'w'), indent=0)
    print("\n".join(report))
    W = sum(nr * n for nr, n, a, i in totals) or 1
    print(f"run-weighted: assigned {100*sum(nr*a for nr,n,a,i in totals)/W:.0f}% of listed lines, prefetch executions per run-weight {sum(nr*i for nr,n,a,i in totals)/max(1,sum(nr for nr,n,a,i in totals)):.0f}")
    reqs = ntype.get(max(ntype, key=lambda k: ntype[k] if 'm1' in k else 0), 1)
    per_req = sum(len(tl) * (ntype.get(nm, 0) / max(1, reqs)) for nm, rows in types.items() for tl in []) if False else 0
    print(f"plan: {len(out['sites'])} sites, {nd} direct + {ng} GOT targets, burst bytes total {sum(K.values())}, median k {statistics.median(len(v) for v in sites.values()) if sites else 0}")
    print(f"written {A.out}")

if __name__ == '__main__':
    main()
