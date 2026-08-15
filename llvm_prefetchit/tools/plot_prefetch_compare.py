#!/usr/bin/env python3
"""Plot baseline vs prefetcht/prefetchit runtime and L2I MPKI."""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import tempfile
from pathlib import Path


def setup_matplotlib_cache() -> None:
    default_cfg = Path.home() / ".config" / "matplotlib"
    if os.access(default_cfg.parent, os.W_OK):
        return
    fallback = Path(tempfile.gettempdir()) / f"matplotlib-{os.getuid()}"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(fallback))


setup_matplotlib_cache()
import matplotlib.pyplot as plt  # noqa: E402


METRICS = ("elapsed_sec", "l2i_mpki")


def parse_input(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError("inputs must be LABEL=/path/to/per_iteration.csv")
    label, path = spec.split("=", 1)
    label = label.strip()
    if not label:
        raise argparse.ArgumentTypeError("empty label")
    return label, Path(path).resolve()


def read_rows(label: str, path: Path) -> list[dict[str, float | str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    out: list[dict[str, float | str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rec: dict[str, float | str] = {"label": label, "iteration": row.get("iteration", "")}
            for metric in METRICS:
                value = float(row.get(metric, "nan"))
                if not math.isfinite(value) or value <= 0.0:
                    raise ValueError(f"invalid {metric}={value!r} in {path}")
                rec[metric] = value
            out.append(rec)
    if not out:
        raise ValueError(f"no rows in {path}")
    return out


def write_combined(path: Path, rows: list[dict[str, float | str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["label", "iteration", *METRICS])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize(labels: list[str], rows: list[dict[str, float | str]]) -> list[dict[str, str]]:
    base = labels[0]
    by_label: dict[str, list[dict[str, float | str]]] = {label: [] for label in labels}
    for row in rows:
        by_label[str(row["label"])].append(row)

    base_means = {
        metric: statistics.fmean(float(r[metric]) for r in by_label[base]) for metric in METRICS
    }
    summary: list[dict[str, str]] = []
    for label in labels:
        recs = by_label[label]
        out = {"label": label, "n": str(len(recs))}
        for metric in METRICS:
            vals = [float(r[metric]) for r in recs]
            mean = statistics.fmean(vals)
            stdev = statistics.stdev(vals) if len(vals) >= 2 else 0.0
            delta = (mean - base_means[metric]) / base_means[metric] * 100.0
            out[f"{metric}_mean"] = f"{mean:.6f}"
            out[f"{metric}_stdev"] = f"{stdev:.6f}"
            out[f"{metric}_delta_pct"] = f"{delta:+.6f}"
        summary.append(out)
    return summary


def write_summary_csv(path: Path, summary: list[dict[str, str]]) -> None:
    fieldnames = [
        "label",
        "n",
        "elapsed_sec_mean",
        "elapsed_sec_stdev",
        "elapsed_sec_delta_pct",
        "l2i_mpki_mean",
        "l2i_mpki_stdev",
        "l2i_mpki_delta_pct",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)


def write_summary_md(path: Path, summary: list[dict[str, str]]) -> None:
    lines = [
        "# Prefetch Compare Summary",
        "",
        "| Binary | N | Runtime mean | Runtime stdev | Runtime delta | L2I MPKI mean | L2I MPKI stdev | L2I delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            "| {label} | {n} | {elapsed_sec_mean} | {elapsed_sec_stdev} | {elapsed_sec_delta_pct}% | "
            "{l2i_mpki_mean} | {l2i_mpki_stdev} | {l2i_mpki_delta_pct}% |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 32,
            "axes.labelsize": 32,
            "xtick.labelsize": 32,
            "ytick.labelsize": 32,
            "legend.fontsize": 32,
            "figure.facecolor": "white",
            "axes.facecolor": "#fbfaf7",
            "axes.edgecolor": "#242424",
            "axes.grid": True,
            "grid.color": "#d8d2c4",
            "grid.alpha": 0.65,
            "grid.linestyle": "-",
        }
    )


def display_label(label: str) -> str:
    mapping = {
        "baseline": "Baseline",
        "prefetcht1": "Data Prefetch",
        "prefetchit1": "Code Prefetch",
    }
    return mapping.get(label, label.replace("_", " ").title())


def set_zoomed_ylim(ax, values: list[float]) -> None:
    low = min(values)
    high = max(values)
    span = high - low
    margin = span * 0.08 if span > 0 else max(abs(high) * 0.02, 1.0)
    ax.set_ylim(low - margin, high + margin)


def add_yaxis_break(ax) -> None:
    # Draw a small sine-wave break marker over the lower y-axis spine.
    points = 40
    xs = [-0.025 + 0.05 * i / (points - 1) for i in range(points)]
    ys = [0.035 + 0.010 * math.sin(i / (points - 1) * math.tau * 2.0) for i in range(points)]
    ax.plot(xs, ys, transform=ax.transAxes, color="#242424", linewidth=2.6, clip_on=False)


def plot(path: Path, labels: list[str], rows: list[dict[str, float | str]], summary: list[dict[str, str]]) -> None:
    apply_style()
    colors = ["#4b5563", "#2563eb", "#d97706", "#059669", "#7c3aed"]
    data = {label: {metric: [] for metric in METRICS} for label in labels}
    for row in rows:
        for metric in METRICS:
            data[str(row["label"])][metric].append(float(row[metric]))

    fig, axes = plt.subplots(1, 2, figsize=(24, 10))
    for ax, metric, ylabel in zip(axes, METRICS, ("Runtime (s)", "L2I MPKI")):
        vals = [data[label][metric] for label in labels]
        bp = ax.boxplot(vals, patch_artist=True, widths=0.55, showfliers=False)
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.22)
            patch.set_edgecolor(color)
            patch.set_linewidth(2.0)
        for key in ("whiskers", "caps", "medians"):
            for line in bp[key]:
                line.set_color("#1f2937")
                line.set_linewidth(2.2)
        ax.set_xticks(range(1, len(labels) + 1), [display_label(label) for label in labels])
        ax.set_ylabel(ylabel)
        ax.set_xlabel("")
        set_zoomed_ylim(ax, [value for group in vals for value in group])
        add_yaxis_break(ax)
    fig.suptitle("Verilator Prefetch Result", fontsize=32, y=0.99)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", action="append", type=parse_input, required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = [label for label, _ in args.input]
    if len(set(labels)) != len(labels):
        raise ValueError("duplicate labels")

    rows: list[dict[str, float | str]] = []
    for label, path in args.input:
        rows.extend(read_rows(label, path))
    summary = summarize(labels, rows)

    write_combined(out_dir / "prefetch_compare_iterations.csv", rows)
    write_summary_csv(out_dir / "prefetch_compare_summary.csv", summary)
    write_summary_md(out_dir / "prefetch_compare_summary.md", summary)
    plot(out_dir / "prefetch_compare_boxplot.png", labels, rows, summary)

    print(f"[ok] wrote {out_dir / 'prefetch_compare_summary.md'}")
    print(f"[ok] wrote {out_dir / 'prefetch_compare_boxplot.png'}")


if __name__ == "__main__":
    main()
