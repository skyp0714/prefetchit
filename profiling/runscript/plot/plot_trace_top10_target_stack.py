#!/usr/bin/env python3
import argparse
import csv
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


def ensure_mpl_config_dir():
    if os.environ.get("MPLCONFIGDIR"):
        return
    default_cfg = Path.home() / ".config" / "matplotlib"
    if default_cfg.exists() and os.access(default_cfg, os.W_OK):
        return
    fallback = Path(tempfile.gettempdir()) / f"matplotlib-{os.getuid()}"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(fallback)


ensure_mpl_config_dir()

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter

BRANCH_ORDER = ["COND", "UNCOND", "CALL", "RET", "IND", "IND_CALL"]
TRACE_LABELS = {
    "l2_miss": "L2",
    "l3_miss": "L3",
    "dsb_miss": "L3",
    "itlb_miss": "iTLB",
    "stlb_miss": "sTLB",
}
TOP_N = 10
FONT_SCALE = 2.0


def apply_plot_style():
    base = float(plt.rcParams.get("font.size", 10.0))
    scaled = base * FONT_SCALE
    plt.rcParams.update(
        {
            "font.size": scaled,
            "axes.titlesize": scaled,
            "axes.labelsize": scaled,
            "xtick.labelsize": scaled,
            "ytick.labelsize": scaled,
            "legend.fontsize": scaled,
            "figure.titlesize": scaled,
        }
    )


def safe_int(text: str) -> int:
    try:
        return int(float(text))
    except Exception:
        return 0


def trace_label(trace_name: str) -> str:
    return TRACE_LABELS.get(trace_name, trace_name)


def resolve_trace_name(trace_root: Path, trace_name: str) -> str | None:
    if (trace_root / trace_name / "target_branch_counts.csv").exists():
        return trace_name
    if trace_name == "l3_miss" and (trace_root / "dsb_miss" / "target_branch_counts.csv").exists():
        return "dsb_miss"
    return None


def load_branch_target_counts(path: Path) -> dict[str, Counter]:
    out: defaultdict[str, Counter] = defaultdict(Counter)
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            bt = row.get("branch_type", "").strip()
            if bt not in BRANCH_ORDER:
                continue
            target = row.get("target", "").strip()
            cnt = safe_int(row.get("count", "0"))
            if not target or cnt <= 0:
                continue
            out[bt][target] += cnt
    return dict(out)


