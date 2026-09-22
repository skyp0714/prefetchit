#!/usr/bin/env python3
"""run_paths.py — split an Intel PT trace of a service into runs (context-switch-in .. switch-out), attribute each run to the
blocking call that woke the thread (hook), the thrift method session it belongs to and the first wake-stream MARK it executes,
and produce per-run-type FIRST-TOUCH line sequences (the class-B prefetch target lists) plus the statistics the wake-stream plan
needs (docs/prefetch_plan_classB_wakestream.md §3).

Inputs (from ws_pt_trace.sh): branches.txt (perf script --itrace=b --show-switch-events -F tid,time,ip,addr,flags),
maps.txt (/proc/pid/maps), symfs_<arm>/ (copies of the mapped images), optional syscalls.txt.

Usage: run_paths.py TRACE_DIR [--symfs DIR] [--min-runs 8] [--landmarks file] [--marks file] [--out DIR]
Outputs: runs.tsv, list_<hook>__all.tsv (stage-0 lists, method unknown), list_<method>__m<k>.tsv (runs whose first mark is k,
all hooks; k=0 = no mark), each row: rank, p (share of runs touching the line), median first-touch index, median us, dso, line, sym.
"""
import argparse, bisect, collections, os, re, statistics, subprocess, sys

NR = {45: 'recv', 47: 'recv', 0: 'read', 19: 'read', 17: 'read', 7: 'poll', 271: 'poll', 270: 'poll', 23: 'poll', 232: 'epoll_wait',
      281: 'epoll_wait', 202: 'futex', 230: 'sleep', 44: 'send', 46: 'send', 1: 'send', 20: 'send', 43: 'accept', 288: 'accept', 56: 'clone', 435: 'clone'}
HOOK_RE = [('futex', re.compile(r'futex|cond_wait|cond_timedwait|sem_wait|sem_timedwait|pthread_join')), ('clone', re.compile(r'clone|start_thread')),
           ('recv', re.compile(r'\brecv')), ('epoll_wait', re.compile(r'epoll')), ('poll', re.compile(r'(^|_)p?poll($|_|@)|select')),
           ('read', re.compile(r'^(__|_IO_|__GI_)*(libc_)?p?readv?($|@|_nocancel)', re.M)), ('send', re.compile(r'\bsend|(^|_)writev?($|@|_nocancel)', re.M)),
           ('accept', re.compile(r'accept')), ('connect', re.compile(r'connect')), ('sleep', re.compile(r'nanosleep|clock_nanosleep'))]
LINE = 64

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout

class Dso:
    """maps a process VA to an ELF vaddr and to the nearest symbol, for one mapped file (static symbols, else dynamic ones)."""
    def __init__(self, path, symfs):
        self.path = path; self.name = os.path.basename(path)
        f = symfs + path if symfs and os.path.exists(symfs + path) else path
        self.file = f if os.path.exists(f) else None
        self.segs = []; self.syms = []; self.sym_addr = []
        if self.file:
            for l in sh(f"readelf -lW {self.file}").splitlines():
                m = re.match(r"\s+LOAD\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+0x[0-9a-f]+\s+0x([0-9a-f]+)", l)
                if m: self.segs.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)))
            for opt in ("", "-D"):
                for l in sh(f"nm {opt} -nS --defined-only -C {self.file} 2>/dev/null").splitlines():
                    p = l.split(None, 3)
                    if len(p) == 4 and p[2] in 'TtWwiV': self.syms.append((int(p[0], 16), int(p[1], 16), p[3].split('@')[0][:70]))
                    elif len(p) == 3 and p[1] in 'TtWwiV': self.syms.append((int(p[0], 16), 0, p[2].split('@')[0][:70]))
                if self.syms: break
            self.syms.sort(); self.sym_addr = [s[0] for s in self.syms]
    def off2va(self, file_off):
        for fo, va, sz in self.segs:
            if fo <= file_off < fo + sz: return file_off - fo + va
        return file_off
    def sym(self, va):
        i = bisect.bisect_right(self.sym_addr, va) - 1
        if i < 0: return '?', va
        a, sz, n = self.syms[i]
        if sz and va >= a + sz and va - a > 4096: return '?', va
        return n, va - a

