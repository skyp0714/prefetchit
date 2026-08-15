#!/usr/bin/env python3
"""Print compact means for completed detailed-profile CSVs in a run directory."""

from __future__ import annotations

import csv
import math
import statistics
import sys
from pathlib import Path


BASELINE = Path(
    "/home/hnpark2/prefetchit/llvm_prefetchit/results/prefetch_plateau/"
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
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} RUN_DIR", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1])
    if BASELINE.exists():
        print_row("baseline", BASELINE)
    for csv_path in sorted(
        run_dir.glob("runs/*/detailed_profile/prefetcht1_qsort_538240/per_iteration.csv")
    ):
        if "latest" in csv_path.parts:
            continue
        print_row(csv_path.parts[-4], csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
