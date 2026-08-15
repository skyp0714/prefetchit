#!/usr/bin/env python3
"""Sweep profile-free static target algorithms against a PGO RET-only oracle.

The oracle is used only for evaluation.  Candidate generation uses binary
structure plus the existing static callsite feature CSV.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from static_branch_target_plan import parse_functions  # noqa: E402
from static_site_plan_to_prefetch_plan import build_symbol_index, parse_int  # noqa: E402


@dataclass(frozen=True)
class TruthTarget:
    rank: int
    samples: int
    function: str
    addr: int
    cacheline: int
    line: int


@dataclass
class StaticRow:
    rank: int
    score: float
    target_function: str
    target_addr: int
    target_cacheline: int
    callee_function: str
    caller_size: int
    callee_size: int
    caller_cachelines: int
    callee_cachelines: int
    caller_call_count: int
    caller_backedges: int
    callee_backedges: int
    call_in_loop: int
    loop_depth_est: int
    depth_from_root: int
    depth_down: int
    possible_chain_depth: int
    ras_overflow: int
    loop_hot_reachable: int
    loop_hot_distance: int
    layout_distance_kb: float
    continuation_pos: float


@dataclass
class Candidate:
    function: str
    cacheline: int
    addr: int
    score: float
    source: str
    evidence_count: int = 1


def read_truth(path: Path) -> list[TruthTarget]:
    out: list[TruthTarget] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                TruthTarget(
                    rank=int(row["rank"]),
                    samples=int(row["samples"]),
                    function=row["function"],
                    addr=parse_int(row["addr"]),
                    cacheline=parse_int(row["cacheline64"]),
                    line=int(row.get("line") or 0),
                )
            )
    return out


def read_static_rows(path: Path) -> list[StaticRow]:
    rows: list[StaticRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                StaticRow(
                    rank=int(row["rank"]),
                    score=float(row["score"]),
                    target_function=row["target_function"],
                    target_addr=parse_int(row["target_addr"]),
                    target_cacheline=parse_int(row["target_cacheline64"]),
                    callee_function=row["callee_function"],
                    caller_size=int(float(row["caller_size_bytes"])),
                    callee_size=int(float(row["callee_size_bytes"])),
                    caller_cachelines=int(float(row["caller_cachelines"])),
                    callee_cachelines=int(float(row["callee_cachelines"])),
                    caller_call_count=int(float(row["caller_call_count"])),
                    caller_backedges=int(float(row["caller_backedges"])),
                    callee_backedges=int(float(row["callee_backedges"])),
                    call_in_loop=int(float(row["call_in_loop"])),
                    loop_depth_est=int(float(row["loop_depth_est"])),
                    depth_from_root=int(float(row["depth_from_root"])),
                    depth_down=int(float(row["depth_down"])),
                    possible_chain_depth=int(float(row["possible_chain_depth"])),
                    ras_overflow=int(float(row["ras_overflow"])),
                    loop_hot_reachable=int(float(row["loop_hot_reachable"])),
                    loop_hot_distance=int(float(row["loop_hot_distance"])),
                    layout_distance_kb=float(row["layout_distance_kb"]),
                    continuation_pos=float(row["continuation_pos"]),
                )
            )
    return rows


def row_cost(row: StaticRow, mode: str) -> float:
    caller = math.log2(row.caller_cachelines + 1)
    callee = math.log2(row.callee_cachelines + 1)
    fanout = math.log2(row.caller_call_count + 1)
    loops = (
        (1.0 if row.call_in_loop else 0.0)
        + 0.8 * math.log2(row.loop_depth_est + 1)
        + 0.5 * math.log2(row.caller_backedges + row.callee_backedges + 1)
    )
    depth = math.log2(row.depth_down + 1) + 3.0 * min(row.ras_overflow, 16)
    hot = 1.0 / (1.0 + min(row.loop_hot_distance, 64)) if row.loop_hot_reachable else -1.0
    layout = math.log2(row.layout_distance_kb + 1)
    if mode == "existing":
        return row.score
    if mode == "footprint":
        return 5.0 * caller + 6.0 * callee + 1.0 * fanout + 1.0 * layout + 20.0 * hot
    if mode == "depth":
        return 20.0 * depth + 2.0 * callee + 10.0 * hot
    if mode == "loop":
        return 40.0 * hot + 8.0 * loops + 3.0 * callee + 1.0 * caller
    if mode == "caller":
        return 8.0 * caller + 2.0 * fanout + 2.0 * loops + 10.0 * hot
    if mode == "balanced":
        return (
            4.0 * caller
            + 4.0 * callee
            + 1.0 * fanout
            + 2.0 * loops
            + 2.0 * layout
            + 8.0 * hot
            + 6.0 * min(row.ras_overflow, 8)
        )
    raise ValueError(f"unknown cost mode {mode}")


def add_candidate(
    acc: dict[tuple[str, int], Candidate],
    function: str,
    addr: int,
    score: float,
    source: str,
    aggregate: str,
) -> None:
    cacheline = addr & ~0x3F
    key = (function, cacheline)
    prev = acc.get(key)
    if prev is None:
        acc[key] = Candidate(function=function, cacheline=cacheline, addr=addr, score=score, source=source)
        return
    prev.evidence_count += 1
    if aggregate == "sum":
        prev.score += score
    elif aggregate == "max":
        if score > prev.score:
            prev.score = score
            prev.addr = addr
            prev.source = source
    else:
        raise ValueError(f"unknown aggregate {aggregate}")


def sorted_candidates(acc: dict[tuple[str, int], Candidate], max_targets: int) -> list[Candidate]:
    out = sorted(acc.values(), key=lambda c: (c.score, c.evidence_count, -c.cacheline), reverse=True)
    return out[:max_targets] if max_targets else out


def merge_candidate_lists(label: str, lists: list[list[Candidate]], max_targets: int, scale: list[float] | None = None) -> list[Candidate]:
    acc: dict[tuple[str, int], Candidate] = {}
    if scale is None:
        scale = [1.0] * len(lists)
    for idx, cands in enumerate(lists):
        factor = scale[idx] if idx < len(scale) else 1.0
        for cand in cands:
            add_candidate(acc, cand.function, cand.addr, cand.score * factor, f"{label}:{cand.source}", "sum")
    return sorted_candidates(acc, max_targets)


def concat_candidate_lists(label: str, lists: list[list[Candidate]], max_targets: int) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[tuple[str, int]] = set()
    for cands in lists:
        for cand in cands:
            key = (cand.function, cand.cacheline)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Candidate(
                    function=cand.function,
                    cacheline=cand.cacheline,
                    addr=cand.addr,
                    score=cand.score,
                    source=f"{label}:{cand.source}",
                    evidence_count=cand.evidence_count,
                )
            )
            if max_targets and len(out) >= max_targets:
                return out
    return out


def generate_return_only(rows: list[StaticRow], cost_mode: str, max_targets: int) -> list[Candidate]:
    acc: dict[tuple[str, int], Candidate] = {}
    for row in rows:
        add_candidate(acc, row.target_function, row.target_addr, row_cost(row, cost_mode), "retaddr", "max")
    return sorted_candidates(acc, max_targets)


def iter_window_addrs(center: int, window_bytes: int, direction: str) -> Iterable[tuple[int, int]]:
    step = 64
    center_cl = center & ~0x3F
    if direction == "forward":
        start, end = center_cl, (center + window_bytes) & ~0x3F
    elif direction == "backward":
        start, end = (center - window_bytes) & ~0x3F, center_cl
    elif direction == "bidir":
        start, end = (center - window_bytes) & ~0x3F, (center + window_bytes) & ~0x3F
    else:
        raise ValueError(f"bad direction {direction}")
    addr = start
    while addr <= end:
        yield addr, abs(addr - center_cl)
        addr += step


def generate_return_window(
    rows: list[StaticRow],
    cost_mode: str,
    window_bytes: int,
    direction: str,
    decay_bytes: int,
    source_rows: int,
    max_targets: int,
    aggregate: str,
) -> list[Candidate]:
    acc: dict[tuple[str, int], Candidate] = {}
    ranked = sorted(rows, key=lambda r: row_cost(r, cost_mode), reverse=True)
    if source_rows:
        ranked = ranked[:source_rows]
    for row in ranked:
        base = row_cost(row, cost_mode)
        func_start = int(row.target_addr - row.continuation_pos * max(row.caller_size, 1)) & ~0x3F
        func_end = func_start + max(row.caller_size, 1)
        for addr, dist in iter_window_addrs(row.target_addr, window_bytes, direction):
            if addr < func_start or addr >= func_end:
                continue
            weight = 1.0 if decay_bytes <= 0 else 1.0 / (1.0 + dist / max(decay_bytes, 1))
            add_candidate(acc, row.target_function, addr, base * weight, f"{direction}{window_bytes}", aggregate)
    return sorted_candidates(acc, max_targets)


def generate_body_near_returns(
    rows: list[StaticRow],
    cost_mode: str,
    window_bytes: int,
    source_rows: int,
    max_targets: int,
) -> list[Candidate]:
    # This is a wider variant: high-risk callers contribute their whole body,
    # while lines near many high-risk returns receive higher rank.
    by_func: dict[str, list[StaticRow]] = defaultdict(list)
    ranked = sorted(rows, key=lambda r: row_cost(r, cost_mode), reverse=True)
    if source_rows:
        ranked = ranked[:source_rows]
    for row in ranked:
        by_func[row.target_function].append(row)

    acc: dict[tuple[str, int], Candidate] = {}
    for func, func_rows in by_func.items():
        # Infer a conservative body range from call return addresses and caller size.
        size = max(r.caller_size for r in func_rows)
        min_ret = min(r.target_addr for r in func_rows)
        # Continuation position gives approximate function start; median is robust
        # against malformed zero-size rows.
        starts = [int(r.target_addr - r.continuation_pos * max(r.caller_size, 1)) for r in func_rows]
        starts.sort()
        start = starts[len(starts) // 2] & ~0x3F
        end = (start + size) & ~0x3F
        if end <= start:
            end = (min_ret + size) & ~0x3F
        func_base = max(row_cost(r, cost_mode) for r in func_rows)
        # Bucket return-site evidence by cacheline, then smear by a static window.
        for row in func_rows:
            base = row_cost(row, cost_mode)
            for addr, dist in iter_window_addrs(row.target_addr, window_bytes, "bidir"):
                if addr < start or addr > end:
                    continue
                add_candidate(acc, func, addr, base / (1.0 + dist / 4096.0), f"body_near_ret_{window_bytes}", "sum")
        # Fill uncovered cachelines from the same hot body with a lower score.
        addr = start
        fill_score = 0.01 * func_base
        while addr <= end:
            add_candidate(acc, func, addr, fill_score, "body_fill", "sum")
            addr += 64
    return sorted_candidates(acc, max_targets)


def function_hot_scores(rows: list[StaticRow], cost_mode: str, top_rows: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    counts: Counter[str] = Counter()
    ranked = sorted(rows, key=lambda r: row_cost(r, cost_mode), reverse=True)
    if top_rows:
        ranked = ranked[:top_rows]
    for row in ranked:
        counts[row.target_function] += 1
        scores[row.target_function] = max(scores.get(row.target_function, float("-inf")), row_cost(row, cost_mode))
    for func, count in counts.items():
        scores[func] += 0.2 * math.log2(count + 1)
    return scores


def generate_role_body_targets(
    binary: Path,
    rows: list[StaticRow],
    cost_mode: str,
    role: str,
    source_rows: int,
    max_targets: int,
    nm: str,
) -> list[Candidate]:
    symbols = build_symbol_index(binary, nm)
    by_name = {sym.demangled: sym for sym in symbols.symbols}
    ranked = sorted(rows, key=lambda r: row_cost(r, cost_mode), reverse=True)
    if source_rows:
        ranked = ranked[:source_rows]
    scores: dict[str, float] = defaultdict(float)
    evidence: Counter[str] = Counter()
    for row in ranked:
        if role == "caller":
            func = row.target_function
        elif role == "callee":
            func = row.callee_function
        else:
            raise ValueError(f"bad role {role}")
        if func not in by_name:
            continue
        scores[func] += row_cost(row, cost_mode)
        evidence[func] += 1
    acc: dict[tuple[str, int], Candidate] = {}
    for func, score in scores.items():
        sym = by_name.get(func)
        if sym is None or sym.size <= 0:
            continue
        func_score = score + 0.5 * math.log2(evidence[func] + 1) + math.log2(sym.size + 1)
        start = sym.addr & ~0x3F
        end = (sym.addr + sym.size - 1) & ~0x3F
        addr = start
        while addr <= end:
            add_candidate(acc, func, addr, func_score, f"{role}_body", "sum")
            addr += 64
    return sorted_candidates(acc, max_targets)


def verilator_hot_category(name: str) -> int:
    # Verilator generated simulators expose stable phase names.  This is still
    # profile-free: the ranking uses symbol names and static sizes only.
    if "VTestDriver___024root___eval_nba" in name:
        return 1000
    if "VTestDriver___024root___nba_sequent__TOP__" in name:
        return 900
    if "VTestDriver___024root___nba_comb__TOP__" in name:
        return 850
    if "VlDelayScheduler::resume" in name:
        return 800
    if "VTestDriver___024root___eval_act" in name:
        return 750
    if "VTestDriver___024root___eval_stl" in name:
        return 700
    if "VTestDriver___024root___eval" in name:
        return 600
    if "VTestDriver___024root___" in name and "__TOP__" in name:
        return 500
    return 0


def generate_verilator_hot_name_body_targets(binary: Path, max_targets: int, nm: str) -> list[Candidate]:
    symbols = build_symbol_index(binary, nm)
    acc: dict[tuple[str, int], Candidate] = {}
    selected = []
    for sym in symbols.symbols:
        cat = verilator_hot_category(sym.demangled)
        if cat <= 0 or sym.size <= 0:
            continue
        selected.append((cat + math.log2(sym.size + 1), sym))
    selected.sort(key=lambda x: (x[0], x[1].size), reverse=True)
    for score, sym in selected:
        addr = sym.addr & ~0x3F
        end = (sym.addr + sym.size - 1) & ~0x3F
        while addr <= end:
            add_candidate(acc, sym.demangled, addr, score, "verilator_hot_body", "sum")
            addr += 64
    return sorted_candidates(acc, max_targets)


def generate_branch_targets(
    binary: Path,
    rows: list[StaticRow],
    cost_mode: str,
    top_rows: int,
    top_functions: int,
    neighbor_lines: int,
    max_targets: int,
    nm: str,
    objdump: str,
) -> list[Candidate]:
    symbols = build_symbol_index(binary, nm)
    bodies = parse_functions(binary, symbols, objdump)
    hot = function_hot_scores(rows, cost_mode, top_rows)
    funcs = sorted(hot, key=lambda fn: hot[fn], reverse=True)[:top_functions]
    acc: dict[tuple[str, int], Candidate] = {}
    for func in funcs:
        body = bodies.get(func)
        if body is None:
            continue
        base = hot[func] + math.log2(body.sym.size + 1)
        for br in body.branches:
            targets: list[int] = []
            if br.target_addr is not None:
                targets.append(br.target_addr)
            if br.fallthrough_addr is not None:
                targets.append(br.fallthrough_addr)
            branch_bonus = {"RET": 0.5, "CALL": 1.0, "COND": 1.2, "UNCOND": 0.9}.get(br.branch_type, 0.0)
            for target in targets:
                target_sym = symbols.symbol_at(target)
                if target_sym is None:
                    continue
                target_func = target_sym.demangled
                for delta in range(-neighbor_lines, neighbor_lines + 1):
                    addr = (target & ~0x3F) + delta * 64
                    add_candidate(acc, target_func, addr, base + branch_bonus - abs(delta) * 0.1, "branch_target", "sum")
    return sorted_candidates(acc, max_targets)


def evaluate(cands: list[Candidate], truth: list[TruthTarget], ks: list[int]) -> list[dict[str, float | int | str]]:
    truth_by_key: Counter[tuple[str, int]] = Counter()
    truth_by_cl: Counter[int] = Counter()
    for t in truth:
        truth_by_key[(t.function, t.cacheline)] += t.samples
        truth_by_cl[t.cacheline] += t.samples
    total = sum(t.samples for t in truth)
    truth_keys = set(truth_by_key)
    truth_cls = set(truth_by_cl)
    ordered_keys: list[tuple[str, int]] = []
    ordered_cls: list[int] = []
    seen_keys: set[tuple[str, int]] = set()
    seen_cls: set[int] = set()
    for c in cands:
        key = (c.function, c.cacheline)
        if key not in seen_keys:
            seen_keys.add(key)
            ordered_keys.append(key)
        if c.cacheline not in seen_cls:
            seen_cls.add(c.cacheline)
            ordered_cls.append(c.cacheline)
    out: list[dict[str, float | int | str]] = []
    for k in ks:
        pred_keys = set(ordered_keys[:k])
        pred_cls = set(ordered_cls[:k])
        hit_weight = sum(v for key, v in truth_by_key.items() if key in pred_keys)
        hit_cl_weight = sum(v for cl, v in truth_by_cl.items() if cl in pred_cls)
        out.append(
            {
                "k": k,
                "pred_targets": min(k, len(ordered_keys)),
                "truth_unique": len(truth_keys),
                "hit_unique": len(truth_keys & pred_keys),
                "weighted_recall": hit_weight / max(1, total),
                "cl_only_weighted_recall": hit_cl_weight / max(1, total),
                "precision": len(truth_keys & pred_keys) / max(1, min(k, len(ordered_keys))),
                "hit_samples": hit_weight,
                "truth_samples": total,
            }
        )
    return out


def write_candidates(path: Path, cands: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        fields = ["rank", "score", "target_function", "target_addr", "target_cacheline64", "source", "evidence_count"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for idx, c in enumerate(cands, 1):
            w.writerow(
                {
                    "rank": idx,
                    "score": f"{c.score:.8f}",
                    "target_function": c.function,
                    "target_addr": f"0x{c.addr:x}",
                    "target_cacheline64": f"0x{c.cacheline:x}",
                    "source": c.source,
                    "evidence_count": c.evidence_count,
                }
            )


def write_missing(path: Path, cands: list[Candidate], truth: list[TruthTarget], k: int) -> None:
    pred = {(c.function, c.cacheline) for c in cands[:k]}
    misses = [t for t in truth if (t.function, t.cacheline) not in pred]
    misses.sort(key=lambda t: t.samples, reverse=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        fields = ["profile_rank", "samples", "function", "addr", "cacheline64", "line"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in misses[:1000]:
            w.writerow(
                {
                    "profile_rank": t.rank,
                    "samples": t.samples,
                    "function": t.function,
                    "addr": f"0x{t.addr:x}",
                    "cacheline64": f"0x{t.cacheline:x}",
                    "line": t.line,
                }
            )


def write_summary_md(path: Path, rows: list[dict[str, float | int | str]], best_by_k: dict[int, dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Static RET Target Algorithm Sweep\n\n")
        f.write("Oracle: PGO RET-only selected targets. Candidate generation is profile-free.\n\n")
        f.write("## Best By Target Budget\n\n")
        f.write("| K | Variant | Weighted Recall | CL-only Recall | Precision | Hit Samples | Truth Samples |\n")
        f.write("|---:|---|---:|---:|---:|---:|---:|\n")
        for k in sorted(best_by_k):
            r = best_by_k[k]
            f.write(
                f"| {k} | {r['variant']} | {float(r['weighted_recall']):.2%} | "
                f"{float(r['cl_only_weighted_recall']):.2%} | {float(r['precision']):.2%} | "
                f"{int(r['hit_samples'])} | {int(r['truth_samples'])} |\n"
            )
        f.write("\n## All Variants\n\n")
        f.write("| Variant | K | Weighted Recall | CL-only Recall | Precision | Pred Targets |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for r in rows:
            f.write(
                f"| {r['variant']} | {int(r['k'])} | {float(r['weighted_recall']):.2%} | "
                f"{float(r['cl_only_weighted_recall']):.2%} | {float(r['precision']):.2%} | {int(r['pred_targets'])} |\n"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--static-candidates", type=Path, required=True)
    ap.add_argument("--pgo-ret-targets", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--k", default="1000,5000,10000,25000,50000,75000,100000,150000,250000")
    ap.add_argument("--max-targets", type=int, default=250000)
    ap.add_argument("--variant-set", choices=("quick", "full"), default="quick")
    ap.add_argument("--include-branch", action="store_true", help="include objdump branch-target variants")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    args = ap.parse_args()

    ks = [int(x) for x in args.k.split(",") if x.strip()]
    truth = read_truth(args.pgo_ret_targets)
    rows = read_static_rows(args.static_candidates)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    variants: list[tuple[str, list[Candidate]]] = []
    for cost in ("existing", "balanced", "footprint", "loop", "depth", "caller"):
        variants.append((f"retaddr_{cost}", generate_return_only(rows, cost, args.max_targets)))

    if args.variant_set == "quick":
        window_specs = [
            ("fw32_top10k", 32 * 1024, "forward", 0, 10000, "sum"),
            ("fw32_top50k", 32 * 1024, "forward", 0, 50000, "sum"),
            ("fw32_top100k", 32 * 1024, "forward", 0, 100000, "sum"),
            ("fw64_top50k", 64 * 1024, "forward", 0, 50000, "sum"),
            ("bi32_top50k", 32 * 1024, "bidir", 0, 50000, "sum"),
        ]
        window_costs = ("existing", "balanced")
    else:
        window_specs = [
            ("fw16", 16 * 1024, "forward", 0, 100000, "sum"),
            ("fw32", 32 * 1024, "forward", 0, 100000, "sum"),
            ("fw64", 64 * 1024, "forward", 0, 100000, "sum"),
            ("fw32_decay4k", 32 * 1024, "forward", 4 * 1024, 100000, "sum"),
            ("fw32_decay16k", 32 * 1024, "forward", 16 * 1024, 100000, "sum"),
            ("bi16", 16 * 1024, "bidir", 0, 100000, "sum"),
            ("bi32", 32 * 1024, "bidir", 0, 100000, "sum"),
            ("bi64", 64 * 1024, "bidir", 0, 50000, "sum"),
            ("fw32_top10k", 32 * 1024, "forward", 0, 10000, "sum"),
            ("fw32_top50k", 32 * 1024, "forward", 0, 50000, "sum"),
        ]
        window_costs = ("existing", "balanced", "caller")
    for name, window, direction, decay, source_rows, aggregate in window_specs:
        for cost in window_costs:
            variants.append(
                (
                    f"{name}_{cost}",
                    generate_return_window(
                        rows,
                        cost,
                        window,
                        direction,
                        decay,
                        source_rows,
                        args.max_targets,
                        aggregate,
                    ),
                )
            )

    body_costs = ("existing", "balanced") if args.variant_set == "quick" else ("existing", "balanced", "caller")
    verilator_hot_body = generate_verilator_hot_name_body_targets(args.binary, args.max_targets, args.nm)
    variants.append(("verilator_hot_name_body", verilator_hot_body))
    fw32_top10k_existing = next((cands for name, cands in variants if name == "fw32_top10k_existing"), [])
    variants.append(("fw32_top10k_then_verilator_hot_body", concat_candidate_lists("fw_then_verilator_hot", [fw32_top10k_existing, verilator_hot_body], args.max_targets)))
    for cost in body_costs:
        body_near = generate_body_near_returns(rows, cost, 32 * 1024, 100000, args.max_targets)
        callee_body = generate_role_body_targets(args.binary, rows, cost, "callee", 100000, args.max_targets, args.nm)
        caller_body = generate_role_body_targets(args.binary, rows, cost, "caller", 100000, args.max_targets, args.nm)
        callee_body_all = generate_role_body_targets(args.binary, rows, cost, "callee", 0, args.max_targets, args.nm)
        caller_body_all = generate_role_body_targets(args.binary, rows, cost, "caller", 0, args.max_targets, args.nm)
        variants.append((f"body_near32_{cost}", body_near))
        variants.append((f"callee_body_{cost}", callee_body))
        variants.append((f"caller_body_{cost}", caller_body))
        variants.append((f"callee_body_all_{cost}", callee_body_all))
        variants.append((f"caller_body_all_{cost}", caller_body_all))
        variants.append((f"body_near32_plus_callee_body_{cost}", merge_candidate_lists("near_plus_callee", [body_near, callee_body], args.max_targets, [1.0, 1.0])))
        variants.append((f"body_near32_plus_caller_callee_body_{cost}", merge_candidate_lists("near_plus_bodies", [body_near, caller_body, callee_body], args.max_targets, [1.0, 0.2, 1.0])))
        variants.append((f"body_near32_plus_callee_body_all_{cost}", merge_candidate_lists("near_plus_callee_all", [body_near, callee_body_all], args.max_targets, [1.0, 1.0])))
        variants.append((f"body_near32_plus_all_bodies_{cost}", merge_candidate_lists("near_plus_all_bodies", [body_near, caller_body_all, callee_body_all], args.max_targets, [1.0, 0.2, 1.0])))
        variants.append((f"fw32_top10k_plus_verilator_hot_body_{cost}", merge_candidate_lists("fw_plus_verilator_hot", [fw32_top10k_existing, verilator_hot_body], args.max_targets, [1.0, 1.0])))
        if args.variant_set == "full":
            variants.append((f"body_near64_{cost}", generate_body_near_returns(rows, cost, 64 * 1024, 50000, args.max_targets)))

    if args.include_branch:
        branch_costs = ("existing",) if args.variant_set == "quick" else ("existing", "balanced", "caller")
        for cost in branch_costs:
            variants.append(
                (
                    f"branch_hot_f50_n1_{cost}",
                    generate_branch_targets(args.binary, rows, cost, 100000, 50, 1, args.max_targets, args.nm, args.objdump),
                )
            )
            if args.variant_set == "full":
                variants.append(
                    (
                        f"branch_hot_f100_n2_{cost}",
                        generate_branch_targets(args.binary, rows, cost, 100000, 100, 2, args.max_targets, args.nm, args.objdump),
                    )
                )

    all_metrics: list[dict[str, float | int | str]] = []
    best_by_k: dict[int, dict[str, float | int | str]] = {}
    cand_dir = args.out_dir / "candidate_targets"
    for name, cands in variants:
        write_candidates(cand_dir / f"{name}.csv", cands)
        metrics = evaluate(cands, truth, ks)
        for metric in metrics:
            metric = dict(metric)
            metric["variant"] = name
            all_metrics.append(metric)
            k = int(metric["k"])
            prev = best_by_k.get(k)
            if prev is None or float(metric["weighted_recall"]) > float(prev["weighted_recall"]):
                best_by_k[k] = metric

    with (args.out_dir / "algorithm_sweep_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "variant",
            "k",
            "pred_targets",
            "truth_unique",
            "hit_unique",
            "weighted_recall",
            "cl_only_weighted_recall",
            "precision",
            "hit_samples",
            "truth_samples",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_metrics)

    write_summary_md(args.out_dir / "algorithm_sweep_summary.md", all_metrics, best_by_k)
    for k, row in best_by_k.items():
        variant = str(row["variant"])
        cands = next(c for name, c in variants if name == variant)
        write_missing(args.out_dir / f"missing_best_k{k}.csv", cands, truth, k)

    print(f"[ok] wrote {args.out_dir / 'algorithm_sweep_metrics.csv'}")
    print(f"[ok] wrote {args.out_dir / 'algorithm_sweep_summary.md'}")
    for k in sorted(best_by_k):
        r = best_by_k[k]
        print(
            f"[best] k={k} variant={r['variant']} weighted_recall={float(r['weighted_recall']):.4f} "
            f"precision={float(r['precision']):.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
