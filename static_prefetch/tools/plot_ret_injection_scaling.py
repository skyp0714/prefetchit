#!/usr/bin/env python3
"""Plot PGO-RET and static RET-prefetch scaling by injection count."""

from __future__ import annotations

import argparse
import csv
import math
import shutil
from pathlib import Path


PGO_LABELS = ["baseline", "pgo_ret_cov50", "pgo_ret_cov75", "pgo_ret_cov90", "pgo_ret_cov100"]
STATIC_LABELS = [
    "static_nested_top1500_callsite_b1",
    "static_nested_top1500_mixed_b32",
    "static_nested_top3000_mixed_b32",
    "static_nested_top3000_spread64_b8",
    "static_nested_top5000_spread64_b8",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def finite_float(raw: str | None, default: float = 0.0) -> float:
    try:
        val = float(raw if raw not in (None, "") else default)
    except ValueError:
        return default
    return val if math.isfinite(val) else default


def finite_int(raw: str | None, default: int = 0) -> int:
    try:
        return int(float(raw if raw not in (None, "") else default))
    except ValueError:
        return default


def index_by_label(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["label"]: row for row in rows}


def short_label(label: str) -> str:
    mapping = {
        "baseline": "Baseline",
        "pgo_ret_cov50": "PGO 50%",
        "pgo_ret_cov75": "PGO 75%",
        "pgo_ret_cov90": "PGO 90%",
        "pgo_ret_cov100": "PGO 100%",
        "static_nested_top1500_callsite_b1": "Static 1.5k call",
        "static_nested_top1500_mixed_b32": "Static 10.1k mixed",
        "static_nested_top3000_mixed_b32": "Static 12.2k mixed",
        "static_nested_top3000_spread64_b8": "Static 23.7k spread",
        "static_nested_top5000_spread64_b8": "Static 38.5k spread",
    }
    return mapping.get(label, label)


def pick_rows(rows: list[dict[str, str]], labels: list[str], series: str) -> list[dict[str, str]]:
    by_label = index_by_label(rows)
    picked = []
    for label in labels:
        if label not in by_label:
            continue
        row = dict(by_label[label])
        row["series"] = series
        row["short_label"] = short_label(label)
        if label == "baseline":
            row["planned_injections"] = "0"
            row["planned_prefetches"] = "0"
        picked.append(row)
    return picked


def write_points_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "series",
        "label",
        "short_label",
        "iterations",
        "planned_injections",
        "planned_prefetches",
        "elapsed_sec_mean",
        "elapsed_sec_stdev",
        "speedup_vs_baseline_pct",
        "l2i_mpki_mean",
        "l2i_mpki_stdev",
        "target_weighted_recall",
        "site_weighted_coverage",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_points_md(path: Path, pgo_rows: list[dict[str, str]], static_rows: list[dict[str, str]]) -> None:
    lines = [
        "# RET Prefetch Injection Scaling Points",
        "",
        "Runtime values are measured wall-clock seconds. L2 MPKI is the frontend L2 instruction MPKI from the detailed profile runs.",
        "",
    ]
    for title, rows in (("PGO RET sweep", pgo_rows), ("Static RET sweep", static_rows)):
        lines.extend(
            [
                f"## {title}",
                "",
                "| Point | Injections | Prefetches | N | Runtime (s) | Runtime stdev | L2 MPKI | L2 stdev | Speedup | Target recall | Site coverage |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            recall = finite_float(row.get("target_weighted_recall"), float("nan"))
            coverage = finite_float(row.get("site_weighted_coverage"), float("nan"))
            recall_s = "" if math.isnan(recall) else f"{recall * 100.0:.2f}%"
            coverage_s = "" if math.isnan(coverage) else f"{coverage * 100.0:.2f}%"
            lines.append(
                f"| {row['short_label']} | {finite_int(row.get('planned_injections'))} | "
                f"{finite_int(row.get('planned_prefetches'))} | {finite_int(row.get('iterations'))} | "
                f"{finite_float(row.get('elapsed_sec_mean')):.3f} | {finite_float(row.get('elapsed_sec_stdev')):.3f} | "
                f"{finite_float(row.get('l2i_mpki_mean')):.3f} | {finite_float(row.get('l2i_mpki_stdev')):.3f} | "
                f"{finite_float(row.get('speedup_vs_baseline_pct')):.2f}% | {recall_s} | {coverage_s} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def plot(path: Path, pgo_rows: list[dict[str, str]], static_rows: list[dict[str, str]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    rows = pgo_rows + static_rows
    x = np.arange(len(rows))
    labels = [row["short_label"] for row in rows]
    runtime = np.array([finite_float(row.get("elapsed_sec_mean")) for row in rows])
    runtime_err = np.array([finite_float(row.get("elapsed_sec_stdev")) for row in rows])
    colors = ["#4C78A8" if row["series"] == "pgo_ret" else "#F58518" for row in rows]

    fig, ax1 = plt.subplots(figsize=(18, 8.2))
    bars = ax1.bar(x, runtime, yerr=runtime_err, capsize=5, color=colors, alpha=0.84)
    ax1.set_ylabel("Runtime (s)", fontsize=20)
    ax1.tick_params(axis="y", labelsize=16)
    ax1.grid(axis="y", linestyle="--", alpha=0.25)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=28, ha="right", fontsize=14)
    ax1.set_xlabel("PGO RET-only sweep followed by static RET-prefetch sweep", fontsize=18)
    for xpos, row in zip(x, rows):
        inj = finite_int(row.get("planned_injections"))
        ax1.text(xpos, max(8.0, runtime.max() * 0.015), f"{inj:,}", ha="center", va="bottom", rotation=90, fontsize=11, color="#222222")

    ax2 = ax1.twinx()
    line_handles = []
    line_labels = []
    for series, color, marker, label in (
        ("pgo_ret", "#1F77B4", "o", "PGO L2 MPKI"),
        ("static", "#D62728", "s", "Static L2 MPKI"),
    ):
        idxs = [i for i, row in enumerate(rows) if row["series"] == series]
        l2 = np.array([finite_float(rows[i].get("l2i_mpki_mean")) for i in idxs])
        l2_err = np.array([finite_float(rows[i].get("l2i_mpki_stdev")) for i in idxs])
        handle = ax2.errorbar(idxs, l2, yerr=l2_err, color=color, marker=marker, linewidth=2.8, capsize=4, label=label)
        line_handles.append(handle)
        line_labels.append(label)
    ax2.set_ylabel("L2 MPKI", fontsize=20)
    ax2.tick_params(axis="y", labelsize=16)

    from matplotlib.patches import Patch

    bar_handles = [
        Patch(facecolor="#4C78A8", alpha=0.84, label="PGO runtime"),
        Patch(facecolor="#F58518", alpha=0.84, label="Static runtime"),
    ]
    fig.legend(
        bar_handles + line_handles,
        ["PGO runtime", "Static runtime"] + line_labels,
        loc="lower center",
        ncol=4,
        frameon=False,
        fontsize=16,
        bbox_to_anchor=(0.5, 0.0),
    )
    fig.suptitle("RET Prefetch Scaling: Runtime and L2 MPKI", fontsize=22, y=0.985)
    fig.tight_layout(rect=(0, 0.08, 1, 0.93))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgo-summary", type=Path, required=True)
    parser.add_argument("--static-summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    pgo_rows = pick_rows(read_rows(args.pgo_summary), PGO_LABELS, "pgo_ret")
    static_rows = pick_rows(read_rows(args.static_summary), STATIC_LABELS, "static")
    if len(pgo_rows) < 5:
        raise SystemExit(f"expected 5 PGO points, found {len(pgo_rows)}")
    if len(static_rows) < 5:
        raise SystemExit(f"expected 5 static points, found {len(static_rows)}")

    out_csv = args.out_dir / "ret_pgo_static_injection_scaling_points.csv"
    out_md = args.out_dir / "ret_pgo_static_injection_scaling_points.md"
    out_png = args.out_dir / "ret_pgo_static_injection_scaling_combined.png"
    write_points_csv(out_csv, pgo_rows + static_rows)
    write_points_md(out_md, pgo_rows, static_rows)
    plot(out_png, pgo_rows, static_rows)
    # Keep the historical filename updated too, but print the cache-busting
    # combined filename as the primary artifact.
    shutil.copy2(out_png, args.out_dir / "ret_pgo_static_injection_scaling.png")
    shutil.copy2(out_png.with_suffix(".pdf"), args.out_dir / "ret_pgo_static_injection_scaling.pdf")
    print(out_csv)
    print(out_md)
    print(out_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
