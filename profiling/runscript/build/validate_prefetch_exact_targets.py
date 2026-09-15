#!/usr/bin/env python3
import argparse
import csv
import importlib.util
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Validate exact prefetch target selection against the original PEBS+LBR trace. "
            "This checks true sample-level LBR coverage and whether source-line targets "
            "hide multiple distinct instruction cache lines."
        )
    )
    ap.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    ap.add_argument(
        "--trace-dir",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/trace/verilator-qsort-highrate/l2_miss"),
    )
    ap.add_argument(
        "--baseline-bin",
        default=str(
            DEFAULT_REPO_ROOT
            / "profiling/results/prefetchit_builds_exact_v1/binaries/"
            "simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-verilator_pf_exact_baseline"
        ),
    )
    ap.add_argument(
        "--variant-result-root",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/prefetch_exact_variants_v2"),
    )
    ap.add_argument(
        "--eval-root",
        default=str(DEFAULT_REPO_ROOT / "profiling/results/prefetchit_eval_exact_v2/20260529_114818"),
    )
    ap.add_argument(
        "--base-verilator-dir",
        default=str(DEFAULT_REPO_ROOT / "benchmarks/chipyard/sims/verilator"),
    )
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--target-symbol-pool", type=int, default=200)
    ap.add_argument("--target-address-pool", type=int, default=50000)
    ap.add_argument("--prefer-prefix", default="VTestDriver___024root___")
    ap.add_argument("--coverage-top-list", default="10,30,50,100,150,200,300")
    ap.add_argument("--out-dir", default="")
    return ap.parse_args()


def load_prepare_module(repo_root: Path):
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


def pct(num: float, den: float) -> float:
    return (100.0 * num / den) if den else 0.0


def target_key_from_row(row: dict):
    return (
        row["target_symbol"].strip(),
        row["target_src_relpath"].strip(),
        int(row["target_src_line"]),
    )


def load_variant_sites(points_csv: Path):
    rows = read_csv(points_csv)
    variant_targets = defaultdict(set)
    site_index = defaultdict(set)
    variant_depths = defaultdict(set)
    variants = []

    for row in rows:
        variant = row["variant_short"].strip()
        if variant not in variants:
            variants.append(variant)
        depth = int(row["depth"])
        target_key = target_key_from_row(row)
        from_sym = row["from_symbol"].strip()
        from_off = parse_hex(row["from_offset"])
        to_sym = row["to_symbol"].strip()
        to_off = parse_hex(row["to_offset"])
        br_type = row["branch_type"].strip()
        site_key = (depth, target_key, from_sym, from_off, to_sym, to_off, br_type)
        site_index[site_key].add(variant)
        variant_targets[variant].add(target_key)
        variant_depths[variant].add(depth)

    return variants, variant_targets, site_index, variant_depths


