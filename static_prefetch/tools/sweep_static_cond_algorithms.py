#!/usr/bin/env python3
"""Run a profile-free COND candidate algorithm sweep and summarize overlap."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import evaluate_static_cond_targets as eval_cond
import static_cond_target_candidates as cond_gen

MODES = [
    "guard-exit",
    "tail-sparse",
    "entry-window",
    "fetch-gap",
    "sparse-hot",
    "small-forward",
    "combined",
    "spread",
    "ifelse",
    "frontier",
    "density",
    "span",
    "loop",
]


def read_metric(path: Path, k: int) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if int(row["k"]) == k:
            return row
    return rows[-1]


def write_summary(path: Path, rows: list[dict[str, str]], ks: list[int]) -> None:
    lines = [
        "# Static COND Target Algorithm Sweep",
        "",
        "PGO/LBR samples are used only for evaluation. Candidate files are generated from binary static structure only.",
        "",
        "| Mode | Best K | Weighted recall | Unique recall | Hit samples | Truth samples | Candidate CSV |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['mode']} | {row['best_k']} | {float(row['best_weighted_recall']) * 100.0:.2f}% | "
            f"{float(row['best_unique_recall']) * 100.0:.2f}% | {row['best_hit_samples']} | {row['truth_samples']} | `{row['candidate_csv']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ks", default="100,500,1000,2500,5000,10000,25000,50000,100000")
    parser.add_argument("--target-k", type=int, default=5000)
    parser.add_argument("--max-depth", type=int, default=96)
    parser.add_argument(
        "--modes",
        default=",".join(MODES),
        help="Comma-separated static scoring modes to generate/evaluate.",
    )
    parser.add_argument(
        "--candidate-targets",
        choices=["taken", "source", "both"],
        default="taken",
        help="Static candidate target set passed to static_cond_target_candidates.py",
    )
    parser.add_argument("--target-window-lines", type=int, default=0)
    parser.add_argument("--nm", default="llvm-nm-19")
    parser.add_argument("--objdump", default="llvm-objdump-19")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ks = [int(x) for x in args.ks.split(",") if x.strip()]
    summary_rows: list[dict[str, str]] = []

    print("[info] parsing binary once")
    symbols = cond_gen.parse_nm(args.binary, args.nm)
    cond_gen.parse_objdump(args.binary, args.objdump, symbols)
    print("[info] collecting COND truth once")
    eval_symbols = eval_cond.build_symbol_index(args.binary, args.nm)
    trace_dirs = eval_cond.trace_dirs_from_args(args.trace_dir)
    truth, by_trace_truth, stats = eval_cond.collect_cond_truth(trace_dirs, eval_symbols, 0)

    requested_modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    unknown_modes = [mode for mode in requested_modes if mode not in MODES]
    if unknown_modes:
        raise SystemExit(f"unknown mode(s): {','.join(unknown_modes)}")

    for mode in requested_modes:
        cand = args.out_dir / "candidates" / f"static_cond_{mode}.csv"
        eval_dir = args.out_dir / "eval" / mode
        rows = cond_gen.generate_candidates(
            symbols,
            mode,
            args.max_depth,
            candidate_targets=args.candidate_targets,
            target_window_lines=args.target_window_lines,
        )
        cond_gen.write_csv(cand, rows)
        keys = eval_cond.ordered_keys(rows)
        metrics = eval_cond.eval_one(keys, truth, ks)
        by_trace_rows = {trace: eval_cond.eval_one(keys, local, ks) for trace, local in by_trace_truth.items()}
        eval_dir.mkdir(parents=True, exist_ok=True)
        eval_cond.write_csv(eval_dir / "overlap_metrics.csv", metrics)
        eval_cond.write_csv(eval_dir / "profile_cond_targets_with_static_rank.csv", eval_cond.rank_truth_rows(keys, truth))
        for idx, (_trace, local_rows) in enumerate(by_trace_rows.items(), 1):
            eval_cond.write_csv(eval_dir / f"trace{idx:02d}_overlap_metrics.csv", local_rows)
        eval_cond.write_report(eval_dir / "overlap_report.md", cand, stats, metrics, by_trace_rows)
        best = max(metrics, key=lambda row: float(row["weighted_recall"]))
        at_target = next((row for row in metrics if int(row["k"]) == args.target_k), metrics[-1])
        summary_rows.append(
            {
                "mode": mode,
                "best_k": best["k"],
                "best_weighted_recall": best["weighted_recall"],
                "best_unique_recall": best["unique_recall"],
                "best_hit_samples": best["hit_samples"],
                "target_k": str(args.target_k),
                "target_weighted_recall": at_target["weighted_recall"],
                "target_unique_recall": at_target["unique_recall"],
                "truth_samples": best["truth_samples"],
                "candidate_csv": str(cand),
                "eval_dir": str(eval_dir),
            }
        )
        print(f"[ok] mode={mode} target_k={args.target_k} wr={at_target['weighted_recall']} best_k={best['k']} best_wr={best['weighted_recall']}")

    fields = [
        "mode",
        "best_k",
        "best_weighted_recall",
        "best_unique_recall",
        "best_hit_samples",
        "target_k",
        "target_weighted_recall",
        "target_unique_recall",
        "truth_samples",
        "candidate_csv",
        "eval_dir",
    ]
    with (args.out_dir / "algorithm_sweep_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary_rows)
    summary_rows.sort(key=lambda row: float(row["target_weighted_recall"]), reverse=True)
    write_summary(args.out_dir / "algorithm_sweep_summary.md", summary_rows, ks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
