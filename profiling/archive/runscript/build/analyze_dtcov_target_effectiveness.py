#!/usr/bin/env python3
import argparse
import csv
import importlib.util
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args():
    ap = argparse.ArgumentParser(
        description="Compare optimized L2 LBR[0].to samples against intended dtcov prefetch targets."
    )
    ap.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    ap.add_argument(
        "--eval-root",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/prefetchit_eval_dtcov_v1/20260531_121556"),
    )
    ap.add_argument(
        "--variant-root",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/prefetch_dtcov_variants_v1"),
    )
    ap.add_argument(
        "--trace-base",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/trace_dtcov_v1"),
    )
    ap.add_argument("--max-cycles", default="538240")
    ap.add_argument("--out-dir", default="")
    return ap.parse_args()


def load_prepare(repo_root: Path):
    path = repo_root / "profiling/runscript/build/prepare_prefetch_exact_variants.py"
    spec = importlib.util.spec_from_file_location("prepare_prefetch_exact_variants", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def parse_hex(raw: str) -> int:
    s = str(raw).strip()
    if not s:
        return 0
    return int(s, 16) if s.startswith("0x") else int(s)


def fmt_hex(raw: int | None) -> str:
    return "" if raw is None else f"0x{raw:x}"


def pct(num: float, den: float) -> float:
    return (100.0 * num / den) if den else 0.0


def percentile(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    idx = round((len(sorted_vals) - 1) * q / 100.0)
    return sorted_vals[idx]


def parse_nm_addresses(binary: Path):
    import subprocess
    raw = subprocess.run(["nm", "-an", str(binary)], check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                out[parts[2]] = int(parts[0], 16)
            except ValueError:
                pass
    return out


def build_intended_targets(prep, binary: Path, target_meta: dict, point_rows: list[dict]):
    addr_by_dem, _ = prep.build_symbol_maps(binary)
    nm_raw = parse_nm_addresses(binary)

    targets = {}
    missing = []
    for row in point_rows:
        tid = row["target_id"]
        if tid in targets:
            continue
        meta = target_meta.get(tid, {})
        kind = row["target_kind"]
        operand_type = row.get("target_operand_type", "").strip()
        sym = row["target_symbol"]
        base = addr_by_dem.get(sym)
        if kind == "line" and operand_type != "symbol_offset":
            label = row["target_label"]
            addr = nm_raw.get(label)
            if addr is None:
                missing.append({"target_id": tid, "reason": "missing_label", "target_label": label})
                continue
            offset = addr - base if base is not None else None
            operand_type = "label"
        else:
            adjusted = row.get("target_adjusted_offset", "").strip()
            if adjusted:
                offset = parse_hex(adjusted)
            else:
                offset = parse_hex(row.get("target_primary_offset", "0"))
            if base is None:
                missing.append({"target_id": tid, "reason": "missing_symbol_base", "target_symbol": sym})
                continue
            addr = base + offset
            operand_type = "symbol_offset"
        try:
            primary_offset = parse_hex(row.get("target_primary_offset", "0"))
        except Exception:
            primary_offset = None

        targets[tid] = {
            "target_id": tid,
            "target_rank": int(row["target_rank"]),
            "target_kind": kind,
            "target_reason": row.get("target_reason", meta.get("target_reason", "")),
            "target_symbol": sym,
            "target_src_relpath": row.get("target_src_relpath", meta.get("target_src_relpath", "")),
            "target_src_line": int(row.get("target_src_line", meta.get("target_src_line", "0")) or 0),
            "target_count": int(row.get("target_count", meta.get("target_count", "0")) or 0),
            "operand_type": operand_type,
            "intended_addr": addr,
            "intended_offset": offset,
            "target_primary_offset": primary_offset,
            "intended_minus_profiled_offset": (
                None if offset is None or primary_offset is None else int(offset) - int(primary_offset)
            ),
        }
    return targets, missing, addr_by_dem


def nearest_target(sym: str, off: int, targets_by_symbol: dict[str, list[dict]]):
    best = None
    for t in targets_by_symbol.get(sym, []):
        intended = t.get("intended_offset")
        if intended is None:
            continue
        dist = abs(off - int(intended))
        if best is None or dist < best[0]:
            best = (dist, t)
    return best


def parse_trace(prep, lbr_file: Path, addr_by_dem: dict, intended_targets: dict):
    addr_to_tid = defaultdict(list)
    targets_by_symbol = defaultdict(list)
    for tid, target in intended_targets.items():
        addr_to_tid[target["intended_addr"]].append(tid)
        targets_by_symbol[target["target_symbol"]].append(target)

    total = 0
    symbolic = 0
    exact = 0
    near64 = 0
    near256 = 0
    exact_by_tid = Counter()
    near256_by_tid = Counter()
    trace_counts = Counter()
    trace_meta = {}
    branch_counts = Counter()
    matched_reason = Counter()
    matched_kind = Counter()

    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            entries = prep.parse_lbr_entries_limited(raw, 1)
            if not entries:
                continue
            total += 1
            e0 = entries[0]
            sym = e0["to_symbol"]
            off = e0["to_offset"]
            bt = e0["branch_type"]
            branch_counts[bt] += 1
            base = addr_by_dem.get(sym)
            if base is None:
                continue
            symbolic += 1
            addr = base + off
            key = (sym, off, bt)
            trace_counts[key] += 1
            trace_meta[key] = {"symbol": sym, "offset": off, "branch_type": bt, "addr": addr}

            tids = addr_to_tid.get(addr, [])
            if tids:
                exact += 1
                for tid in tids:
                    exact_by_tid[tid] += 1
                    t = intended_targets[tid]
                    matched_reason[t["target_reason"]] += 1
                    matched_kind[t["target_kind"]] += 1

            nearest = nearest_target(sym, off, targets_by_symbol)
            if nearest is not None:
                dist, t = nearest
                if dist <= 64:
                    near64 += 1
                if dist <= 256:
                    near256 += 1
                    near256_by_tid[t["target_id"]] += 1

    top_rows = []
    for rank, ((sym, off, bt), cnt) in enumerate(trace_counts.most_common(80), start=1):
        nearest = nearest_target(sym, off, targets_by_symbol)
        nearest_dist = ""
        nearest_tid = ""
        nearest_rank = ""
        nearest_kind = ""
        nearest_reason = ""
        if nearest is not None:
            nearest_dist, t = nearest
            nearest_tid = t["target_id"]
            nearest_rank = t["target_rank"]
            nearest_kind = t["target_kind"]
            nearest_reason = t["target_reason"]
        top_rows.append(
            {
                "trace_rank": rank,
                "samples": cnt,
                "symbol": sym,
                "offset": f"0x{off:x}",
                "branch_type": bt,
                "is_exact_intended_target": "yes" if (addr_by_dem.get(sym, 0) + off) in addr_to_tid else "no",
                "nearest_intended_distance_bytes": nearest_dist,
                "nearest_target_rank": nearest_rank,
                "nearest_target_kind": nearest_kind,
                "nearest_target_reason": nearest_reason,
                "nearest_target_id": nearest_tid,
            }
        )

    target_rows = []
    for tid, t in sorted(intended_targets.items(), key=lambda kv: kv[1]["target_rank"]):
        target_rows.append(
            {
                "target_rank": t["target_rank"],
                "target_id": tid,
                "target_kind": t["target_kind"],
                "target_reason": t["target_reason"],
                "target_symbol": t["target_symbol"],
                "target_src_relpath": t["target_src_relpath"],
                "target_src_line": t["target_src_line"],
                "profiled_offset": fmt_hex(t.get("target_primary_offset")),
                "intended_offset": f"0x{int(t['intended_offset']):x}" if t["intended_offset"] is not None else "",
                "intended_minus_profiled_offset_bytes": (
                    "" if t.get("intended_minus_profiled_offset") is None else t["intended_minus_profiled_offset"]
                ),
                "abs_intended_minus_profiled_offset_bytes": (
                    "" if t.get("intended_minus_profiled_offset") is None else abs(int(t["intended_minus_profiled_offset"]))
                ),
                "target_baseline_count": t["target_count"],
                "exact_optimized_l2_samples": exact_by_tid[tid],
                "near256_optimized_l2_samples": near256_by_tid[tid],
            }
        )

    summary = {
        "total_l2_trace_samples": total,
        "symbolic_samples": symbolic,
        "intended_target_count": len(intended_targets),
        "exact_intended_samples": exact,
        "near64_intended_samples": near64,
        "near256_intended_samples": near256,
        "exact_pct": pct(exact, total),
        "near64_pct": pct(near64, total),
        "near256_pct": pct(near256, total),
        "branch_counts": branch_counts,
        "matched_reason": matched_reason,
        "matched_kind": matched_kind,
    }
    return summary, top_rows, target_rows


def summarize_unresolved(debug_rows: list[dict]):
    by_reason = Counter()
    by_reason_rows = Counter()
    examples = defaultdict(list)
    for row in debug_rows:
        reason = row["target_reason"]
        cnt = int(row["count"])
        by_reason[reason] += cnt
        by_reason_rows[reason] += 1
        if len(examples[reason]) < 12:
            examples[reason].append(row)
    rows = []
    total = sum(by_reason.values())
    for reason, cnt in by_reason.most_common():
        rows.append(
            {
                "target_reason": reason,
                "address_rows": by_reason_rows[reason],
                "samples": cnt,
                "pct_samples": f"{pct(cnt, total):.4f}",
            }
        )
    return rows, examples


def summarize_line_label_distances(target_rows: list[dict]):
    by_variant = defaultdict(list)
    for row in target_rows:
        if row["target_kind"] != "line":
            continue
        raw = row.get("abs_intended_minus_profiled_offset_bytes", "")
        if raw == "":
            continue
        by_variant[row["variant"]].append((int(raw), int(row["target_baseline_count"] or 0)))

    rows = []
    for variant, vals in sorted(by_variant.items()):
        unweighted = sorted(v for v, _ in vals)
        weighted = []
        total_samples = sum(c for _, c in vals)
        for dist, count in vals:
            weighted.extend([dist] * count)
        weighted.sort()
        rows.append(
            {
                "variant": variant,
                "line_target_count": len(vals),
                "baseline_sample_weight": total_samples,
                "unweighted_p50": percentile(unweighted, 50),
                "unweighted_p75": percentile(unweighted, 75),
                "unweighted_p90": percentile(unweighted, 90),
                "unweighted_p95": percentile(unweighted, 95),
                "unweighted_p99": percentile(unweighted, 99),
                "unweighted_max": percentile(unweighted, 100),
                "weighted_p50": percentile(weighted, 50),
                "weighted_p75": percentile(weighted, 75),
                "weighted_p90": percentile(weighted, 90),
                "weighted_p95": percentile(weighted, 95),
                "weighted_p99": percentile(weighted, 99),
                "weighted_max": percentile(weighted, 100),
                "weighted_gt_64_pct": f"{pct(sum(c for d, c in vals if d > 64), total_samples):.4f}",
                "weighted_gt_256_pct": f"{pct(sum(c for d, c in vals if d > 256), total_samples):.4f}",
                "weighted_gt_1024_pct": f"{pct(sum(c for d, c in vals if d > 1024), total_samples):.4f}",
                "weighted_gt_4096_pct": f"{pct(sum(c for d, c in vals if d > 4096), total_samples):.4f}",
            }
        )
    return rows


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    eval_root = Path(args.eval_root).resolve()
    variant_root = Path(args.variant_root).resolve()
    trace_base = Path(args.trace_base).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else eval_root / "dtcov_target_effectiveness"
    out_dir.mkdir(parents=True, exist_ok=True)

    prep = load_prepare(repo_root)
    comparison_rows = [r for r in read_csv(eval_root / "comparison_mpki_runtime.csv") if r["variant"] != "baseline"]
    selected_rows = read_csv(variant_root / "selected_dtcov_targets.csv")
    target_meta = {r["target_id"]: r for r in selected_rows}
    all_points = read_csv(variant_root / "injection_points_by_depth.csv")

    summary_rows = []
    all_top_rows = []
    all_target_rows = []
    for comp in comparison_rows:
        variant = comp["variant"]
        vp = comp["variant_prefixed"]
        binary = Path(comp["binary"])
        points = [r for r in all_points if r["variant_short"] == variant]
        intended, missing, addr_by_dem = build_intended_targets(prep, binary, target_meta, points)
        trace_file = trace_base / f"qsort_{args.max_cycles}_{vp}" / "l2_miss" / "lbr_symbolic_dump.txt"
        if not trace_file.is_file():
            raise RuntimeError(f"missing optimized trace: {trace_file}")
        summary, top_rows, target_rows = parse_trace(prep, trace_file, addr_by_dem, intended)
        summary_rows.append(
            {
                "variant": variant,
                "variant_prefixed": vp,
                "optimized_trace": str(trace_file),
                "intended_target_count": summary["intended_target_count"],
                "missing_intended_target_count": len(missing),
                "total_l2_trace_samples": summary["total_l2_trace_samples"],
                "exact_intended_samples": summary["exact_intended_samples"],
                "exact_intended_pct": f"{summary['exact_pct']:.4f}",
                "near64_intended_samples": summary["near64_intended_samples"],
                "near64_intended_pct": f"{summary['near64_pct']:.4f}",
                "near256_intended_samples": summary["near256_intended_samples"],
                "near256_intended_pct": f"{summary['near256_pct']:.4f}",
                "exact_by_kind": ";".join(f"{k}:{v}" for k, v in summary["matched_kind"].most_common()),
                "exact_by_reason": ";".join(f"{k}:{v}" for k, v in summary["matched_reason"].most_common()),
            }
        )
        for row in top_rows:
            row["variant"] = variant
            all_top_rows.append(row)
        for row in target_rows:
            row["variant"] = variant
            all_target_rows.append(row)

    write_csv(
        out_dir / "optimized_trace_intended_target_match.csv",
        summary_rows,
        [
            "variant", "variant_prefixed", "optimized_trace", "intended_target_count",
            "missing_intended_target_count", "total_l2_trace_samples", "exact_intended_samples",
            "exact_intended_pct", "near64_intended_samples", "near64_intended_pct",
            "near256_intended_samples", "near256_intended_pct", "exact_by_kind", "exact_by_reason",
        ],
    )
    write_csv(
        out_dir / "optimized_trace_top_targets_vs_intended.csv",
        all_top_rows,
        [
            "variant", "trace_rank", "samples", "symbol", "offset", "branch_type",
            "is_exact_intended_target", "nearest_intended_distance_bytes", "nearest_target_rank",
            "nearest_target_kind", "nearest_target_reason", "nearest_target_id",
        ],
    )
    write_csv(
        out_dir / "intended_targets_remaining_in_optimized_trace.csv",
        all_target_rows,
        [
            "variant", "target_rank", "target_id", "target_kind", "target_reason", "target_symbol",
            "target_src_relpath", "target_src_line", "profiled_offset", "intended_offset",
            "intended_minus_profiled_offset_bytes", "abs_intended_minus_profiled_offset_bytes",
            "target_baseline_count", "exact_optimized_l2_samples", "near256_optimized_l2_samples",
        ],
    )

    label_distance_rows = summarize_line_label_distances(all_target_rows)
    write_csv(
        out_dir / "line_label_distance_summary.csv",
        label_distance_rows,
        [
            "variant", "line_target_count", "baseline_sample_weight",
            "unweighted_p50", "unweighted_p75", "unweighted_p90", "unweighted_p95",
            "unweighted_p99", "unweighted_max", "weighted_p50", "weighted_p75",
            "weighted_p90", "weighted_p95", "weighted_p99", "weighted_max",
            "weighted_gt_64_pct", "weighted_gt_256_pct", "weighted_gt_1024_pct",
            "weighted_gt_4096_pct",
        ],
    )

    debug_rows = read_csv(variant_root / "target_address_resolution_debug.csv")
    unresolved_summary, unresolved_examples = summarize_unresolved(debug_rows)
    write_csv(
        out_dir / "target_resolution_reason_summary.csv",
        unresolved_summary,
        ["target_reason", "address_rows", "samples", "pct_samples"],
    )

    with (out_dir / "dtcov_target_effectiveness.md").open("w", encoding="utf-8") as f:
        f.write("# DTCOV Target Effectiveness\n\n")
        f.write("## Optimized Trace Match Against Intended Targets\n\n")
        f.write("| Variant | Intended targets | Trace samples | Exact intended hits | Near +/-64B | Near +/-256B |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for row in summary_rows:
            f.write(
                f"| {row['variant']} | {row['intended_target_count']} | {row['total_l2_trace_samples']} | "
                f"{row['exact_intended_samples']} ({row['exact_intended_pct']}%) | "
                f"{row['near64_intended_samples']} ({row['near64_intended_pct']}%) | "
                f"{row['near256_intended_samples']} ({row['near256_intended_pct']}%) |\n"
            )
        f.write("\n")
        f.write("Exact means optimized `LBR[0].to` lands exactly on an intended prefetch target address. ")
        f.write("Near means same symbol and offset within the byte window.\n\n")

        f.write("## Source-Line Label Distance\n\n")
        f.write("This compares the original profiled target offset with the actual source label offset in the optimized binary. ")
        f.write("Large distances mean `function:line` insertion did not prefetch the exact miss cache line.\n\n")
        f.write("| Variant | Line targets | Sample weight | Weighted p50 | Weighted p90 | Weighted >256B | Weighted >4KB |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for row in label_distance_rows:
            f.write(
                f"| {row['variant']} | {row['line_target_count']} | {row['baseline_sample_weight']} | "
                f"{row['weighted_p50']} | {row['weighted_p90']} | "
                f"{row['weighted_gt_256_pct']}% | {row['weighted_gt_4096_pct']}% |\n"
            )
        f.write("\n")

        f.write("## Top Optimized L2 Targets\n\n")
        for variant in [r["variant"] for r in summary_rows]:
            f.write(f"### {variant}\n\n")
            f.write("| Rank | Samples | Target offset | Branch | Exact intended? | Nearest dist | Nearest rank/reason |\n")
            f.write("|---:|---:|---|---|---|---:|---|\n")
            for row in [r for r in all_top_rows if r["variant"] == variant][:20]:
                f.write(
                    f"| {row['trace_rank']} | {row['samples']} | `{row['symbol']}+{row['offset']}` | "
                    f"{row['branch_type']} | {row['is_exact_intended_target']} | "
                    f"{row['nearest_intended_distance_bytes']} | "
                    f"{row['nearest_target_rank']} / {row['nearest_target_reason']} |\n"
                )
            f.write("\n")

        f.write("## Target Resolution Reasons\n\n")
        f.write("| Reason | Address rows | Samples | Sample share |\n")
        f.write("|---|---:|---:|---:|\n")
        for row in unresolved_summary:
            f.write(f"| {row['target_reason']} | {row['address_rows']} | {row['samples']} | {row['pct_samples']}% |\n")
        f.write("\n")
        f.write("### Examples\n\n")
        for reason, rows in unresolved_examples.items():
            if reason == "resolved_line":
                continue
            f.write(f"#### {reason}\n\n")
            f.write("| Count | Symbol | Offset | Addr2line function | Addr2line location | Enclosing |\n")
            f.write("|---:|---|---|---|---|---|\n")
            for row in rows[:8]:
                f.write(
                    f"| {row['count']} | {row['target_symbol']} | {row['target_offset']} | "
                    f"{row['addr2line_function']} | {row['addr2line_location']} | {row['enclosing_function']} |\n"
                )
            f.write("\n")

        f.write("## Interpretation\n\n")
        f.write("- Optimized traces still miss mostly at addresses that are not exact intended prefetch targets.\n")
        f.write("- `line0` is not one address; it is a DWARF line-table failure bucket, so it can hide many different PCs.\n")
        f.write("- Direct symbol+offset targets assemble correctly, but source insertion changes code layout; exact offset targeting remains less robust than labels.\n")

    print(out_dir)


if __name__ == "__main__":
    main()
