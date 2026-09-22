#!/usr/bin/env python3
"""Print compact means for completed detailed-profile CSVs in a run directory."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = (
    PROJECT_ROOT
    / "llvm_prefetchit/results/prefetch_plateau/"
    "resume_aggressive_20260620_105007/exact_best_compare/final_compare/"
    "profiles/baseline_qsort_538240/per_iteration.csv"
)


def read_means(path: Path) -> tuple[int, float, float, float, float]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))

    def mean(key: str) -> float:
        vals = []
        for row in rows:
            try:
                value = float(row.get(key, ""))
            except ValueError:
                continue
            if math.isfinite(value):
                vals.append(value)
        return statistics.fmean(vals) if vals else float("nan")

    return (
        len(rows),
        mean("elapsed_sec"),
        mean("l2i_mpki"),
        mean("l1i_mpki"),
        mean("instructions"),
    )


def print_row(label: str, path: Path) -> None:
    n, elapsed, l2, l1, inst = read_means(path)
    print(
        f"{label} n={n} elapsed={elapsed:.3f} "
        f"l2={l2:.3f} l1={l1:.3f} inst={inst:.0f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()

    run_dir = args.run_dir
    if args.baseline.is_file():
        print_row("baseline", args.baseline)
    for csv_path in sorted(
        run_dir.glob("runs/*/detailed_profile/prefetcht1_qsort_538240/per_iteration.csv")
    ):
        if "latest" in csv_path.parts:
            continue
        print_row(csv_path.parts[-4], csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