def derive_companion(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def build_tables(trace_root: Path, trace_names: list[str], top_n: int):
    traces: list[str] = []
    for name in trace_names:
        found = resolve_trace_name(trace_root, name)
        if found and found not in traces:
            traces.append(found)
    if not traces:
        raise RuntimeError("No valid trace directories with target_branch_counts.csv were found.")

    detail_labels = [f"T{i}" for i in range(1, top_n + 1)] + ["O"]
    merged_labels = ["TOP10", "O"]

    detail_ratio: defaultdict[tuple[str, str, str], float] = defaultdict(float)
    merged_ratio: defaultdict[tuple[str, str, str], float] = defaultdict(float)
    detail_rows: list[dict] = []
    merged_rows: list[dict] = []

    for tr in traces:
        in_csv = trace_root / tr / "target_branch_counts.csv"
        by_branch = load_branch_target_counts(in_csv)
        branch_totals = {bt: sum(by_branch.get(bt, Counter()).values()) for bt in BRANCH_ORDER}
        trace_total = sum(branch_totals.values())

        for bt in BRANCH_ORDER:
            bt_total = branch_totals[bt]
            top_items = by_branch.get(bt, Counter()).most_common(top_n)
            top_sum = 0
            top_targets = []

            for rank in range(1, top_n + 1):
                bucket = f"T{rank}"
                target = ""
                cnt = 0
                if rank <= len(top_items):
                    target, cnt = top_items[rank - 1]
                    top_targets.append(target)
                top_sum += cnt

                ratio_trace = (float(cnt) / float(trace_total)) if trace_total > 0 else 0.0
                ratio_branch = (float(cnt) / float(bt_total)) if bt_total > 0 else 0.0
                detail_ratio[(tr, bt, bucket)] = ratio_trace
                detail_rows.append(
                    {
                        "trace_name": tr,
                        "trace_label": trace_label(tr),
                        "branch_type": bt,
                        "bucket": bucket,
                        "target": target,
                        "count": cnt,
                        "ratio_in_trace": f"{ratio_trace:.10f}",
                        "ratio_in_branch": f"{ratio_branch:.10f}",
                        "trace_total_count": trace_total,
                        "branch_total_count": bt_total,
                    }
                )

            others = max(0, bt_total - top_sum)
            ratio_trace_others = (float(others) / float(trace_total)) if trace_total > 0 else 0.0
            ratio_branch_others = (float(others) / float(bt_total)) if bt_total > 0 else 0.0
            detail_ratio[(tr, bt, "O")] = ratio_trace_others
            detail_rows.append(
                {
                    "trace_name": tr,
                    "trace_label": trace_label(tr),
                    "branch_type": bt,
                    "bucket": "O",
                    "target": "Others",
                    "count": others,
                    "ratio_in_trace": f"{ratio_trace_others:.10f}",
                    "ratio_in_branch": f"{ratio_branch_others:.10f}",
                    "trace_total_count": trace_total,
                    "branch_total_count": bt_total,
                }
            )

            ratio_trace_top10 = (float(top_sum) / float(trace_total)) if trace_total > 0 else 0.0
            ratio_branch_top10 = (float(top_sum) / float(bt_total)) if bt_total > 0 else 0.0
            merged_ratio[(tr, bt, "TOP10")] = ratio_trace_top10
            merged_ratio[(tr, bt, "O")] = ratio_trace_others

            merged_rows.append(
                {
                    "trace_name": tr,
                    "trace_label": trace_label(tr),
                    "branch_type": bt,
                    "bucket": "TOP10",
                    "count": top_sum,
                    "ratio_in_trace": f"{ratio_trace_top10:.10f}",
                    "ratio_in_branch": f"{ratio_branch_top10:.10f}",
                    "trace_total_count": trace_total,
                    "branch_total_count": bt_total,
                    "local_top_targets": " | ".join(top_targets),
                }
            )
            merged_rows.append(
                {
                    "trace_name": tr,
                    "trace_label": trace_label(tr),
                    "branch_type": bt,
                    "bucket": "O",
                    "count": others,
                    "ratio_in_trace": f"{ratio_trace_others:.10f}",
                    "ratio_in_branch": f"{ratio_branch_others:.10f}",
                    "trace_total_count": trace_total,
                    "branch_total_count": bt_total,
                    "local_top_targets": "",
                }
            )

    return traces, detail_labels, merged_labels, detail_ratio, merged_ratio, detail_rows, merged_rows


def build_plot_layout(traces: list[str]):
    traces_n = len(traces)
    branches_n = len(BRANCH_ORDER)
    group_gap = 1.35
    x_vals: list[float] = []
    x_labels: list[str] = []
    meta: list[tuple[str, str]] = []
    centers: list[float] = []

    for t_idx, tr in enumerate(traces):
        base = t_idx * (branches_n + group_gap)
        local_x = []
        for b_idx, bt in enumerate(BRANCH_ORDER):
            x = base + b_idx
            x_vals.append(x)
            x_labels.append(bt)
            meta.append((tr, bt))
            local_x.append(x)
        centers.append(float(np.mean(local_x)))
    return x_vals, x_labels, meta, centers


def plot_stacked(
    out_png: Path,
    traces: list[str],
    stack_labels: list[str],
    ratio_map: dict[tuple[str, str, str], float],
    legend_title: str,
):
    x_vals, x_labels, meta, centers = build_plot_layout(traces)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig_w = max(16.0, len(traces) * len(BRANCH_ORDER) * 0.62)
    fig, ax = plt.subplots(figsize=(fig_w, 7.3))

    if len(stack_labels) <= 2:
        palette = ["#2f7ed8", "#d9d9d9"]
    else:
        palette = list(plt.cm.tab20.colors) + list(plt.cm.Set3.colors)

    bottom = np.zeros(len(meta), dtype=float)
    for i, bucket in enumerate(stack_labels):
        values = []
        for tr, bt in meta:
            values.append(float(ratio_map.get((tr, bt, bucket), 0.0)))
        vals_np = np.array(values, dtype=float)
        ax.bar(
            x_vals,
            vals_np,
            width=0.86,
            bottom=bottom,
            color=palette[i % len(palette)],
            edgecolor="none",
            label=bucket,
        )
        bottom += vals_np

    ax.set_ylabel("Percentage")
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    ax.set_xticks(x_vals)
    ax.set_xticklabels(x_labels, rotation=52, ha="right")
    ax.set_xlabel("Branch type")
    ax.grid(axis="y", linestyle="--", alpha=0.30)
    ax.set_xlim(min(x_vals) - 0.7, max(x_vals) + 0.7)

    for i in range(1, len(centers)):
        boundary = 0.5 * (centers[i - 1] + centers[i])
        ax.axvline(boundary, color="#bdbdbd", linewidth=1.2, linestyle="-")

    ax_top = ax.twiny()
    ax_top.set_xlim(ax.get_xlim())
    ax_top.set_xticks(centers)
    ax_top.set_xticklabels([trace_label(t) for t in traces])
    ax_top.set_xlabel("Miss level")

    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), title=legend_title, frameon=True)
    plt.tight_layout(rect=[0, 0, 0.82, 1.0])
    plt.savefig(out_png, dpi=220)
    plt.close(fig)


