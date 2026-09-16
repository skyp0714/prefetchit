#!/usr/bin/env python3
"""Profile-free selection of the functions that get sequential-lookahead prefetch.

Rule (structural, no trace): every function reachable through the static call
graph from the calls inside `main`'s loops (the steady-state simulation loop);
optional size / loopiness filters.  On Verilator DualMegaBoom this selects 3,987
functions (13.6 MB of 24 MB text) holding 97.4% of the L2I miss samples -- the
same coverage as the hand-written regex `___eval_nba|nba_sequent|nba_comb`.  Writes MANGLED names for
`-prefetchit-seq-functions-file` and reports how many bytes of text the list
covers.  --trace-dir (optional) scores the list: share of L2I miss samples whose
IP lies in a listed function.

    select_seq_functions.py --binary SIM --out funcs.txt [--min-size 1024] [--trace-dir T ...]
"""
from __future__ import annotations

import argparse
import bisect
import subprocess
import sys
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ret"))
from static_return_target_candidates import parse_nm, parse_objdump  # noqa: E402


def mangled_by_addr(binary: Path, nm: str) -> dict[int, str]:
    out = subprocess.run([nm, "-S", "-n", "--defined-only", str(binary)], check=True, text=True, capture_output=True).stdout
    m = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 4 and p[2] in "tTwW":
            m.setdefault(int(p[0], 16), p[3])
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-size", type=int, default=0)
    ap.add_argument("--max-backedges-per-kb", type=float, default=1e9, help="optionally skip loopy functions (default: no filter; Verilator eval_nba__0 has 3 backedges/KB and holds 60%% of the misses)")
    ap.add_argument("--max-depth", type=int, default=96)
    ap.add_argument("--root", action="append", default=[], help="extra root function names (demangled); default: main's loop callees")
    ap.add_argument("--trace-dir", type=Path, action="append", default=[])
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    a = ap.parse_args()

    syms = parse_nm(a.binary, a.nm)
    parse_objdump(a.binary, a.objdump, syms)
    graph = {f.name: [c.callee for c in f.calls if c.callee in syms.by_name] for f in syms.funcs}
    roots = set(a.root)
    main_f = syms.by_name.get("main")
    if main_f:
        for c in main_f.calls:
            if c.in_loop:
                roots.add(c.callee)
    if not roots:  # fallback: every callee called from any loop
        for f in syms.funcs:
            for c in f.calls:
                if c.in_loop:
                    roots.add(c.callee)
    dist = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        n = q.popleft()
        if dist[n] >= a.max_depth:
            continue
        for c in graph.get(n, []):
            if c not in dist:
                dist[c] = dist[n] + 1
                q.append(c)
    mangled = mangled_by_addr(a.binary, a.nm)
    chosen = []
    total_text = sum(f.size for f in syms.funcs)
    for f in syms.funcs:
        if f.name not in dist or f.size < a.min_size:
            continue
        if f.backedge_count / max(f.size / 1024.0, 1e-9) > a.max_backedges_per_kb:
            continue
        m = mangled.get(f.addr)
        if m:
            chosen.append((f, m))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("# select_seq_functions.py: reachable from main-loop roots, size>=%d, backedges/KB<=%.1f\n" % (a.min_size, a.max_backedges_per_kb)
                     + "\n".join(m for _f, m in chosen) + "\n")
    cov = sum(f.size for f, _m in chosen)
    print(f"[ok] roots={len(roots)} reachable={len(dist)} selected={len(chosen)} functions, {cov / 1e6:.1f} MB of {total_text / 1e6:.1f} MB text -> {a.out}")

    if a.trace_dir:
        sys.path.insert(0, str(HERE.parent / "ret"))
        from miss_stream_characterization import nm_index, load_base  # noqa: E402
        ns = nm_index(a.binary, a.nm)
        addrs = [s[0] for s in ns]
        sel_addrs = {f.addr for f, _m in chosen}
        hit = n = 0
        for td in a.trace_dir:
            base = load_base(td, ns)
            for line in (td / "lbr_raw_dump.txt").open(errors="replace"):
                t = line.split()
                if len(t) < 3:
                    continue
                try:
                    ip = int(t[0], 16) - base
                except ValueError:
                    continue
                i = bisect.bisect_right(addrs, ip) - 1
                n += 1
                if i >= 0 and ns[i][0] in sel_addrs:
                    hit += 1
        print(f"[score] {100 * hit / n:.1f}% of {n} L2I miss samples fall in the selected functions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
