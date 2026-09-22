#!/usr/bin/env python3
"""Static RET plan v3: call-level selection of *producing* calls (TODO 1-A).

Profile-free rule derived from the miss-stream analysis (2026-09-16): a RET
miss is produced when a straight-line dispatcher function (Verilator
eval_nba*/nba_sequent*/nba_comb*) calls a callee that runs long enough for the
hardware sequential prefetcher to lose the caller's stream -- generated
sub-functions above a size threshold, and long libc calls (memset/memcpy).
The continuation *and the lines after it* are then cold, so each selected call
gets `prefetcht1 continuation+64*k` for k in 0..lines-1 right before the call
(lead = the callee's execution).

Selection is purely structural; --trace-dir (optional) only scores the plan
against the producing-call truth (ret_producing_call_truth.py).

    static_ret_v3_plan.py --binary SIM --output plan.json [--min-callee-size 256]
        [--callee-regex ...] [--caller-regex ...] [--plt-callees memset,memcpy]
        [--lines 4] [--top-k 0] [--trace-dir T ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ret_producing_call_truth import Symbols, parse_calls  # noqa: E402
from static_site_plan_to_prefetch_plan import build_symbol_index, resolve_addrs, source_obj  # noqa: E402

DEFAULT_CALLER = r"___eval_nba|nba_sequent|nba_comb|___eval_act|act_sequent|act_comb|___eval_ico|ico_sequent|ico_comb"
DEFAULT_CALLEE = r"nba_sequent|nba_comb|act_sequent|act_comb|ico_sequent|ico_comb|___eval_nba__|___eval_act__|___eval_ico__"
DEFAULT_EXCLUDE = r"eval_initial|eval_static|eval_final|_settle|__Vdpi|__Vtrace|_debug"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None, help="where to write the selection CSV (default: beside --output)")
    ap.add_argument("--label", default="static_ret_v3")
    ap.add_argument("--caller-regex", default=DEFAULT_CALLER)
    ap.add_argument("--callee-regex", default=DEFAULT_CALLEE)
    ap.add_argument("--exclude-regex", default=DEFAULT_EXCLUDE)
    ap.add_argument("--plt-callees", default="memset,memcpy,memmove", help="external callees treated as long")
    ap.add_argument("--min-callee-size", type=int, default=256, help="bytes; generated callees below this are skipped")
    ap.add_argument("--top-k", type=int, default=0, help="keep the K largest-callee calls (0 = all that pass the filter)")
    ap.add_argument("--lines", type=int, default=4, help="consecutive continuation cachelines to prefetch")
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--trace-dir", type=Path, action="append", default=[], help="scoring only")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    a = ap.parse_args()
    out_dir = a.out_dir or a.output.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    syms = Symbols(a.binary, a.nm)
    calls_by_ret, indegree, ncalls_func = parse_calls(a.binary, a.objdump, syms)
    caller_re, callee_re, excl_re = re.compile(a.caller_regex), re.compile(a.callee_regex), re.compile(a.exclude_regex)
    plt = {x.strip() for x in a.plt_callees.split(",") if x.strip()}
    size_of = {}
    for addr, size, name in zip(syms.addrs, syms.sizes, syms.names):
        size_of.setdefault(name, size)

    selected = []
    n_caller = 0
    for ret_addr, rec in calls_by_ret.items():
        caller = rec["caller"]
        if not caller_re.search(caller) or excl_re.search(caller):
            continue
        n_caller += 1
        callee = rec["callee"]
        long_call = False
        callee_size = 0
        if not rec["callee_known"]:
            base = callee.split("@", 1)[0]
            if base in plt:
                long_call = True
                callee_size = 1 << 20  # rank libc calls first
        else:
            if excl_re.search(callee):
                continue
            callee_size = size_of.get(callee, 0)
            if callee_re.search(callee) and callee_size >= a.min_callee_size:
                long_call = True
        if not long_call:
            continue
        selected.append({"call_addr": rec["call_addr"], "ret_addr": ret_addr, "caller": caller, "callee": callee,
                         "callee_size": callee_size, "callee_known": rec["callee_known"]})
    selected.sort(key=lambda r: (-r["callee_size"], r["call_addr"]))
    if a.top_k:
        selected = selected[: a.top_k]
    print(f"[ok] calls in steady-state callers: {n_caller}; selected long calls: {len(selected)} "
          f"(plt={sum(1 for r in selected if not r['callee_known'])})")

    # ---- optional scoring against the producing-call truth
    if a.trace_dir:
        import subprocess
        truth_dir = out_dir / "truth"
        subprocess.run([sys.executable, str(HERE / "ret_producing_call_truth.py"), "--binary", str(a.binary), "--out-dir", str(truth_dir),
                        *[x for t in a.trace_dir for x in ("--trace-dir", str(t))]], check=True, stdout=subprocess.DEVNULL)
        truth = {int(r["call_addr"], 16): int(r["samples"]) for r in csv.DictReader((truth_dir / "ret_producing_calls.csv").open())}
        tot = sum(truth.values())
        sel = {r["call_addr"] for r in selected}
        hit = sum(v for k, v in truth.items() if k in sel)
        print(f"[score] producing-call coverage: {100 * hit / tot:.1f}% of RET samples ({len(sel & set(truth))} of {len(truth)} producing calls selected; "
              f"precision {100 * len(sel & set(truth)) / max(1, len(sel)):.1f}% of selected calls produce misses)")
        miss = Counter()
        for k, v in truth.items():
            if k not in sel:
                rec = calls_by_ret.get(next((ra for ra, rr in calls_by_ret.items() if rr["call_addr"] == k), None))
                if rec:
                    miss[("known" if rec["callee_known"] else "plt") + ":" + rec["callee"][:40] + f" size={size_of.get(rec['callee'], 0)}"] += v
        print("[score] largest uncovered producing calls: " + "; ".join(f"{k} ({v})" for k, v in miss.most_common(5)))

    # ---- emit prefetchit.plan.v1 (site = the call, target = its continuation, offsets 0..64*(lines-1))
    symidx = build_symbol_index(a.binary, a.nm)
    addrs = sorted({r["call_addr"] for r in selected} | {r["ret_addr"] for r in selected})
    locs = resolve_addrs(a.binary, a.addr2line, addrs)
    injections = []
    for rank, r in enumerate(selected, 1):
        tsym = symidx.symbol_at(r["ret_addr"])
        ssym = symidx.symbol_at(r["call_addr"])
        if tsym is None or ssym is None:
            continue
        site = source_obj(ssym, r["call_addr"], locs[r["call_addr"]])
        site.update({"branch_type": "CALL", "lbr_depth": 0, "site_kind": "callsite"})
        injections.append({"target_rank": rank, "site_rank": 1, "samples": 0, "new_covered_samples": 0,
                           "cumulative_coverage_pct": 0.0, "prefetch_mnemonic": a.prefetch_mnemonic,
                           "target": source_obj(tsym, r["ret_addr"], locs[r["ret_addr"]]), "site": site,
                           "static_v3": {"callee": r["callee"], "callee_size": r["callee_size"]}})
    offsets = [64 * k for k in range(a.lines)]
    plan = {"schema": "prefetchit.plan.v1", "prefetch_mnemonic": a.prefetch_mnemonic,
            "prefetch": {"mnemonic": a.prefetch_mnemonic, "operand": "pc-relative-symbol-offset", "byte_offsets": offsets},
            "options": {"source": "static_ret_v3", "label": a.label, "caller_regex": a.caller_regex, "callee_regex": a.callee_regex,
                        "min_callee_size": a.min_callee_size, "plt_callees": sorted(plt), "top_k": a.top_k, "lines": a.lines},
            "stats": {"selected_injections": len(injections), "planned_prefetches": len(injections) * len(offsets)},
            "injections": injections}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
    with (out_dir / f"{a.label}_selected_calls.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["call_addr", "ret_addr", "caller", "callee", "callee_size", "callee_known"])
        w.writeheader()
        for r in selected:
            w.writerow({**r, "call_addr": hex(r["call_addr"]), "ret_addr": hex(r["ret_addr"])})
    print(f"[ok] wrote {a.output}: {len(injections)} injections x {len(offsets)} lines = {len(injections) * len(offsets)} prefetches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
