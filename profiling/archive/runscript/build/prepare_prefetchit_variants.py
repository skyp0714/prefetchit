#!/usr/bin/env python3
import argparse
import csv
import glob
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


FUNC_DEF_RE = re.compile(r"^void\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")
ENTRY_MIN_SLASHES = 7


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Prepare baseline + coverage-guided depth variants by inserting prefetchit0 "
            "from L2 top miss targets and LBR upstream branches."
        )
    )
    ap.add_argument("--verilator-dir", required=True, help="Base chipyard/sims/verilator directory")
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument(
        "--trace-dir",
        required=True,
        help="Trace dir containing lbr_symbolic_dump.txt and target_branch_counts.csv",
    )
    ap.add_argument("--variant-root", required=True, help="Output root for variant build trees")
    ap.add_argument("--result-root", required=True, help="Output root for mapping summaries")
    ap.add_argument("--variant-name-prefix", default="verilator_pf_", help="Variant directory name prefix")
    ap.add_argument("--top-n", type=int, default=10, help="Top miss targets to optimize")
    ap.add_argument("--depths", default="2,4,8,16,32")
    ap.add_argument(
        "--site-budgets",
        default="10,100",
        help="Comma-separated max injection-site candidates per (depth,target), e.g., 10,100",
    )
    ap.add_argument(
        "--coverage-threshold",
        type=float,
        default=0.5,
        help="Coverage reporting threshold per (depth,target), range (0,1]",
    )
    ap.add_argument(
        "--selection-policy",
        choices=["budget", "threshold"],
        default="budget",
        help=(
            "budget: select up to --site-budgets candidates per target. "
            "threshold: stop once --coverage-threshold is reached."
        ),
    )
    ap.add_argument(
        "--prefer-prefix",
        default="VTestDriver___024root___",
        help="Prefer upstream inject functions with this prefix",
    )
    ap.add_argument("--copy-tool", default="rsync", choices=["rsync", "cp"])
    return ap.parse_args()


def normalize_symbol(sym: str) -> str:
    s = sym.strip()
    s = re.sub(r"\+0x[0-9a-fA-F]+$", "", s)
    if "@" in s:
        s = s.split("@", 1)[0]
    if "(" in s:
        s = s.split("(", 1)[0]
    return s.strip()


def parse_lbr_entries(line: str):
    out = []
    toks = line.strip().split()
    for t in toks:
        if t.count("/") < ENTRY_MIN_SLASHES:
            continue
        parts = t.split("/")
        if len(parts) < 2:
            continue
        out.append((normalize_symbol(parts[0]), normalize_symbol(parts[1])))
    return out


def load_top_targets(target_csv: Path, top_n: int):
    counts = Counter()
    with target_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            sym = row.get("symbol", "").strip()
            cnt = int(float(row.get("count", "0")))
            if sym and cnt > 0:
                counts[sym] += cnt
    top = counts.most_common(top_n)
    return counts, top


def index_function_defs(gen_cpp_dir: Path):
    func_to_file = {}
    for fp in glob.glob(str(gen_cpp_dir / "*.cpp")):
        p = Path(fp)
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = FUNC_DEF_RE.match(line)
                if not m:
                    continue
                fn = m.group(1)
                if fn not in func_to_file:
                    func_to_file[fn] = p
    return func_to_file


def find_function_body(lines: list[str], func: str):
    def_idx = -1
    for i, ln in enumerate(lines):
        m = FUNC_DEF_RE.match(ln)
        if m and m.group(1) == func:
            def_idx = i
            break
    if def_idx < 0:
        return -1, -1

    end_idx = len(lines)
    for i in range(def_idx + 1, len(lines)):
        if FUNC_DEF_RE.match(lines[i]):
            end_idx = i
            break
    return def_idx, end_idx


