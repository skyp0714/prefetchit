#!/usr/bin/env python3
"""Build static RET-site plans that prefetch a forward window after returns.

PGO "RET" experiments use RET branches as injection sites, but their target is
the later LBR[0].to miss target, not necessarily the immediate return address.
This generator is the static analogue: for high-risk callsites, use callee RETs
as injection sites and prefetch cachelines in the caller after the return
continuation.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from static_branch_target_plan import parse_functions
from static_site_plan_to_prefetch_plan import (
    Loc,
    build_symbol_index,
    parse_offsets,
    parse_int,
    resolve_addrs,
    source_obj,
)


def read_target_rows(path: Path, top_k: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for idx, row in enumerate(csv.DictReader(f), 1):
            if top_k and idx > top_k:
                break
            rows.append(row)
    return rows


def cacheline_targets(return_addr: int, window_bytes: int, max_lines: int) -> list[int]:
    start = return_addr & ~0x3F
    end = (return_addr + window_bytes) & ~0x3F
    out: list[int] = []
    addr = start
    while addr <= end:
        out.append(addr)
        if max_lines and len(out) >= max_lines:
            break
        addr += 64
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--label", default="static_return_window")
    ap.add_argument("--top-k", type=int, default=1000)
    ap.add_argument("--window-bytes", type=int, default=4096)
    ap.add_argument("--max-lines-per-call", type=int, default=0)
    ap.add_argument("--ret-site-budget", type=int, default=1, help="0 means all RET sites in callee")
    ap.add_argument(
        "--site-budget-per-target",
        type=int,
        default=0,
        help="0 means unlimited; otherwise cap selected RET sites per target cacheline",
    )
    ap.add_argument("--max-injections", type=int, default=0)
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--prefetch-byte-offsets", default="0,64")
    ap.add_argument("--skip-same-cacheline", action="store_true")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    args = ap.parse_args()

    symbols = build_symbol_index(args.binary, args.nm)
    bodies = parse_functions(args.binary, symbols, args.objdump)
    rows = read_target_rows(args.targets, args.top_k)

    raw: list[tuple[int, int, dict[str, str], int]] = []
    missing_callee = 0
    missing_ret = 0
    for row in rows:
        return_addr = parse_int(row["target_addr"])
        callee = row["callee_function"]
        body = bodies.get(callee)
        if body is None:
            missing_callee += 1
            continue
        ret_sites = [b.addr for b in body.branches if b.branch_type == "RET"]
        if not ret_sites:
            missing_ret += 1
            continue
        if args.ret_site_budget:
            ret_sites = ret_sites[: args.ret_site_budget]
        targets = cacheline_targets(return_addr, args.window_bytes, args.max_lines_per_call)
        for site_addr in ret_sites:
            for target_addr in targets:
                if args.skip_same_cacheline and ((site_addr & ~0x3F) == (target_addr & ~0x3F)):
                    continue
                raw.append((site_addr, target_addr, row, return_addr))

    seen: set[tuple[int, int]] = set()
    sites_by_target: dict[int, int] = {}
    selected: list[tuple[int, int, dict[str, str], int]] = []
    for item in raw:
        site_addr, target_addr, _row, _return_addr = item
        target_cl = target_addr & ~0x3F
        if args.site_budget_per_target and sites_by_target.get(target_cl, 0) >= args.site_budget_per_target:
            continue
        key = (site_addr, target_cl)
        if key in seen:
            continue
        seen.add(key)
        sites_by_target[target_cl] = sites_by_target.get(target_cl, 0) + 1
        selected.append(item)
        if args.max_injections and len(selected) >= args.max_injections:
            break

    addrs = {site for site, _target, _row, _ret in selected}
    addrs |= {target for _site, target, _row, _ret in selected}
    locs = resolve_addrs(args.binary, args.addr2line, sorted(addrs))

    injections: list[dict[str, Any]] = []
    missing_symbol = 0
    target_rank: dict[int, int] = {}
    site_rank_by_target: dict[int, int] = {}
    for site_addr, target_addr, row, return_addr in selected:
        site_sym = symbols.symbol_at(site_addr)
        target_sym = symbols.symbol_at(target_addr)
        if site_sym is None or target_sym is None:
            missing_symbol += 1
            continue
        target_cl = target_addr & ~0x3F
        if target_cl not in target_rank:
            target_rank[target_cl] = len(target_rank) + 1
        site_rank_by_target[target_cl] = site_rank_by_target.get(target_cl, 0) + 1

        site = source_obj(site_sym, site_addr, locs.get(site_addr, Loc("", "", 0)))
        site.update(
            {
                "branch_type": "RET",
                "lbr_depth": 0,
                "site_kind": f"static-return-window-{args.window_bytes}",
                "static_return_addr": hex(return_addr),
                "static_callee_function": row["callee_function"],
            }
        )
        injections.append(
            {
                "target_rank": target_rank[target_cl],
                "site_rank": site_rank_by_target[target_cl],
                "samples": 0,
                "new_covered_samples": 0,
                "cumulative_coverage_pct": 0.0,
                "prefetch_mnemonic": args.prefetch_mnemonic,
                "target": source_obj(target_sym, target_addr, locs.get(target_addr, Loc("", "", 0))),
                "site": site,
            }
        )

    byte_offsets = parse_offsets(args.prefetch_byte_offsets)
    plan = {
        "schema": "prefetchit.plan.v1",
        "prefetch_mnemonic": args.prefetch_mnemonic,
        "prefetch": {
            "mnemonic": args.prefetch_mnemonic,
            "operand": "pc-relative-symbol-offset",
            "byte_offsets": byte_offsets,
        },
        "options": {
            "source": "static_return_window_plan",
            "label": args.label,
            "target_csv": str(args.targets),
            "top_k": args.top_k,
            "window_bytes": args.window_bytes,
            "max_lines_per_call": args.max_lines_per_call,
            "ret_site_budget": args.ret_site_budget,
            "site_budget_per_target": args.site_budget_per_target,
            "max_injections": args.max_injections,
        },
        "stats": {
            "input_rows": len(rows),
            "missing_callee": missing_callee,
            "missing_ret": missing_ret,
            "raw_pairs": len(raw),
            "missing_symbol": missing_symbol,
            "selected_injections": len(injections),
            "planned_prefetches": len(injections) * len(byte_offsets),
            "selected_target_cachelines": len({int(i["target"]["cacheline64"], 16) for i in injections}),
            "unique_sites": len({(i["site"]["mangled"], i["site"]["symbol_offset"]) for i in injections}),
        },
        "injections": injections,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(plan, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"), sort_keys=True)
    args.output.write_text(text + "\n", encoding="utf-8")
    print(f"[ok] wrote {args.output}")
    for key, value in plan["stats"].items():
        print(f"[ok] {key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