def summarize_target_address_spread(
    target_addr_counts: Counter,
    addr_by_dem: dict,
    addr_to_target_key: dict,
    selected_rank: dict,
):
    grouped = defaultdict(Counter)
    for (sym, off), cnt in target_addr_counts.items():
        base = addr_by_dem.get(sym)
        if base is None:
            continue
        key = addr_to_target_key.get(base + off)
        if key in selected_rank:
            grouped[key][off] += cnt

    rows = []
    for key, counts in grouped.items():
        total = sum(counts.values())
        if total <= 0:
            continue
        offsets = sorted(counts)
        min_off = offsets[0]
        max_off = offsets[-1]
        line_counts = Counter()
        for off, cnt in counts.items():
            line_counts[(off - min_off) // 64] += cnt
        densest_line_count = line_counts.most_common(1)[0][1] if line_counts else 0
        first_1_count = sum(cnt for off, cnt in counts.items() if 0 <= off - min_off < 64)
        first_4_count = sum(cnt for off, cnt in counts.items() if 0 <= off - min_off < 256)
        first_8_count = sum(cnt for off, cnt in counts.items() if 0 <= off - min_off < 512)
        top_offsets = ";".join(f"+0x{off:x}:{cnt}" for off, cnt in counts.most_common(8))
        rows.append(
            {
                "target_rank": selected_rank[key],
                "target_symbol": key[0],
                "target_src_relpath": key[1],
                "target_src_line": key[2],
                "target_count": total,
                "unique_target_pcs": len(counts),
                "unique_64b_lines_from_min": len(line_counts),
                "min_func_offset": f"0x{min_off:x}",
                "max_func_offset": f"0x{max_off:x}",
                "func_offset_span_bytes": max_off - min_off,
                "densest_single_64b_line_pct": f"{pct(densest_line_count, total):.4f}",
                "first_64b_from_min_pct": f"{pct(first_1_count, total):.4f}",
                "first_256b_from_min_pct": f"{pct(first_4_count, total):.4f}",
                "first_512b_from_min_pct": f"{pct(first_8_count, total):.4f}",
                "top_func_offsets": top_offsets,
            }
        )
    rows.sort(key=lambda r: int(r["target_rank"]))
    return rows


def parse_top_list(raw: str):
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        n = int(item)
        if n > 0:
            out.append(n)
    return sorted(set(out))


def summarize_static_lead(points_csv: Path, spread_rows: list[dict]):
    target_min = {}
    for row in spread_rows:
        key = (row["target_symbol"], row["target_src_relpath"], int(row["target_src_line"]))
        target_min[key] = parse_hex(row["min_func_offset"])

    def bucket(distance: int) -> str:
        if distance < 0:
            return "negative"
        if distance < 64:
            return "0_63B"
        if distance < 256:
            return "64_255B"
        if distance < 1024:
            return "256B_1K"
        if distance < 4096:
            return "1K_4K"
        if distance < 65536:
            return "4K_64K"
        if distance < 2097152:
            return "64K_2M"
        return "gt_2M"

    counters = defaultdict(Counter)
    with points_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            variant = row["variant_short"].strip()
            cnt = int(row["count"])
            counters[variant]["site_rows"] += 1
            counters[variant]["candidate_weight"] += cnt
            key = target_key_from_row(row)
            target_off = target_min.get(key)
            if target_off is None:
                counters[variant]["missing_target_offset_w"] += cnt
                continue
            if row["from_symbol"].strip() != row["target_symbol"].strip():
                counters[variant]["cross_function_w"] += cnt
                continue
            distance = target_off - parse_hex(row["from_offset"])
            counters[variant]["same_function_w"] += cnt
            counters[variant][f"{bucket(distance)}_w"] += cnt

    rows = []
    for variant, c in counters.items():
        total = c["candidate_weight"]

        def p(key: str):
            return f"{pct(c[key], total):.4f}"

        rows.append(
            {
                "variant_short": variant,
                "site_rows": c["site_rows"],
                "candidate_weight": total,
                "same_function_weight_pct": p("same_function_w"),
                "cross_function_weight_pct": p("cross_function_w"),
                "distance_0_63B_pct": p("0_63B_w"),
                "distance_64_255B_pct": p("64_255B_w"),
                "distance_256B_1K_pct": p("256B_1K_w"),
                "distance_1K_4K_pct": p("1K_4K_w"),
                "distance_4K_64K_pct": p("4K_64K_w"),
                "distance_64K_2M_pct": p("64K_2M_w"),
                "distance_gt_2M_pct": p("gt_2M_w"),
                "distance_negative_pct": p("negative_w"),
            }
        )
    return rows


def compute_true_lbr_coverage(
    prep,
    lbr_file: Path,
    addr_by_dem: dict,
    addr_to_target_key: dict,
    variants: list[str],
    variant_targets: dict,
    site_index: dict,
):
    target_to_variants = defaultdict(set)
    max_depth = 1
    for variant, targets in variant_targets.items():
        for target in targets:
            target_to_variants[target].add(variant)
    for site_key in site_index:
        max_depth = max(max_depth, site_key[0])

    total_samples = 0
    samples_with_selected_target = Counter()
    samples_covered_once = Counter()
    matched_site_instances = Counter()
    selected_target_counts = Counter()
    lbr0_target_counts = Counter()
    missing_depth_samples = Counter()

    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line_idx, raw in enumerate(f, start=1):
            entries = prep.parse_lbr_entries_limited(raw, max_depth)
            if not entries:
                continue
            total_samples += 1
            e0 = entries[0]
            base = addr_by_dem.get(e0["to_symbol"])
            if base is None:
                continue
            target_key = addr_to_target_key.get(base + e0["to_offset"])
            if target_key is None:
                continue
            lbr0_target_counts[target_key] += 1

            target_variants = target_to_variants.get(target_key, set())
            if not target_variants:
                continue
            for variant in target_variants:
                samples_with_selected_target[variant] += 1
                selected_target_counts[(variant, target_key)] += 1

            covered_variants = set()
            for idx, e in enumerate(entries, start=1):
                site_key = (
                    idx,
                    target_key,
                    e["from_symbol"],
                    e["from_offset"],
                    e["to_symbol"],
                    e["to_offset"],
                    e["branch_type"],
                )
                hit_variants = site_index.get(site_key)
                if not hit_variants:
                    continue
                for variant in hit_variants:
                    matched_site_instances[variant] += 1
                    covered_variants.add(variant)
            for variant in covered_variants:
                samples_covered_once[variant] += 1

            if len(entries) < max_depth:
                for variant in target_variants:
                    missing_depth_samples[variant] += 1

    rows = []
    for variant in variants:
        selected = samples_with_selected_target[variant]
        covered = samples_covered_once[variant]
        rows.append(
            {
                "variant_short": variant,
                "total_lbr_samples": total_samples,
                "selected_target_samples": selected,
                "covered_selected_samples_once": covered,
                "matched_site_instances": matched_site_instances[variant],
                "selected_target_pct_of_all_l2_samples": f"{pct(selected, total_samples):.4f}",
                "covered_pct_of_all_l2_samples": f"{pct(covered, total_samples):.4f}",
                "covered_pct_of_selected_target_samples": f"{pct(covered, selected):.4f}",
                "avg_matched_sites_per_selected_sample": f"{(matched_site_instances[variant] / selected) if selected else 0.0:.4f}",
                "avg_matched_sites_per_covered_sample": f"{(matched_site_instances[variant] / covered) if covered else 0.0:.4f}",
                "selected_samples_with_less_than_max_depth": missing_depth_samples[variant],
            }
        )
    return rows, selected_target_counts, lbr0_target_counts


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    trace_dir = Path(args.trace_dir).resolve()
    lbr_file = trace_dir / "lbr_symbolic_dump.txt"
    target_csv = trace_dir / "target_branch_counts.csv"
    baseline_bin = Path(args.baseline_bin).resolve()
    variant_root = Path(args.variant_result_root).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else Path(args.eval_root).resolve() / "rigorous_prefetch_validation"
    cfg_tag = f"chipyard.harness.TestHarness.{args.config}"
    source_root = Path(args.base_verilator_dir).resolve() / "generated-src" / cfg_tag / cfg_tag

    prep = load_prepare_module(repo_root)
    selected_rows = read_csv(variant_root / "selected_exact_targets.csv")
    selected_rank = {target_key_from_row(row): int(row["target_rank"]) for row in selected_rows}
    max_top_n = max(selected_rank.values())
    coverage_top_list = parse_top_list(args.coverage_top_list)
    max_resolved_targets = max([max_top_n] + coverage_top_list)

    print(f"[phase] symbol maps: {baseline_bin}")
    addr_by_dem, _ = prep.build_symbol_maps(baseline_bin)
    symbol_pool = set(prep.load_top_symbol_pool(target_csv, max(args.target_symbol_pool, max_resolved_targets)))

    print(f"[phase] pass 1 target address counts: {lbr_file}")
    target_addr_counts, total_samples, accepted_samples = prep.count_target_addresses(
        lbr_file, symbol_pool, addr_by_dem, args.target_address_pool, 0
    )
    print(
        f"[inf] total_lbr_samples={total_samples} accepted_by_symbol_pool={accepted_samples} "
        f"unique_target_addrs={len(target_addr_counts)}"
    )

    print("[phase] resolve target source lines")
    target_rows, _, addr_to_target_key, unresolved_targets, filtered_inlined, _ = prep.build_target_line_selection(
        target_addr_counts,
        addr_by_dem,
        args.addr2line,
        baseline_bin,
        cfg_tag,
        max_resolved_targets,
        source_root,
        True,
    )
    line_counts = Counter()
    for row in target_rows:
        key = target_key_from_row(row)
        line_counts[key] = int(row["target_count"])
    selected_total = sum(int(row["target_count"]) for row in selected_rows)
    print(
        f"[inf] selected_target_samples={selected_total} ({pct(selected_total, total_samples):.2f}% of all) "
        f"filtered_inlined_addrs={len(filtered_inlined)} unresolved_addrs={len(unresolved_targets)}"
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    print("[phase] target source-line address spread")
    spread_rows = summarize_target_address_spread(
        target_addr_counts,
        addr_by_dem,
        addr_to_target_key,
        selected_rank,
    )
    write_csv(
        out_dir / "target_source_line_address_spread.csv",
        spread_rows,
        [
            "target_rank",
            "target_symbol",
            "target_src_relpath",
            "target_src_line",
            "target_count",
            "unique_target_pcs",
            "unique_64b_lines_from_min",
            "min_func_offset",
            "max_func_offset",
            "func_offset_span_bytes",
            "densest_single_64b_line_pct",
            "first_64b_from_min_pct",
            "first_256b_from_min_pct",
            "first_512b_from_min_pct",
            "top_func_offsets",
        ],
    )

    cumulative_rows = []
    ranked_counts = [int(row["target_count"]) for row in sorted(target_rows, key=lambda r: int(r["target_rank"]))]
    for n in coverage_top_list:
        s = sum(ranked_counts[: min(n, len(ranked_counts))])
        cumulative_rows.append(
            {
                "top_n": n,
                "samples": s,
                "pct_of_all_l2_samples": f"{pct(s, total_samples):.4f}",
                "pct_of_accepted_symbol_pool": f"{pct(s, accepted_samples):.4f}",
            }
        )
    write_csv(
        out_dir / "target_cumulative_coverage.csv",
        cumulative_rows,
        ["top_n", "samples", "pct_of_all_l2_samples", "pct_of_accepted_symbol_pool"],
    )

    static_lead_rows = summarize_static_lead(variant_root / "injection_points_by_depth.csv", spread_rows)
    write_csv(
        out_dir / "static_lead_distance_summary.csv",
        static_lead_rows,
        [
            "variant_short",
            "site_rows",
            "candidate_weight",
            "same_function_weight_pct",
            "cross_function_weight_pct",
            "distance_0_63B_pct",
            "distance_64_255B_pct",
            "distance_256B_1K_pct",
            "distance_1K_4K_pct",
            "distance_4K_64K_pct",
            "distance_64K_2M_pct",
            "distance_gt_2M_pct",
            "distance_negative_pct",
        ],
    )

    print("[phase] pass 2 true sample-level LBR coverage")
    variants, variant_targets, site_index, _ = load_variant_sites(variant_root / "injection_points_by_depth.csv")
    coverage_rows, selected_target_counts, lbr0_target_counts = compute_true_lbr_coverage(
        prep,
        lbr_file,
        addr_by_dem,
        addr_to_target_key,
        variants,
        variant_targets,
        site_index,
    )
    write_csv(
        out_dir / "true_lbr_sample_coverage.csv",
        coverage_rows,
        [
            "variant_short",
            "total_lbr_samples",
            "selected_target_samples",
            "covered_selected_samples_once",
            "matched_site_instances",
            "selected_target_pct_of_all_l2_samples",
            "covered_pct_of_all_l2_samples",
            "covered_pct_of_selected_target_samples",
            "avg_matched_sites_per_selected_sample",
            "avg_matched_sites_per_covered_sample",
            "selected_samples_with_less_than_max_depth",
        ],
    )

    top_rows = []
    for key, cnt in lbr0_target_counts.most_common(50):
        if key not in selected_rank:
            continue
        top_rows.append(
            {
                "target_rank": selected_rank[key],
                "target_symbol": key[0],
                "target_src_relpath": key[1],
                "target_src_line": key[2],
                "lbr0_samples": cnt,
                "pct_of_all_l2_samples": f"{pct(cnt, total_samples):.4f}",
            }
        )
    write_csv(
        out_dir / "selected_target_sample_share.csv",
        sorted(top_rows, key=lambda r: int(r["target_rank"])),
        ["target_rank", "target_symbol", "target_src_relpath", "target_src_line", "lbr0_samples", "pct_of_all_l2_samples"],
    )

    with (out_dir / "rigorous_prefetch_validation.md").open("w", encoding="utf-8") as f:
        f.write("# Rigorous Prefetch Validation\n\n")
        f.write("## Inputs\n")
        f.write(f"- LBR trace: `{lbr_file}`\n")
        f.write(f"- Baseline binary: `{baseline_bin}`\n")
        f.write(f"- Variant metadata: `{variant_root}`\n\n")
        f.write("## Overall Target Coverage\n")
        f.write(f"- Total LBR samples with branch stack: {total_samples}\n")
        f.write(f"- Samples accepted by top-symbol pool: {accepted_samples} ({pct(accepted_samples, total_samples):.2f}%)\n")
        f.write(f"- Selected exact target samples, top {max_top_n}: {selected_total} ({pct(selected_total, total_samples):.2f}% of all L2 samples)\n")
        f.write(f"- Filtered inline target addresses: {len(filtered_inlined)}\n")
        f.write(f"- Unresolved target addresses: {len(unresolved_targets)}\n\n")
        f.write("## True Sample-Level Coverage By Variant\n")
        f.write("| Variant | selected/all | covered/all | covered/selected | matched sites / selected sample |\n")
        f.write("|---|---:|---:|---:|---:|\n")
        for row in coverage_rows:
            f.write(
                f"| {row['variant_short']} | {row['selected_target_pct_of_all_l2_samples']}% | "
                f"{row['covered_pct_of_all_l2_samples']}% | {row['covered_pct_of_selected_target_samples']}% | "
                f"{row['avg_matched_sites_per_selected_sample']} |\n"
            )
        f.write("\n")
        f.write("## Cumulative Target Coverage\n")
        f.write("| Top N target lines | samples | all L2 samples | accepted top-symbol samples |\n")
        f.write("|---:|---:|---:|---:|\n")
        for row in cumulative_rows:
            f.write(
                f"| {row['top_n']} | {row['samples']} | {row['pct_of_all_l2_samples']}% | "
                f"{row['pct_of_accepted_symbol_pool']}% |\n"
            )
        f.write("\n")
        f.write("## Target Source-Line Spread\n")
        f.write(
            "If a selected `function:line` maps to many target PCs/cache lines, a single source label can be "
            "PC-relative correct but still prefetch the wrong instruction line for most samples.\n\n"
        )
        f.write("| Rank | samples | unique PCs | 64B lines | span bytes | densest 64B | first 256B from min | source |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for row in spread_rows[:30]:
            f.write(
                f"| {row['target_rank']} | {row['target_count']} | {row['unique_target_pcs']} | "
                f"{row['unique_64b_lines_from_min']} | {row['func_offset_span_bytes']} | "
                f"{row['densest_single_64b_line_pct']}% | {row['first_256b_from_min_pct']}% | "
                f"{row['target_src_relpath']}:{row['target_src_line']} |\n"
            )
        f.write("\n")
        f.write("## Static Lead Distance Summary\n")
        f.write(
            "Distances are measured only when insertion and target are in the same function; "
            "cross-function sites are usually call/return-chain prefetches and can be either too early or not directly comparable.\n\n"
        )
        f.write("| Variant | same func | cross func | 256B-1K | 1K-4K | 4K-64K | negative |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for row in static_lead_rows:
            f.write(
                f"| {row['variant_short']} | {row['same_function_weight_pct']}% | "
                f"{row['cross_function_weight_pct']}% | {row['distance_256B_1K_pct']}% | "
                f"{row['distance_1K_4K_pct']}% | {row['distance_4K_64K_pct']}% | "
                f"{row['distance_negative_pct']}% |\n"
            )
        f.write("\n")
        f.write("## Generated CSVs\n")
        f.write("- `target_source_line_address_spread.csv`\n")
        f.write("- `true_lbr_sample_coverage.csv`\n")
        f.write("- `selected_target_sample_share.csv`\n")
        f.write("- `target_cumulative_coverage.csv`\n")
        f.write("- `static_lead_distance_summary.csv`\n")

    print(f"[ok] wrote {out_dir}")


if __name__ == "__main__":
    main()
