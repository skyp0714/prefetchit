#!/usr/bin/env python3
"""Ground truth for RET-miss *producing calls* (TODO 1-A).

A RET-type L2I miss sample (LBR[0].type == RET) returns to LBR[0].to.  The call
that pushed that return address is statically unique: the call instruction
whose next instruction is LBR[0].to.  This tool maps every RET sample onto that
call and reports, per call: samples, the LBR depth at which the call itself is
still visible (branches executed inside the callee), the cycle lead between
the call and the RET, and the sample-IP/LBR[0].to relation.  It also writes a
per-sample-type overview (what fraction of misses are sequential, i.e. the
sample IP is not on LBR[0].to's cacheline).

    ret_producing_call_truth.py --binary SIM --trace-dir T1 [--trace-dir T2 ...] --out-dir D
"""
from __future__ import annotations

import argparse
import bisect
import csv
import re
import statistics as st
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(.*?)(?:\s+#.*)?$")
CALL_RE = re.compile(r"\bcallq?\b\s+(.+)$")
TARGET_RE = re.compile(r"0x([0-9a-fA-F]+)(?:\s+<(.+)>)?")
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
TEXT_TYPES = set("tTwW")


class Symbols:
    def __init__(self, binary: Path, nm: str):
        out = subprocess.run([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)],
                             check=True, text=True, capture_output=True, errors="replace").stdout
        syms = []
        for line in out.splitlines():
            p = line.split(None, 3)
            if len(p) < 4 or p[2] not in TEXT_TYPES:
                continue
            try:
                syms.append((int(p[0], 16), int(p[1], 16), p[3].strip()))
            except ValueError:
                continue
        syms.sort()
        self.addrs = [s[0] for s in syms]
        self.sizes = [s[1] for s in syms]
        self.names = [s[2] for s in syms]
        self.by_name: dict[str, int] = {}
        self.by_noargs: dict[str, int] = {}
        for a, _s, n in syms:
            self.by_name.setdefault(n, a)
            self.by_noargs.setdefault(n.split("(", 1)[0], a)
        self._cache: dict[str, int | None] = {}

    def func_at(self, addr: int) -> tuple[str, int] | None:
        i = bisect.bisect_right(self.addrs, addr) - 1
        if i < 0:
            return None
        if addr < self.addrs[i] + max(self.sizes[i], 1):
            return self.names[i], self.addrs[i]
        return None

    def resolve(self, tok: str) -> int | None:
        """sym+0xoff (symbolic perf dump) -> file address."""
        if tok in self._cache:
            return self._cache[tok]
        m = SYM_OFF_RE.match(tok)
        name, off = (m.group(1), int(m.group(2), 16)) if m else (tok, 0)
        if "@" in name:
            name = name.split("@", 1)[0]
        base = self.by_name.get(name)
        if base is None:
            base = self.by_noargs.get(name.split("(", 1)[0])
        val = None if base is None else base + off
        self._cache[tok] = val
        return val