def build_demangled_to_mangled(sim_bin: Path):
    raw = subprocess.run(
        ["nm", "-n", str(sim_bin)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    dem = subprocess.run(
        ["nm", "-n", "-C", str(sim_bin)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()

    line_re = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
    by_key_raw = {}
    by_key_dem = {}
    for ln in raw:
        m = line_re.match(ln)
        if not m:
            continue
        by_key_raw[(m.group(1), m.group(2))] = m.group(3).strip()
    for ln in dem:
        m = line_re.match(ln)
        if not m:
            continue
        by_key_dem[(m.group(1), m.group(2))] = m.group(3).strip()

    out = {}
    for k, raw_name in by_key_raw.items():
        dem_name = by_key_dem.get(k)
        if not dem_name:
            continue
        out[normalize_symbol(dem_name)] = raw_name
    return out


def collect_lbr_counts(lbr_file: Path, top_target_bases: list[str], depths: list[int]):
    max_depth = max(depths)
    counts = Counter()
    target_seen = Counter()
    target_set = set(top_target_bases)

    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            entries = parse_lbr_entries(raw)
            if not entries:
                continue
            miss_target = entries[0][1]
            if miss_target not in target_set:
                continue
            target_seen[miss_target] += 1
            if len(entries) < 2:
                continue
            upto = min(len(entries), max_depth)
            for d in depths:
                idx = d - 1
                if idx >= upto:
                    continue
                upstream = entries[idx][0]
                counts[(d, miss_target, upstream)] += 1
    return counts, target_seen


def choose_sites_for_budget(
    *,
    site_budget: int,
    coverage_threshold: float,
    top_target_bases: list[str],
    depths: list[int],
    counts: Counter,
    target_seen: Counter,
    func_to_file: dict[str, Path],
    prefer_prefix: str,
    selection_policy: str,
):
    selected_rows = []
    coverage_rows = []
    candidate_rows = []
    per_depth_func_targets = {d: defaultdict(list) for d in depths}

    for d in depths:
        for tgt in top_target_bases:
            total = int(target_seen.get(tgt, 0))

            cands = []
            for (dd, tt, up), cnt in counts.items():
                if dd != d or tt != tgt:
                    continue
                if up not in func_to_file:
                    continue
                cands.append((up, int(cnt)))

            # Prefer Verilator model functions when available.
            preferred = [(up, cnt) for up, cnt in cands if up.startswith(prefer_prefix)]
            ranked = preferred if preferred else cands
            ranked.sort(key=lambda x: x[1], reverse=True)

            picked = []
            covered = 0
            for rank, (up, cnt) in enumerate(ranked, start=1):
                if len(picked) >= site_budget:
                    break
                picked.append((up, cnt, rank, "ranked"))
                covered += cnt
                if selection_policy == "threshold" and total > 0 and (covered / total) >= coverage_threshold:
                    break

            # Fallback for edge cases with no observed upstream candidate in parsed LBR.
            if not picked and tgt in func_to_file:
                picked = [(tgt, 0, 0, "fallback_target")]
                covered = 0

            if total > 0:
                coverage_pct = 100.0 * covered / total
            else:
                coverage_pct = 0.0

            coverage_rows.append(
                {
                    "site_budget": site_budget,
                    "depth": d,
                    "target_symbol": tgt,
                    "target_seen_samples": total,
                    "covered_samples": covered,
                    "coverage_pct": f"{coverage_pct:.4f}",
                    "selected_site_count": len(picked),
                    "coverage_threshold": f"{coverage_threshold:.4f}",
                    "selection_policy": selection_policy,
                    "threshold_met": int(total > 0 and (covered / total) >= coverage_threshold),
                    "budget_exhausted": int(len(picked) >= site_budget),
                }
            )

            running = 0
            for site_idx, (up, cnt, rank, picked_by) in enumerate(picked, start=1):
                running += cnt
                running_pct = (100.0 * running / total) if total > 0 else 0.0
                selected_rows.append(
                    {
                        "site_budget": site_budget,
                        "depth": d,
                        "target_symbol": tgt,
                        "selected_inject_function": up,
                        "selection_count": cnt,
                        "target_seen_samples": total,
                        "candidate_rank": rank,
                        "site_index": site_idx,
                        "running_coverage_pct": f"{running_pct:.4f}",
                        "picked_by": picked_by,
                    }
                )
                per_depth_func_targets[d][up].append(tgt)

            for rank, (up, cnt) in enumerate(ranked, start=1):
                candidate_rows.append(
                    {
                        "site_budget": site_budget,
                        "depth": d,
                        "target_symbol": tgt,
                        "candidate_function": up,
                        "count": cnt,
                        "candidate_rank": rank,
                    }
                )

    return selected_rows, coverage_rows, candidate_rows, per_depth_func_targets


def patch_variant_sources(
    variant_dir: Path,
    config: str,
    depth: int,
    site_budget: int,
    func_targets: dict[str, list[str]],
    target_to_mangled: dict[str, str],
):
    cfg_tag = f"chipyard.harness.TestHarness.{config}"
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    func_to_file = index_function_defs(gen_cpp_dir)
    file_to_funcs = defaultdict(dict)

    for func, targets in func_targets.items():
        fp = func_to_file.get(func)
        if not fp:
            continue
        uniq_targets = []
        for t in targets:
            if t not in uniq_targets:
                uniq_targets.append(t)
        file_to_funcs[fp][func] = uniq_targets

    patched_files = []
    inserted_inst_count = 0
    missing_mangled = []

    for fp, func_map in file_to_funcs.items():
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        insertions = []
        for func, targets in func_map.items():
            def_idx, end_idx = find_function_body(lines, func)
            if def_idx < 0:
                continue

            auto_idx = -1
            for i in range(def_idx, end_idx):
                if "auto& vlSelfRef =" in lines[i]:
                    auto_idx = i
                    break
            if auto_idx < 0:
                auto_idx = def_idx

            block = [
                f"    // PREFETCHIT_MANUAL budget={site_budget} depth={depth} func={func} count={len(targets)}\n"
            ]
            for tgt in targets:
                mangled = target_to_mangled.get(tgt, "")
                if not mangled:
                    missing_mangled.append((func, tgt))
                    continue
                block.append(f'    asm volatile("prefetchit0 {mangled}(%%rip)" ::: "memory");\n')
                inserted_inst_count += 1
            if len(block) > 1:
                insertions.append((auto_idx + 1, block))

        if not insertions:
            continue

        insertions.sort(key=lambda x: x[0], reverse=True)
        for pos, block in insertions:
            lines[pos:pos] = block

        fp.write_text("".join(lines), encoding="utf-8")
        patched_files.append(str(fp))

    return patched_files, inserted_inst_count, missing_mangled


def copy_tree(src: Path, dst: Path, tool: str):
    dst.mkdir(parents=True, exist_ok=True)
    if tool == "rsync" and shutil.which("rsync"):
        subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"], check=True)
    else:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main():
    args = parse_args()

    if args.top_n <= 0:
        raise RuntimeError("--top-n must be positive")
    if not (0.0 < args.coverage_threshold <= 1.0):
        raise RuntimeError("--coverage-threshold must be in (0,1]")

    verilator_dir = Path(args.verilator_dir).resolve()
    trace_dir = Path(args.trace_dir).resolve()
    variant_root = Path(args.variant_root).resolve()
    result_root = Path(args.result_root).resolve()

    depths = [int(x.strip()) for x in args.depths.split(",") if x.strip()]
    depths = sorted(set(depths))
    if not depths:
        raise RuntimeError("--depths produced an empty set")

    site_budgets = [int(x.strip()) for x in args.site_budgets.split(",") if x.strip()]
    site_budgets = sorted(set(site_budgets))
    if not site_budgets or any(x <= 0 for x in site_budgets):
        raise RuntimeError("--site-budgets must contain positive integers")

    cfg_tag = f"chipyard.harness.TestHarness.{args.config}"
    gen_cpp_dir = verilator_dir / "generated-src" / cfg_tag / cfg_tag
    sim_bin = verilator_dir / f"simulator-chipyard.harness-{args.config}"
    lbr_file = trace_dir / "lbr_symbolic_dump.txt"
    target_csv = trace_dir / "target_branch_counts.csv"

    if not gen_cpp_dir.exists():
        raise RuntimeError(f"missing generated source dir: {gen_cpp_dir}")
    if not sim_bin.exists():
        raise RuntimeError(f"missing simulator binary: {sim_bin}")
    if not lbr_file.exists() or not target_csv.exists():
        raise RuntimeError("missing l2 trace inputs (lbr_symbolic_dump.txt / target_branch_counts.csv)")

    _, top = load_top_targets(target_csv, args.top_n)
    if not top:
        raise RuntimeError(f"no top targets found in {target_csv}")

    top_syms = [sym for sym, _ in top]
    top_bases = [normalize_symbol(sym) for sym in top_syms]

    func_to_file = index_function_defs(gen_cpp_dir)
    dem_to_mangled = build_demangled_to_mangled(sim_bin)

    target_to_mangled = {}
    for s in top_syms:
        base = normalize_symbol(s)
        if base in dem_to_mangled:
            target_to_mangled[base] = dem_to_mangled[base]

    counts, target_seen = collect_lbr_counts(
        lbr_file=lbr_file,
        top_target_bases=top_bases,
        depths=depths,
    )

    result_root.mkdir(parents=True, exist_ok=True)
    variant_root.mkdir(parents=True, exist_ok=True)

    top_rows = []
    for i, (sym, cnt) in enumerate(top, start=1):
        base = normalize_symbol(sym)
        top_rows.append(
            {
                "rank": i,
                "symbol": sym,
                "base_symbol": base,
                "count": cnt,
                "mangled_symbol": target_to_mangled.get(base, ""),
                "target_seen_samples": int(target_seen.get(base, 0)),
            }
        )
    write_csv(
        result_root / "selected_top_targets.csv",
        top_rows,
        ["rank", "symbol", "base_symbol", "count", "mangled_symbol", "target_seen_samples"],
    )

    all_selected_rows = []
    all_coverage_rows = []
    all_candidate_rows = []

    # Mapping: (site_budget, depth) -> func_targets
    budget_depth_func_targets = {}

    for site_budget in site_budgets:
        selected_rows, coverage_rows, candidate_rows, per_depth_func_targets = choose_sites_for_budget(
            site_budget=site_budget,
            coverage_threshold=args.coverage_threshold,
            selection_policy=args.selection_policy,
            top_target_bases=top_bases,
            depths=depths,
            counts=counts,
            target_seen=target_seen,
            func_to_file=func_to_file,
            prefer_prefix=args.prefer_prefix,
        )

        all_selected_rows.extend(selected_rows)
        all_coverage_rows.extend(coverage_rows)
        all_candidate_rows.extend(candidate_rows)

        for d in depths:
            budget_depth_func_targets[(site_budget, d)] = per_depth_func_targets[d]

    write_csv(
        result_root / "injection_selection.csv",
        all_selected_rows,
        [
            "site_budget",
            "depth",
            "target_symbol",
            "selected_inject_function",
            "selection_count",
            "target_seen_samples",
            "candidate_rank",
            "site_index",
            "running_coverage_pct",
            "picked_by",
        ],
    )

    write_csv(
        result_root / "candidate_rankings.csv",
        all_candidate_rows,
        ["site_budget", "depth", "target_symbol", "candidate_function", "count", "candidate_rank"],
    )

    write_csv(
        result_root / "coverage_by_target.csv",
        all_coverage_rows,
        [
            "site_budget",
            "depth",
            "target_symbol",
            "target_seen_samples",
            "covered_samples",
            "coverage_pct",
            "selected_site_count",
            "coverage_threshold",
            "selection_policy",
            "threshold_met",
            "budget_exhausted",
        ],
    )

    # Aggregate coverage by (site_budget, depth).
    agg_rows = []
    by_key = defaultdict(list)
    for row in all_coverage_rows:
        by_key[(int(row["site_budget"]), int(row["depth"]))].append(row)

    for (site_budget, depth), rows in sorted(by_key.items()):
        total_seen = sum(int(r["target_seen_samples"]) for r in rows)
        total_cov = sum(int(r["covered_samples"]) for r in rows)
        weighted = (100.0 * total_cov / total_seen) if total_seen > 0 else 0.0
        threshold_met_count = sum(int(r["threshold_met"]) for r in rows)
        agg_rows.append(
            {
                "site_budget": site_budget,
                "depth": depth,
                "target_count": len(rows),
                "targets_meeting_threshold": threshold_met_count,
                "targets_meeting_threshold_pct": f"{(100.0 * threshold_met_count / len(rows)) if rows else 0.0:.4f}",
                "weighted_coverage_pct": f"{weighted:.4f}",
                "total_target_seen_samples": total_seen,
                "total_covered_samples": total_cov,
            }
        )

    write_csv(
        result_root / "coverage_summary_by_depth.csv",
        agg_rows,
        [
            "site_budget",
            "depth",
            "target_count",
            "targets_meeting_threshold",
            "targets_meeting_threshold_pct",
            "weighted_coverage_pct",
            "total_target_seen_samples",
            "total_covered_samples",
        ],
    )

    # Prepare variants.
    variant_rows = [{"variant_short": "baseline", "site_budget": 0, "depth": 0, "is_baseline": 1}]
    for site_budget in site_budgets:
        for d in depths:
            variant_rows.append(
                {
                    "variant_short": f"k{site_budget}_d{d}",
                    "site_budget": site_budget,
                    "depth": d,
                    "is_baseline": 0,
                }
            )

    for vr in variant_rows:
        vn = f"{args.variant_name_prefix}{vr['variant_short']}"
        copy_tree(verilator_dir, variant_root / vn, args.copy_tool)

    patch_rows = []
    points_rows = []
    count_rows = []
    missing_mangled_rows = []

    for vr in variant_rows:
        if vr["is_baseline"] == 1:
            patch_rows.append(
                {
                    "variant": f"{args.variant_name_prefix}{vr['variant_short']}",
                    "variant_short": vr["variant_short"],
                    "site_budget": vr["site_budget"],
                    "depth": vr["depth"],
                    "patched_file_count": 0,
                    "inserted_prefetch_instructions": 0,
                    "missing_mangled_count": 0,
                }
            )
            continue

        d = int(vr["depth"])
        site_budget = int(vr["site_budget"])
        func_targets = budget_depth_func_targets[(site_budget, d)]
        variant_short = vr["variant_short"]
        variant_name = f"{args.variant_name_prefix}{variant_short}"

        patched, inserted_inst_count, missing_mangled = patch_variant_sources(
            variant_dir=variant_root / variant_name,
            config=args.config,
            depth=d,
            site_budget=site_budget,
            func_targets=func_targets,
            target_to_mangled=target_to_mangled,
        )

        for fn, tgts in sorted(func_targets.items()):
            uniq_tgts = []
            for t in tgts:
                if t not in uniq_tgts:
                    uniq_tgts.append(t)
            points_rows.append(
                {
                    "variant_short": variant_short,
                    "site_budget": site_budget,
                    "depth": d,
                    "inject_function": fn,
                    "prefetch_target_count": len(uniq_tgts),
                    "prefetch_targets": " | ".join(uniq_tgts),
                    "source_file": str(func_to_file.get(fn, "")),
                }
            )

        uniq_funcs = len(func_targets)
        total_prefetch_targets = sum(len(set(v)) for v in func_targets.values())
        count_rows.append(
            {
                "variant_short": variant_short,
                "site_budget": site_budget,
                "depth": d,
                "unique_inject_functions": uniq_funcs,
                "total_prefetch_targets": total_prefetch_targets,
                "inserted_prefetch_instructions": inserted_inst_count,
            }
        )

        patch_rows.append(
            {
                "variant": variant_name,
                "variant_short": variant_short,
                "site_budget": site_budget,
                "depth": d,
                "patched_file_count": len(patched),
                "inserted_prefetch_instructions": inserted_inst_count,
                "missing_mangled_count": len(missing_mangled),
            }
        )

        for func, tgt in missing_mangled:
            missing_mangled_rows.append(
                {
                    "variant_short": variant_short,
                    "site_budget": site_budget,
                    "depth": d,
                    "inject_function": func,
                    "target_symbol": tgt,
                }
            )

    write_csv(
        result_root / "injection_counts_by_depth.csv",
        count_rows,
        [
            "variant_short",
            "site_budget",
            "depth",
            "unique_inject_functions",
            "total_prefetch_targets",
            "inserted_prefetch_instructions",
        ],
    )
    write_csv(
        result_root / "injection_points_by_depth.csv",
        points_rows,
        [
            "variant_short",
            "site_budget",
            "depth",
            "inject_function",
            "prefetch_target_count",
            "prefetch_targets",
            "source_file",
        ],
    )
    write_csv(
        result_root / "variant_patch_summary.csv",
        patch_rows,
        [
            "variant",
            "variant_short",
            "site_budget",
            "depth",
            "patched_file_count",
            "inserted_prefetch_instructions",
            "missing_mangled_count",
        ],
    )

    if missing_mangled_rows:
        write_csv(
            result_root / "missing_mangled_symbols.csv",
            missing_mangled_rows,
            ["variant_short", "site_budget", "depth", "inject_function", "target_symbol"],
        )

    variant_dir_rows = []
    for vr in variant_rows:
        variant_short = vr["variant_short"]
        vn = f"{args.variant_name_prefix}{variant_short}"
        variant_dir_rows.append(
            {
                "variant": vn,
                "variant_short": variant_short,
                "site_budget": vr["site_budget"],
                "depth": vr["depth"],
                "is_baseline": vr["is_baseline"],
                "variant_dir": str(variant_root / vn),
            }
        )

    write_csv(
        result_root / "variant_dirs.csv",
        variant_dir_rows,
        ["variant", "variant_short", "site_budget", "depth", "is_baseline", "variant_dir"],
    )

    md = []
    md.append("# Prefetchit Variant Plan")
    md.append("")
    md.append("## Top Miss Targets")
    md.append("")
    for row in top_rows:
        md.append(
            f"- {row['rank']}. {row['base_symbol']} count={row['count']} seen={row['target_seen_samples']}"
        )
    md.append("")
    md.append("## Coverage Summary (weighted by target_seen_samples)")
    md.append("")
    for row in agg_rows:
        md.append(
            "- budget={site_budget}, depth={depth}: coverage={weighted_coverage_pct}% "
            "threshold_met={targets_meeting_threshold}/{target_count}".format(**row)
        )
    md.append("")
    md.append("## Variant Patch Summary")
    md.append("")
    for row in patch_rows:
        md.append(
            f"- {row['variant_short']}: patched_files={row['patched_file_count']}, "
            f"prefetch_insts={row['inserted_prefetch_instructions']}, missing_mangled={row['missing_mangled_count']}"
        )
    md.append("")
    (result_root / "injection_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"[ok] wrote {result_root / 'selected_top_targets.csv'}")
    print(f"[ok] wrote {result_root / 'injection_selection.csv'}")
    print(f"[ok] wrote {result_root / 'coverage_by_target.csv'}")
    print(f"[ok] wrote {result_root / 'coverage_summary_by_depth.csv'}")
    print(f"[ok] wrote {result_root / 'injection_counts_by_depth.csv'}")
    print(f"[ok] wrote {result_root / 'injection_points_by_depth.csv'}")
    print(f"[ok] wrote {result_root / 'variant_patch_summary.csv'}")
    print(f"[ok] wrote {result_root / 'variant_dirs.csv'}")
    print(f"[ok] wrote {result_root / 'injection_summary.md'}")
    print(f"[ok] variants prepared at {variant_root}")


if __name__ == "__main__":
    main()