def write_csv(out_csv: Path, rows: list[dict], fieldnames: list[str]):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser(
        description="Plot absolute-ratio stacked bars by miss-cause x branch-type with local top-N targets."
    )
    ap.add_argument("--trace-root", required=True, help="root directory containing per-trace subdirectories")
    ap.add_argument("--trace-names", default="l2_miss,l3_miss,itlb_miss,stlb_miss")
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--out-detail-png", default="")
    ap.add_argument("--out-detail-csv", default="")
    ap.add_argument("--out-merged-png", default="")
    ap.add_argument("--out-merged-csv", default="")
    # Legacy args (backward compatibility).
    ap.add_argument("--out-png", default="")
    ap.add_argument("--out-csv", default="")
    args = ap.parse_args()

    trace_root = Path(args.trace_root)
    requested = [x.strip() for x in args.trace_names.split(",") if x.strip()]
    if not requested:
        raise RuntimeError("trace-names cannot be empty")

    detail_png_arg = args.out_detail_png or args.out_png
    detail_csv_arg = args.out_detail_csv or args.out_csv
    if not detail_png_arg or not detail_csv_arg:
        raise RuntimeError("detail outputs are required: --out-detail-png/--out-detail-csv (or legacy --out-png/--out-csv)")

    detail_png = Path(detail_png_arg)
    detail_csv = Path(detail_csv_arg)
    merged_png = Path(args.out_merged_png) if args.out_merged_png else derive_companion(detail_png, "_merged")
    merged_csv = Path(args.out_merged_csv) if args.out_merged_csv else derive_companion(detail_csv, "_merged")

    top_n = max(1, int(args.top_n))
    apply_plot_style()
    traces, detail_labels, merged_labels, detail_ratio, merged_ratio, detail_rows, merged_rows = build_tables(
        trace_root, requested, top_n
    )

    write_csv(
        detail_csv,
        detail_rows,
        [
            "trace_name",
            "trace_label",
            "branch_type",
            "bucket",
            "target",
            "count",
            "ratio_in_trace",
            "ratio_in_branch",
            "trace_total_count",
            "branch_total_count",
        ],
    )
    write_csv(
        merged_csv,
        merged_rows,
        [
            "trace_name",
            "trace_label",
            "branch_type",
            "bucket",
            "count",
            "ratio_in_trace",
            "ratio_in_branch",
            "trace_total_count",
            "branch_total_count",
            "local_top_targets",
        ],
    )

    plot_stacked(
        detail_png,
        traces,
        detail_labels,
        detail_ratio,
        legend_title="T1..T10 + O",
    )
    plot_stacked(
        merged_png,
        traces,
        merged_labels,
        merged_ratio,
        legend_title="TOP10 + O",
    )


if __name__ == "__main__":
    main()