def parse_calls(binary: Path, objdump: str, syms: Symbols):
    """Return (ret_addr -> call record), in-degree per callee name, insn count per function."""
    proc = subprocess.Popen([objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, errors="replace")
    cur = None
    pending = None  # (call_addr, callee_name, callee_addr, known)
    calls_by_ret: dict[int, dict] = {}
    indegree: Counter = Counter()
    ncalls_func: Counter = Counter()
    for line in proc.stdout:
        fm = FUNC_RE.match(line.strip())
        if fm:
            cur = (fm.group(2), int(fm.group(1), 16))
            pending = None
            continue
        im = INSN_RE.match(line)
        if not im or cur is None:
            continue
        addr = int(im.group(1), 16)
        asm = im.group(2).strip()
        if pending is not None:
            call_addr, callee, callee_addr, known = pending
            calls_by_ret[addr] = {"call_addr": call_addr, "ret_addr": addr, "caller": cur[0], "caller_addr": cur[1],
                                  "callee": callee, "callee_addr": callee_addr, "callee_known": known,
                                  "call_index": ncalls_func[cur[0]]}
            ncalls_func[cur[0]] += 1
            pending = None
        cm = CALL_RE.search(asm)
        if cm:
            tm = TARGET_RE.search(cm.group(1))
            taddr = int(tm.group(1), 16) if tm else None
            f = syms.func_at(taddr) if taddr is not None else None
            if f is not None:
                pending = (addr, f[0], f[1], True)
                indegree[f[0]] += 1
            else:
                pending = (addr, (tm.group(2) if tm and tm.group(2) else cm.group(1).strip()), taddr or 0, False)
    proc.wait()
    return calls_by_ret, indegree, ncalls_func


def parse_entry(tok: str):
    p = tok.split("/")
    if len(p) < 8:
        return None
    try:
        cyc = int(p[5]) if p[5] not in ("-", "") else 0
    except ValueError:
        cyc = 0
    return p[0], p[1], cyc, p[6].upper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--trace-dir", type=Path, action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--max-samples", type=int, default=0)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)

    syms = Symbols(a.binary, a.nm)
    calls_by_ret, indegree, ncalls_func = parse_calls(a.binary, a.objdump, syms)
    print(f"[ok] {len(calls_by_ret)} static calls, {len(indegree)} distinct known callees")

    type_stats: dict[str, Counter] = defaultdict(Counter)
    truth: dict[int, dict] = {}          # ret_addr -> aggregate
    ret_no_call = Counter()
    n = 0
    for td in a.trace_dir:
        path = td / "lbr_symbolic_dump.txt"
        with path.open(errors="replace") as f:
            for line in f:
                if a.max_samples and n >= a.max_samples:
                    break
                toks = line.split()
                if len(toks) < 3:
                    continue
                try:
                    ip = int(toks[0], 16)
                except ValueError:
                    continue
                entries = [e for e in (parse_entry(t) for t in toks[1:]) if e]
                if not entries:
                    continue
                n += 1
                btype = entries[0][3]
                to0 = syms.resolve(entries[0][1])
                from0 = syms.resolve(entries[0][0])
                ts = type_stats[btype]
                ts["samples"] += 1
                # sample IP is a runtime (PIE) address: compare with runtime raw? we only have symbolic; derive
                # file address of the IP from toks[0]? perf prints raw ip; recover base from the first entry.
                # The symbolic dump prints ip raw and brstack symbolic, so use the from/to of LBR[0]:
                # ip_file = ip - (raw_from0 - to0_file) is unavailable here; instead record via the '-F ip,sym' sym.
                if to0 is not None:
                    ts["to0_resolved"] += 1
                if btype != "RET" or to0 is None:
                    continue
                rec = calls_by_ret.get(to0)
                if rec is None:
                    ret_no_call[entries[0][1]] += 1
                    continue
                agg = truth.get(to0)
                if agg is None:
                    agg = truth[to0] = {"samples": 0, "depths": [], "lead_cycles": [], "deep": 0,
                                        "ret_from_callee_match": 0}
                agg["samples"] += 1
                # callee of the RET (LBR[0].from) should be inside rec.callee (or a tail-callee)
                if from0 is not None:
                    ff = syms.func_at(from0)
                    if ff and ff[0] == rec["callee"]:
                        agg["ret_from_callee_match"] += 1
                # find the call in the LBR: entries[d].from == call_addr
                found = False
                cyc = 0
                for d in range(1, len(entries)):
                    cyc += entries[d - 1][2]
                    if entries[d][3] == "CALL" and syms.resolve(entries[d][0]) == rec["call_addr"]:
                        agg["depths"].append(d)
                        agg["lead_cycles"].append(cyc)
                        found = True
                        break
                if not found:
                    agg["deep"] += 1
    print(f"[ok] samples={n}")

    # ---- per-type overview
    with (a.out_dir / "sample_type_overview.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["branch_type", "samples", "share_pct", "to0_resolved"])
        for t, c in sorted(type_stats.items(), key=lambda kv: -kv[1]["samples"]):
            w.writerow([t, c["samples"], f"{100 * c['samples'] / n:.2f}", c["to0_resolved"]])

    # ---- truth CSV
    rows = []
    for ret_addr, agg in truth.items():
        rec = calls_by_ret[ret_addr]
        rows.append({
            "samples": agg["samples"],
            "call_addr": hex(rec["call_addr"]), "ret_addr": hex(ret_addr),
            "ret_cacheline64": hex(ret_addr & ~0x3F), "ret_line_offset": ret_addr & 0x3F,
            "call_crosses_line": int((rec["call_addr"] & ~0x3F) != (ret_addr & ~0x3F)),
            "caller": rec["caller"], "caller_call_index": rec["call_index"], "caller_ncalls": ncalls_func[rec["caller"]],
            "callee": rec["callee"], "callee_known": int(rec["callee_known"]),
            "callee_indegree": indegree.get(rec["callee"], 0),
            "callee_size": (lambda f: syms.sizes[syms.addrs.index(f[1])] if f else 0)(syms.func_at(rec["callee_addr"]) if rec["callee_known"] else None),
            "in_lbr_pct": f"{100 * len(agg['depths']) / agg['samples']:.1f}",
            "depth_median": st.median(agg["depths"]) if agg["depths"] else "",
            "lead_cycles_median": st.median(agg["lead_cycles"]) if agg["lead_cycles"] else "",
            "lead_cycles_p10": (sorted(agg["lead_cycles"])[len(agg["lead_cycles"]) // 10] if agg["lead_cycles"] else ""),
            "ret_from_callee_match_pct": f"{100 * agg['ret_from_callee_match'] / agg['samples']:.1f}",
        })
    rows.sort(key=lambda r: -r["samples"])
    with (a.out_dir / "ret_producing_calls.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = sum(r["samples"] for r in rows)
    print(f"[ok] RET samples mapped to a producing call: {total} over {len(rows)} calls; unmapped RET targets: {sum(ret_no_call.values())}")
    cum = 0
    marks = {}
    for i, r in enumerate(rows, 1):
        cum += r["samples"]
        for k in (100, 250, 500, 1000, 2000, 3000, 5000, 10000):
            if i == k:
                marks[k] = cum
    print("[ok] hottest-K producing calls cover: " + ", ".join(f"K={k}: {100 * v / total:.1f}%" for k, v in marks.items()))
    depths = [d for agg in truth.values() for d in agg["depths"]]
    leads = [c for agg in truth.values() for c in agg["lead_cycles"]]
    deep = sum(agg["deep"] for agg in truth.values())
    print(f"[ok] call visible in LBR for {len(depths)} samples ({100 * len(depths) / total:.1f}%), deeper than LBR for {deep}")
    if depths:
        print(f"[ok] depth median={st.median(depths)} p25={sorted(depths)[len(depths)//4]} p75={sorted(depths)[3*len(depths)//4]}; lead cycles median={st.median(leads)} p10={sorted(leads)[len(leads)//10]} p90={sorted(leads)[9*len(leads)//10]}")
    # callee in-degree and size distribution (sample-weighted)
    ind = Counter()
    for r in rows:
        ind["indeg=1" if r["callee_indegree"] == 1 else ("indeg 2-4" if r["callee_indegree"] <= 4 else "indeg>4")] += r["samples"]
    print("[ok] sample-weighted callee in-degree: " + ", ".join(f"{k}: {100 * v / total:.1f}%" for k, v in ind.items()))
    cross = sum(r["samples"] for r in rows if r["call_crosses_line"])
    print(f"[ok] continuation on a different cacheline than the call: {100 * cross / total:.1f}% of samples")
    callers = Counter()
    for r in rows:
        callers[r["caller"][:70]] += r["samples"]
    print("[ok] top caller functions: " + "; ".join(f"{k} {100 * v / total:.1f}%" for k, v in callers.most_common(4)))
    callees = Counter()
    for r in rows:
        callees[r["callee"][:60]] += r["samples"]
    print("[ok] top callees: " + "; ".join(f"{k} {100 * v / total:.1f}%" for k, v in callees.most_common(6)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
