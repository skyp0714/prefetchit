import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

ORDER = ["tomcat", "finagle-http", "finagle-chirper"]
FONT_SCALE = 2.0
COLORS = {
    "tomcat": "#1f77b4",
    "finagle-http": "#ff7f0e",
    "finagle-chirper": "#2ca02c",
}


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
            "figure.titlesize": scaled * 1.05,
        }
    )


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def safe_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


def load_data(path: Path):
    out = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return out

    cols = set(rows[0].keys())
    has_new_schema = "CtxSwitchesPerMInst" in cols or "ContextSwitches" in cols

    for row in rows:
        bench = row.get("Benchmark", "")
        if bench not in ORDER:
            continue

        cores = safe_int(row.get("CoreCount", "0"), 0)
        if cores <= 0:
            continue

        rc = safe_int(row.get("ReturnCode", "0"), 0)
        if "ReturnCode" in cols and rc != 0:
            continue

        threads_avg = safe_float(row.get("ThreadsAvg", "0"), 0.0)
        per_core = safe_float(row.get("PerCoreThreadsAvg", "0"), 0.0)

        # Count/frequency metrics from perf stat.
        ctx_count = safe_float(row.get("ContextSwitches", "0"), 0.0)

        # Frequency metric (context-switches per million instructions)
        freq = 0.0
        if has_new_schema:
            freq = safe_float(row.get("CtxSwitchesPerMInst", "0"), 0.0)
            if freq <= 0.0:
                inst = safe_float(row.get("Instructions", "0"), 0.0)
                if inst > 0.0:
                    freq = (ctx_count * 1_000_000.0) / inst

        out[bench].append((cores, per_core, threads_avg, freq, ctx_count))

    for bench in out:
        out[bench].sort(key=lambda x: x[0])
    return out


def setup_axis(ax):
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 86, 128])
    ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())
    ax.grid(alpha=0.3, linestyle="--")
    ax.set_xlabel("Allowed cores")


def plot_thread_scaling(data, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.1))
    ax0, ax1 = axes

    for bench in ORDER:
        pts = data.get(bench, [])
        if not pts:
            continue
        x = [p[0] for p in pts]
        y_per_core = [p[1] for p in pts]
        y_total = [p[2] for p in pts]
        ax0.plot(x, y_per_core, marker="o", linewidth=2.0, label=bench, color=COLORS.get(bench))
        ax1.plot(x, y_total, marker="o", linewidth=2.0, label=bench, color=COLORS.get(bench))

    for ax in axes:
        setup_axis(ax)

    ax0.set_title("Per-Core Java Threads")
    ax0.set_ylabel("Average Java threads / core")
    ax1.set_title("Total Java Threads")
    ax1.set_ylabel("Average Java threads")
    ax1.legend(loc="best")

    fig.suptitle("Context-Switch Sweep: Thread Scaling")
    plt.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_count_and_frequency(data, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2))
    ax0, ax1 = axes
    for bench in ORDER:
        pts = data.get(bench, [])
        if not pts:
            continue
        x_count = [p[0] for p in pts if p[4] > 0.0]
        y_count = [p[4] for p in pts if p[4] > 0.0]
        x_freq = [p[0] for p in pts if p[3] > 0.0]
        y_freq = [p[3] for p in pts if p[3] > 0.0]
        if x_count:
            ax0.plot(x_count, y_count, marker="o", linewidth=2.0, label=bench, color=COLORS.get(bench))
        if x_freq:
            ax1.plot(x_freq, y_freq, marker="o", linewidth=2.0, label=bench, color=COLORS.get(bench))

    setup_axis(ax0)
    setup_axis(ax1)
    ax0.set_ylabel("Total context switches")
    ax0.set_title("Core0 Context Switch Count vs Core Count")
    ax1.set_ylabel("Context switches per million instructions")
    ax1.set_title("Core0 Context Switch Frequency vs Core Count")
    ax1.legend(loc="best")
    fig.suptitle("Core0 Context Switch Count/Frequency")
    plt.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Plot context-switch thread scaling and frequency")
    ap.add_argument("--input", required=True, help="CSV from run_jvm_thread_scaling.sh")
    ap.add_argument("--out-thread", required=True, help="Output PNG for thread scaling")
    ap.add_argument("--out-frequency", required=True, help="Output PNG for context-switch count/frequency")
    args = ap.parse_args()

    apply_plot_style()
    data = load_data(Path(args.input))
    plot_thread_scaling(data, Path(args.out_thread))
    plot_count_and_frequency(data, Path(args.out_frequency))

    print(f"Saved: {args.out_thread}")
    print(f"Saved: {args.out_frequency}")


if __name__ == "__main__":
    main()