class Maps:
    def __init__(self, maps_txt, symfs):
        self.regions = []; self.dsos = {}
        for l in open(maps_txt):
            p = l.split()
            if len(p) < 6 or not p[5].startswith('/') or 'x' not in p[1]: continue
            a, b = (int(x, 16) for x in p[0].split('-')); off = int(p[2], 16); path = p[5]
            if path not in self.dsos: self.dsos[path] = Dso(path, symfs)
            self.regions.append((a, b, off, self.dsos[path]))
        self.regions.sort(); self.starts = [r[0] for r in self.regions]
    def resolve(self, va):
        i = bisect.bisect_right(self.starts, va) - 1
        if i < 0: return None
        a, b, off, d = self.regions[i]
        if va >= b: return None
        return d, d.off2va(va - a + off)

def parse(trace):
    br = collections.defaultdict(list); sw = collections.defaultdict(list)
    rb = re.compile(r"^\s*(\d+)\s+(\d+\.\d+):\s+(.*?)\s*([0-9a-f]+)\s+=>\s+([0-9a-f]+)\s*$")
    rs = re.compile(r"^\s*(\d+)\s+(\d+\.\d+):\s+PERF_RECORD_SWITCH(?:_CPU_WIDE)?\s+(IN|OUT)(\s+preempt)?")
    n = 0
    with open(os.path.join(trace, 'branches.txt')) as f:
        for l in f:
            m = rb.match(l)
            if m: br[int(m.group(1))].append((float(m.group(2)), int(m.group(4), 16), int(m.group(5), 16), m.group(3).strip())); n += 1; continue
            m = rs.match(l)
            if m and m.group(1) != '0': sw[int(m.group(1))].append((float(m.group(2)), m.group(3), bool(m.group(4))))
    sc = collections.defaultdict(list); sp = os.path.join(trace, 'syscalls.txt')
    if os.path.exists(sp):
        rc = re.compile(r"\s(\d+)\s+\[\d+\]\s+(\d+\.\d+):\s+raw_syscalls:sys_exit:\s+NR\s+(\d+)")
        for l in open(sp):
            m = rc.search(l)
            if m: sc[int(m.group(1))].append((float(m.group(2)), int(m.group(3))))
    return br, sw, sc, n

def runs_of(tid, brs, sws, scs):
    sws = sorted(sws); scs = sorted(scs); sct = [s[0] for s in scs]
    brs = sorted(brs, key=lambda r: r[0]); brt = [r[0] for r in brs]; t_in = None; first_run = True
    for t, kind, pre in sws:
        if kind == 'IN': t_in = t
        elif kind == 'OUT' and t_in is not None:
            i = bisect.bisect_left(sct, t_in - 2e-6)
            hook = NR.get(scs[i][1], 'nr%d' % scs[i][1]) if i < len(scs) and scs[i][0] <= t_in + 30e-6 else None
            a = bisect.bisect_left(brt, t_in - 1e-6); b = bisect.bisect_right(brt, t + 1e-6)
            yield (t_in, t, hook, brs[a:b], first_run); t_in = None; first_run = False

def classify_hook(recs, maps, first_run):
    names = []
    for t, ip, addr, fl in recs[:60]:
        for a in (ip, addr):
            if a:
                r = maps.resolve(a)
                if r: names.append(r[0].sym(r[1])[0])
    blob = '\n'.join(names)
    for h, rx in HOOK_RE:
        if rx.search(blob): return h
    return 'clone' if first_run else 'none'

