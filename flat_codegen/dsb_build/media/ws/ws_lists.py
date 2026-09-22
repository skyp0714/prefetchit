#!/usr/bin/env python3
"""ws_lists.py — turn run_paths.py first-touch lists into a WS_LIST file for ws_rt.c.

  ws_lists.py RUNS_DIR OUT [--p-min 0.5] [--pair] [--max N] [--keys recv,poll,futex,...] [--site ID:KEY:LANDMARK ...]

For each list_<hook>_<method>.tsv: keep lines with p >= p-min in consensus order, optionally collapse 128 B pairs (keep the first
line of each pair in order), cap at --max, and emit 'L <key> <dso> <elf_line>' where key = '<hook>' for the '_all' aggregate list
and '<hook>_<method>' otherwise. --site ID:KEY:SUBSTR emits 'S ID KEY POS' with POS = the rank of the first list entry whose symbol
contains SUBSTR (the mark's position in that list)."""
import argparse, glob, os, sys

def load(path):
    rows = []
    for l in open(path):
        if l.startswith('#'): continue
        p = l.rstrip('\n').split('\t')
        if len(p) < 7: continue
        rows.append(dict(rank=int(p[0]), p=float(p[1]), idx=float(p[2]), us=float(p[3]), dso=p[4], line=int(p[5], 16), sym=p[6]))
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('runs'); ap.add_argument('out'); ap.add_argument('--p-min', type=float, default=0.5)
    ap.add_argument('--pair', action='store_true'); ap.add_argument('--max', type=int, default=0); ap.add_argument('--keys', default='')
    ap.add_argument('--site', action='append', default=[]); ap.add_argument('--auto-sites', help='marks file (ws_marks.sh) -> S lines'); ap.add_argument('--next', help='next.tsv from run_paths -> N lines'); ap.add_argument('--exclude-dso', default='')
    A = ap.parse_args(); want = set(A.keys.split(',')) if A.keys else None; excl = set(A.exclude_dso.split(',')) if A.exclude_dso else set()
    out = open(A.out, 'w'); summary = []
    lists = {}
    for f in sorted(glob.glob(os.path.join(A.runs, 'list_*.tsv'))):
        name = os.path.basename(f)[5:-4]
        if '__' not in name: continue
        a, b = name.split('__', 1); key = a if b == 'all' else name      # 'recv' (stage-0 hook list) or 'UploadMovieId__m3'
        if want and key not in want: continue
        rows = [r for r in load(f) if r['p'] >= A.p_min and r['dso'] not in excl]
        if A.pair:
            seen = set(); kept = []
            for r in rows:
                k = (r['dso'], r['line'] & ~127)
                if k in seen: continue
                seen.add(k); kept.append(r)
            rows = kept
        if A.max: rows = rows[:A.max]
        lists[key] = rows
        for r in rows: out.write(f"L {key} {r['dso']} {r['line']:x}\n")
        summary.append(f"{key}: {len(rows)} lines (p>={A.p_min}{', paired' if A.pair else ''})")
    site_list = {}
    if A.auto_sites:      # every mark id -> the __m list where its own line has the highest p (the run type the mark starts)
        marks = {}
        for l in open(A.auto_sites):
            p = l.split()
            if len(p) == 3: marks[int(p[0])] = (p[1], int(p[2], 16) & ~63)
        for mid, (dso, line) in sorted(marks.items()):
            best = None
            for key, rows in lists.items():
                if '__m' not in key: continue
                for i, r in enumerate(rows):
                    if r['dso'] == dso and r['line'] == line and (best is None or r['p'] > best[0]): best = (r['p'], key, i)
            if best: out.write(f"S {mid} {best[1]} {best[2]}\n"); summary.append(f"site {mid} -> {best[1]}@{best[2]} (p={best[0]:.2f})"); site_list[mid] = best[1]
            else: summary.append(f"site {mid}: mark line not in any list")
    if A.next and site_list:
        succ = {}
        for l in open(A.next):
            if l.startswith('#'): continue
            fm, fk, nh, nm, nk, share, n = l.rstrip('\n').split('\t')
            succ.setdefault(f"{fm}__m{fk}", {}); succ[f"{fm}__m{fk}"][f"{nm}__m{nk}"] = succ[f"{fm}__m{fk}"].get(f"{nm}__m{nk}", 0) + float(share)
        marked = set(site_list.values())
        for mid, key in sorted(site_list.items()):
            chain = []; cur = key
            for _ in range(3):
                nxt = max(succ.get(cur, {}).items(), key=lambda x: x[1], default=None)
                if not nxt or nxt[1] < 0.5 or nxt[0] not in lists: break
                chain.append(nxt[0]); cur = nxt[0]
                if cur in marked: break
            if chain: out.write(f"N {mid} {' '.join(chain)}\n"); summary.append(f"next after mark {mid}: {' -> '.join(chain)}")
    import fnmatch
    for s in A.site:
        sid, key, sub = s.split(':', 2)            # key may be a glob ('clone_async_*_1'); sub = landmark symbol substring, or '@N' = fixed position N, or '-' = keep list, position 0
        if key != '-':
            ks = [k for k in lists if fnmatch.fnmatch(k, key)]
            if not ks: print(f"site {sid}: no list matches {key}", file=sys.stderr); continue
            key = ks[0]
        rows = lists.get(key, [])
        if sub.startswith('@'): pos = int(sub[1:])
        elif sub == '-': pos = 0
        else:
            pos = next((i for i, r in enumerate(rows) if sub in r['sym']), None)
            if pos is None: print(f"site {sid}: landmark '{sub}' not in list {key}", file=sys.stderr); continue
        out.write(f"S {sid} {key} {pos}\n"); summary.append(f"site {sid} -> {key}@{pos}" + (f" ({rows[pos]['sym'][:40]})" if rows and pos < len(rows) else ''))
    out.close(); print("\n".join(summary)); print(f"written {A.out}")

if __name__ == '__main__':
    main()
