#!/usr/bin/env python3
"""Summarize repeated L2I/LBR profiles and miss-target determinism."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import Counter
from pathlib import Path


TOP_KS = (10, 25, 50, 100)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--trace-dir", action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def read_branch_counts(trace_dir: Path) -> Counter[str]:
    path = trace_dir / "branch_type_distribution.csv"
    counts: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            counts[row["branch_type"].upper()] += int(row["count"])
    return counts


def read_target_counts(trace_dir: Path) -> Counter[str]:
    path = trace_dir / "target_branch_counts.csv"
    counts: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            # The analyzer groups the same missed code location by target key;
            # branch type is intentionally not part of determinism identity.
            counts[row["target"]] += int(row["count"])
    return counts


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def main() -> None:
    args = parse_args()
    trace_dirs = [Path(path).resolve() for path in args.trace_dir]
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for trace_dir in trace_dirs:
        for filename in ("branch_type_distribution.csv", "target_branch_counts.csv"):
            if not (trace_dir / filename).is_file():
                raise SystemExit(f"missing {trace_dir / filename}")

    branch_by_rep = [read_branch_counts(path) for path in trace_dirs]
    target_by_rep = [read_target_counts(path) for path in trace_dirs]

    aggregate_branch: Counter[str] = Counter()
    for counts in branch_by_rep:
        aggregate_branch.update(counts)
    branch_total = sum(aggregate_branch.values())
    branch_rows = []
    for branch_type, count in aggregate_branch.most_common():
        branch_rows.append(
            {
                "benchmark": args.benchmark,
                "rep_count": len(trace_dirs),
                "branch_type": branch_type,
                "count": count,
                "ratio_pct": 100.0 * count / branch_total if branch_total else 0.0,
            }
        )
    write_csv(
        out_dir / "branch_type_summary.csv",
        ["benchmark", "rep_count", "branch_type", "count", "ratio_pct"],
        branch_rows,
    )

    overlap_rows = []
    for top_k in TOP_KS:
        top_sets = [set(key for key, _ in counts.most_common(top_k)) for counts in target_by_rep]
        pairwise = []
        weighted_pairwise = []
        for left, right in itertools.combinations(top_sets, 2):
            union = left | right
            pairwise.append(len(left & right) / len(union) if union else 1.0)
        for left_counts, right_counts in itertools.combinations(target_by_rep, 2):
            left_total = sum(left_counts.values())
            right_total = sum(right_counts.values())
            keys = set(key for key, _ in left_counts.most_common(top_k))
            keys |= set(key for key, _ in right_counts.most_common(top_k))
            weighted_pairwise.append(
                sum(
                    min(
                        left_counts[key] / left_total if left_total else 0.0,
                        right_counts[key] / right_total if right_total else 0.0,
                    )
                    for key in keys
                )
            )
        shares = []
        for counts in target_by_rep:
            total = sum(counts.values())
            shares.append(
                sum(value for _, value in counts.most_common(top_k)) / total if total else 0.0
            )
        overlap_rows.append(
            {
                "benchmark": args.benchmark,
                "top_k": top_k,
                "rep_count": len(trace_dirs),
                "mean_pairwise_jaccard": mean(pairwise) if pairwise else 1.0,
                "min_pairwise_jaccard": min(pairwise) if pairwise else 1.0,
                "mean_pairwise_sample_overlap": mean(weighted_pairwise) if weighted_pairwise else 1.0,
                "min_pairwise_sample_overlap": min(weighted_pairwise) if weighted_pairwise else 1.0,
                "mean_topk_sample_share": mean(shares),
            }
        )
    write_csv(
        out_dir / "target_overlap_summary.csv",
        [
            "benchmark",
            "top_k",
            "rep_count",
            "mean_pairwise_jaccard",
            "min_pairwise_jaccard",
            "mean_pairwise_sample_overlap",
            "min_pairwise_sample_overlap",
            "mean_topk_sample_share",
        ],
        overlap_rows,
    )

    aggregate_targets: Counter[str] = Counter()
    target_rep_presence: Counter[str] = Counter()
    for counts in target_by_rep:
        aggregate_targets.update(counts)
        target_rep_presence.update(counts.keys())
    target_rows = []
    total_target_samples = sum(aggregate_targets.values())
    for rank, (target, count) in enumerate(aggregate_targets.most_common(), start=1):
        target_rows.append(
            {
                "rank": rank,
                "target": target,
                "samples": count,
                "sample_share_pct": 100.0 * count / total_target_samples if total_target_samples else 0.0,
                "reps_present": target_rep_presence[target],
                "rep_presence_pct": 100.0 * target_rep_presence[target] / len(trace_dirs),
            }
        )
    write_csv(
        out_dir / "target_repeatability.csv",
        ["rank", "target", "samples", "sample_share_pct", "reps_present", "rep_presence_pct"],
        target_rows,
    )

    summary = {
        "benchmark": args.benchmark,
        "trace_dirs": [str(path) for path in trace_dirs],
        "rep_count": len(trace_dirs),
        "branch_samples": branch_total,
        "target_samples": total_target_samples,
        "top_branch_type": branch_rows[0]["branch_type"] if branch_rows else "",
        "top_branch_ratio_pct": branch_rows[0]["ratio_pct"] if branch_rows else 0.0,
        "top10_mean_jaccard": overlap_rows[0]["mean_pairwise_jaccard"],
        "top10_mean_sample_overlap": overlap_rows[0]["mean_pairwise_sample_overlap"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
