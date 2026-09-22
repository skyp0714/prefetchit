import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

BENCHES = ["tomcat", "finagle-http", "finagle-chirper"]
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


def load_main_style(rows, core_small, core_large):
    data = {}
    by_key = {(r.get("Benchmark", ""), r.get("Mode", "")): r for r in rows}

    for bench in BENCHES:
        small = by_key.get((bench, f"jvm{core_small}c"))
        large = by_key.get((bench, f"jvm{core_large}c"))
        if small:
            data[(bench, core_small)] = (
                safe_float(small.get("L1I_MPKI", "0")),
                safe_float(small.get("L2_MPKI", "0")),
            )
        if large:
            data[(bench, core_large)] = (
                safe_float(large.get("L1I_MPKI", "0")),
                safe_float(large.get("L2_MPKI", "0")),
            )

    if len(data) > 0:
        return data

    # Fallback to whatever jvm*c rows exist if explicit core labels were not found.
    for row in rows:
        bench = row.get("Benchmark", "")
        mode = row.get("Mode", "")
        if bench not in BENCHES or not mode.startswith("jvm") or not mode.endswith("c"):
            continue
        core = safe_int(mode[3:-1], -1)
        if core <= 0:
            continue
        data[(bench, core)] = (
            safe_float(row.get("L1I_MPKI", "0")),
            safe_float(row.get("L2_MPKI", "0")),
        )
    return data


def load_legacy_style(rows):
    data = {}
    for row in rows:
        bench = row.get("Benchmark", "")
        if bench not in BENCHES:
            continue
        core = safe_int(row.get("CoreCount", "-1"), -1)
        if core <= 0:
            continue
        data[(bench, core)] = (
            safe_float(row.get("L1I_MPKI", "0")),
            safe_float(row.get("L2_MPKI", "0")),
        )
    return data


def load_data(path: Path, core_small: int, core_large: int):
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}

    cols = set(rows[0].keys())
    if "Mode" in cols:
        return load_main_style(rows, core_small, core_large)
    return load_legacy_style(rows)


def choose_cores(data, requested_small, requested_large):
    available = sorted({core for (_, core) in data.keys()})
    if not available:
        return requested_small, requested_large
    core_small = requested_small if requested_small in available else available[0]
    core_large = requested_large if requested_large in available else available[-1]
    return core_small, core_large


def main():
    ap = argparse.ArgumentParser(description="Plot core0 MPKI comparison (small core set vs large core set)")
    ap.add_argument("--input", required=True, help="Input CSV (main_frontend_all.csv preferred)")
    ap.add_argument("--output", required=True, help="Output PNG path")
    ap.add_argument("--core-small", type=int, default=1, help="Small core-count configuration")
    ap.add_argument("--core-large", type=int, default=86, help="Large core-count configuration")
    args = ap.parse_args()

    data = load_data(Path(args.input), args.core_small, args.core_large)
    if not data:
        raise RuntimeError(f"No JVM MPKI rows found in {args.input}")
    apply_plot_style()

    core_small, core_large = choose_cores(data, args.core_small, args.core_large)

    x = np.arange(len(BENCHES))
    width = 0.35

    l1_small = [data.get((b, core_small), (0.0, 0.0))[0] for b in BENCHES]
    l1_large = [data.get((b, core_large), (0.0, 0.0))[0] for b in BENCHES]
    l2_small = [data.get((b, core_small), (0.0, 0.0))[1] for b in BENCHES]
    l2_large = [data.get((b, core_large), (0.0, 0.0))[1] for b in BENCHES]

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    ax0, ax1 = axes

    ax0.bar(x - width / 2, l1_small, width, label=f"{core_small} core")
    ax0.bar(x + width / 2, l1_large, width, label=f"{core_large} cores")
    ax0.set_title("Core0 L1I MPKI")
    ax0.set_ylabel("MPKI")
    ax0.set_xticks(x)
    ax0.set_xticklabels(BENCHES, rotation=15, ha="right")
    ax0.grid(axis="y", alpha=0.3, linestyle="--")
    ax0.legend()

    ax1.bar(x - width / 2, l2_small, width, label=f"{core_small} core")
    ax1.bar(x + width / 2, l2_large, width, label=f"{core_large} cores")
    ax1.set_title("Core0 L2 inst. MPKI")
    ax1.set_ylabel("MPKI")
    ax1.set_xticks(x)
    ax1.set_xticklabels(BENCHES, rotation=15, ha="right")
    ax1.grid(axis="y", alpha=0.3, linestyle="--")
    ax1.legend()

    fig.suptitle(f"Core0 Frontend MPKI: {core_small} Core vs {core_large} Cores")
    plt.tight_layout()
    plt.savefig(args.output, dpi=300, bbox_inches="tight")


if __name__ == "__main__":
    main()