def touched_lines(records, maps):
    out = []; prev = None
    for t, ip, addr, fl in records:
        if prev is not None and ip:
            lo, hi = prev, ip
            if hi >= lo and hi - lo < 65536:
                for a in range(lo & ~(LINE - 1), (hi & ~(LINE - 1)) + 1, LINE): out.append((t, a))
        prev = addr if addr else None
    res = []
    for t, a in out:
        r = maps.resolve(a)
        if r: res.append((t, r[0], r[1] & ~(LINE - 1)))
    return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('trace'); ap.add_argument('--symfs'); ap.add_argument('--min-runs', type=int, default=8)
    ap.add_argument('--landmarks'); ap.add_argument('--marks', help='"id dso elf_addr" per line (ws_marks.sh)'); ap.add_argument('--out')
    ap.add_argument('--method-sym', default='Processor::process_'); ap.add_argument('--exe', default='/custom/MovieIdService'); ap.add_argument('--instrumentable', help='mangled names the pass can instrument: entry frames are restricted to these')
    A = ap.parse_args(); out = A.out or os.path.join(A.trace, 'runs'); os.makedirs(out, exist_ok=True)
    symfs = A.symfs
    if not symfs:
        cands = sorted(d for d in os.listdir(os.path.join(A.trace, '..')) if d.startswith('symfs'))
        symfs = os.path.join(A.trace, '..', cands[-1]) if cands else None
    maps = Maps(os.path.join(A.trace, 'maps.txt'), symfs)
    global exe_name_g, instr_addr_g, instr_syms_g; exe_name_g = os.path.basename(A.exe)
    instr_syms_g = []; instr_addr_g = []
    if A.instrumentable:
        iset = set(open(A.instrumentable).read().split())
        for l in sh(f"nm -nS --defined-only {symfs + A.exe}").splitlines():
            p = l.split()
            if len(p) == 4 and p[2] in 'TtWw' and p[3] in iset: instr_syms_g.append((int(p[0], 16), int(p[1], 16), p[3]))
        instr_syms_g.sort(); instr_addr_g = [x[0] for x in instr_syms_g]
    marks = {}
    if A.marks:
        for l in open(A.marks):
            p = l.split()
            if len(p) == 3: marks[(p[1], int(p[2], 16) & ~(LINE - 1))] = int(p[0])
    br, sw, sc, nrec = parse(A.trace)
    print(f"branch records {nrec}, threads with branches {len(br)}, with switches {len(sw)}, marks known {len(marks)}, symfs {symfs}")
    runs = []
    for tid in sw:
        for t_in, t_out, hook, recs, first_run in runs_of(tid, br.get(tid, []), sw[tid], sc.get(tid, [])):
            if not recs: continue
            if hook is None: hook = classify_hook(recs, maps, first_run)
            entry_ret = None    # (mangled exe function, return address elf va): first 'return' after resume into an instrumentable exe function
            for t, ip, addr, fl in recs[:600]:
                if 'return' in fl and addr:
                    r_ = maps.resolve(addr)
                    if r_ and r_[0].name == exe_name_g:
                        i_ = bisect.bisect_right(instr_addr_g, r_[1]) - 1
                        if i_ >= 0 and r_[1] < instr_addr_g[i_] + max(instr_syms_g[i_][1], 16):
                            entry_ret = (instr_syms_g[i_][2], r_[1]); break
            lines = touched_lines(recs, maps)
            seen = set(); first = []; prevk = None; rank_of = {}
            for t, d, va in lines:
                k = (d.name, va)
                if k not in seen: seen.add(k); rank_of[k] = len(first); first.append((t, d, va, prevk == (d.name, va - LINE)))
                prevk = k
            shadow = {}      # (dso, line) -> (rank of the taken branch's line, dso): fetched by fall-through but never executed in this run
            for t, ip, addr, fl in recs:
                if not ip or not addr or ('jcc' not in fl and 'jmp' not in fl and 'call' not in fl and 'return' not in fl): continue
                if (ip & ~(LINE - 1)) == (addr & ~(LINE - 1)): continue
                rb_ = maps.resolve(ip & ~(LINE - 1))
                if not rb_: continue
                bk = (rb_[0].name, rb_[1] & ~(LINE - 1))
                for kk in (1, 2):
                    r_ = maps.resolve((ip & ~(LINE - 1)) + kk * LINE)
                    if not r_: continue
                    sk = (r_[0].name, r_[1] & ~(LINE - 1))
                    if sk in seen or sk in shadow: continue
                    shadow[sk] = (rank_of.get(bk, 0), r_[0])
            method = None; mk = 0
            for t, d, va, _sq in first:
                n, _ = d.sym(va)
                if A.method_sym in n and 'process_' in n and method is None: method = n.split('process_')[1].split('(')[0]
                if '_Async_state_impl' in n and '$_' in n and method is None:
                    mm = re.search(r'(\w+)\(.*?\$_(\d+)', n); method = ('async_' + mm.group(1)[:12] + '_' + mm.group(2)) if mm else 'async'
                if mk == 0 and (d.name, va) in marks: mk = marks[(d.name, va)]
            runs.append(dict(tid=tid, t_in=t_in, t_out=t_out, hook=hook, method=method, mk=mk, nrec=len(recs), nlines=len(lines), first=first, shadow=shadow, entry_ret=entry_ret))
    runs.sort(key=lambda r: r['t_in'])
    cur = {}; jidx = {}; lastmk = {}     # method sessions: a thread keeps its method from the dispatch run until the next dispatch run
    for r in runs:
        tid = r['tid']
        if r['method'] is not None: cur[tid] = r['method']; jidx[tid] = 0
        elif tid in cur: jidx[tid] += 1; r['method'] = cur[tid]
        else: r['method'] = 'none'
        r['j'] = jidx.get(tid, 0)
        if r['mk']: lastmk[tid] = r['mk']
        elif tid in lastmk: r['mk'] = f"{lastmk[tid]}p"      # markless run right after mark k (worker's post-RPC run, main thread's futex run)
    with open(os.path.join(out, 'runs.tsv'), 'w') as f:
        f.write("tid\tt_in\tdur_us\thook\tmethod\tj\tfirst_mark\tbranch_recs\tlines_touched\tdistinct_lines\n")
        for r in runs: f.write(f"{r['tid']}\t{r['t_in']:.6f}\t{(r['t_out']-r['t_in'])*1e6:.1f}\t{r['hook']}\t{r['method']}\t{r['j']}\t{r['mk']}\t{r['nrec']}\t{r['nlines']}\t{len(r['first'])}\n")
    byhook = collections.Counter(r['hook'] for r in runs); bytype = collections.Counter((r['method'], r['mk']) for r in runs)
    print(f"runs {len(runs)}; by hook: {dict(byhook.most_common())}")
    print("by (method, first mark):", dict(bytype.most_common(16)))
    print("by (hook, method, first mark):", dict(collections.Counter((r['hook'], r['method'], r['mk']) for r in runs).most_common(16)))
    dl = [len(r['first']) for r in runs]; du = [(r['t_out'] - r['t_in']) * 1e6 for r in runs]
    print(f"distinct lines per run: median {statistics.median(dl):.0f} mean {statistics.mean(dl):.0f} max {max(dl)}; run duration us: median {statistics.median(du):.1f} mean {statistics.mean(du):.1f}")
    print(f"total first touches {sum(dl)}; distinct lines overall {len(set((d.name, va) for r in runs for _, d, va, _sq in r['first']))}")
    allt = sorted((t - r['t_in']) * 1e6 for r in runs for t, _, _, _sq in r['first'])
    if allt: print("first touches within N us of the run start: " + ", ".join(f"{N}us {100*bisect.bisect_right(allt, N)/len(allt):.1f}%" for N in (1, 2, 5, 10, 20, 40, 100)))
    dmix = collections.Counter(d.name for r in runs for _, d, _, _sq in r['first']); tot = sum(dmix.values()) or 1
    print("first touches by dso: " + ", ".join(f"{k} {100*v/tot:.0f}%" for k, v in dmix.most_common(8)))
    landmarks = [l.strip() for l in open(A.landmarks)] if A.landmarks else []

    def emit(name, rs):
        nr = len(rs); pos = collections.defaultdict(list); tim = collections.defaultdict(list); dsoof = {}; sq = collections.defaultdict(list)
        for r in rs:
            for i, (t, d, va, s_) in enumerate(r['first']):
                pos[(d.name, va)].append(i); tim[(d.name, va)].append((t - r['t_in']) * 1e6); dsoof[(d.name, va)] = d; sq[(d.name, va)].append(1 if s_ else 0)
        rows = sorted((statistics.median(ps), len(ps) / nr, statistics.median(tim[k]), k) for k, ps in pos.items())
        with open(os.path.join(out, f"list_{name}.tsv"), 'w') as f:
            f.write("#rank\tp\tidx_med\tus_med\tdso\telf_line\tsym+off\tpseq\n")
            for rank, (im, p, um, k) in enumerate(rows):
                s, o = dsoof[k].sym(k[1]); f.write(f"{rank}\t{p:.2f}\t{im:.0f}\t{um:.1f}\t{k[0]}\t{k[1]:#x}\t{s}+{o:#x}\t{sum(sq[k])/len(sq[k]):.2f}\n")
        spos = collections.defaultdict(list); sdso = {}
        for r in rs:
            for k, (rk, d) in r['shadow'].items(): spos[k].append(rk); sdso[k] = d
        srows = sorted((statistics.median(v), len(v) / nr, k) for k, v in spos.items())
        with open(os.path.join(out, f"list_{name}__shadow.tsv"), 'w') as f:
            f.write("#rank\tp\tidx_med\tus_med\tdso\telf_line\tsym+off\n")
            for rank, (im, p, k) in enumerate(srows):
                s_, o_ = sdso[k].sym(k[1]); f.write(f"{rank}\t{p:.2f}\t{im:.0f}\t0\t{k[0]}\t{k[1]:#x}\t{s_}+{o_:#x}\n")
        ent = collections.Counter(r['entry_ret'] for r in rs if r['entry_ret'])
        with open(os.path.join(out, f"entry_{name}.tsv"), 'w') as f:
            f.write("#share\tn\texe_function\tret_elf_va\n")
            for (fn_, va_), c_ in ent.most_common(5): f.write(f"{c_/nr:.2f}\t{c_}\t{fn_}\t{va_:#x}\n")
        if ent: fn_, va_ = ent.most_common(1)[0][0]; print(f"    run starts inside exe frame {fn_[:60]} (return to {va_:#x}) in {100*ent.most_common(1)[0][1]/nr:.0f}% of runs")
        tot_first = sum(len(r['first']) for r in rs) or 1
        cov50 = sum(1 for r in rs for _, d, va, _sq in r['first'] if len(pos[(d.name, va)]) / nr >= 0.5) / tot_first
        print(f"type {name}: runs {nr}, median distinct lines {statistics.median(len(r['first']) for r in rs):.0f}, median us {statistics.median((r['t_out']-r['t_in'])*1e6 for r in rs):.1f}, "
              f"lines p>=0.5: {sum(1 for r in rows if r[1] >= 0.5)} (cover {100*cov50:.0f}% of first touches), p>=0.9: {sum(1 for r in rows if r[1] >= 0.9)}")
        for (dn, va), mid in sorted(marks.items(), key=lambda x: x[1]):
            if (dn, va) in pos:
                rank = next(i for i, r in enumerate(rows) if r[3] == (dn, va)); im, p, um, _ = rows[rank]
                print(f"    mark {mid}: rank {rank} (idx {im:.0f}, {um:.1f} us, p={p:.2f})")
        for lm in landmarks:
            hits = [(rk, r) for rk, r in enumerate(rows) if lm in dsoof[r[3]].sym(r[3][1])[0]]
            if hits:
                rk, (im, p, um, k) = min(hits); print(f"    landmark {lm[:40]:40s} rank {rk:5d} ({um:6.1f} us, p={p:.2f})")

    for h, c in byhook.most_common():
        if c >= A.min_runs: emit(f"{h}__all", [r for r in runs if r['hook'] == h])
    for (m, mk), c in bytype.most_common():
        if c >= A.min_runs: emit(f"{m}__m{mk}", [r for r in runs if r['method'] == m and r['mk'] == mk])
    seqshare = sum(1 for r in runs for _, _, _, s_ in r['first'] if s_) / max(1, sum(dl))
    print(f"share of first touches entered by fall-through (HW next-line territory): {100*seqshare:.0f}%")
    print(f"written: {out}/runs.tsv and list_*.tsv")

if __name__ == '__main__':
    main()
