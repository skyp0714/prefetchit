#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

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
            "figure.titlesize": scaled * 1.05,
        }
    )


def load_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def metric_map(rows, scenario: str, metric: str):
    out = {}
    for r in rows:
        if r.get("Scenario") != scenario:
            continue
        try:
            cpu = int(float(r.get("CPU", "0")))
            val = float(r.get(metric, "0"))
        except ValueError:
            continue
        out[cpu] = val
    return out


def system_metric(rows, scenario: str, metric: str):
    key = f"System_{metric}"
    for r in rows:
        if r.get("Scenario") == scenario:
            try:
                return float(r.get(key, "0"))
            except ValueError:
                return 0.0
    return 0.0


def save_metric_plot(rows, metric: str, ylabel: str, out_png: Path):
    idle = metric_map(rows, "kernel_idle", metric)
    busy = metric_map(rows, "kernel_busy", metric)
    cpus = sorted(set(idle.keys()) | set(busy.keys()))
    if not cpus:
        raise SystemExit(f"[err] no CPU rows for metric {metric}")

    idle_vals = [idle.get(c, 0.0) for c in cpus]
    busy_vals = [busy.get(c, 0.0) for c in cpus]

    idle_sys = system_metric(rows, "kernel_idle", metric)
    busy_sys = system_metric(rows, "kernel_busy", metric)

    x = list(range(len(cpus)))
    width = 0.42
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.bar([i - width / 2 for i in x], idle_vals, width=width, label="kernel_idle (per-core)")
    ax.bar([i + width / 2 for i in x], busy_vals, width=width, label="kernel_busy (per-core)")

    ax.axhline(idle_sys, color="red", linestyle="--", linewidth=1.8, label="kernel_idle system")
    ax.axhline(busy_sys, color="darkred", linestyle="-.", linewidth=1.8, label="kernel_busy system")

    step = 1
    if len(cpus) > 64:
        step = 4
    elif len(cpus) > 24:
        step = 2

    ax.set_xticks(x[::step], [str(c) for c in cpus[::step]])
    ax.set_xlabel("CPU Core")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel}: kernel_idle vs kernel_busy (per-core + system)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="upper right", ncol=2)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)
    print(f"[ok] saved {out_png}")


def main():
    ap = argparse.ArgumentParser(description="Plot kernel idle/busy per-core MPKI with system reference lines")
    ap.add_argument("--input", required=True, help="kernel_idle_busy_percore.csv")
    ap.add_argument("--out-l1i", required=True, help="Output PNG for L1I MPKI")
    ap.add_argument("--out-l2i", required=True, help="Output PNG for L2 inst MPKI")
    args = ap.parse_args()

    apply_plot_style()
    rows = load_rows(Path(args.input))
    save_metric_plot(rows, "L1I_MPKI", "L1i MPKI", Path(args.out_l1i))
    save_metric_plot(rows, "L2I_MPKI", "L2 inst MPKI", Path(args.out_l2i))


if __name__ == "__main__":
    main()
