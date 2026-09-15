import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

JVM_BENCHES = ("tomcat", "finagle-http", "finagle-chirper")
SPEC_BENCHES = ("602.gcc_s", "605.mcf_s", "641.leela_s")
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


def row_lookup(rows):
    d = {}
    for r in rows:
        key = (r.get("Benchmark", ""), r.get("Mode", ""))
        d[key] = r
    return d


def get_metric(row, name):
    return float(row.get(name, "0") or 0)


def build_variant_metrics(lookup, jvm_mode: str):
    metrics = {}
    for bench in JVM_BENCHES:
        r = lookup.get((bench, jvm_mode))
        if not r:
            raise RuntimeError(f"Missing row for {bench}/{jvm_mode}")
        metrics[bench] = {
            "L1I MPKI": get_metric(r, "L1I_MPKI"),
            "L2 MPKI": get_metric(r, "L2_MPKI"),
            "iTLB MPKI": get_metric(r, "iTLB_MPKI"),
            "sTLB MPKI": get_metric(r, "sTLB_MPKI"),
        }

    shared = lookup.get(("verilator", "shared")) or lookup.get(("verilator-qsort", "shared"))
    if not shared:
        raise RuntimeError("Missing row for verilator/shared")
    metrics["verilator"] = {
        "L1I MPKI": get_metric(shared, "L1I_MPKI"),
        "L2 MPKI": get_metric(shared, "L2_MPKI"),
        "iTLB MPKI": get_metric(shared, "iTLB_MPKI"),
        "sTLB MPKI": get_metric(shared, "sTLB_MPKI"),
    }

    spec_vals = {"L1I MPKI": [], "L2 MPKI": [], "iTLB MPKI": [], "sTLB MPKI": []}
    for b in SPEC_BENCHES:
        r = lookup.get((b, "shared"))
        if not r:
            raise RuntimeError(f"Missing row for {b}/shared")
        for k in spec_vals:
            spec_vals[k].append(get_metric(r, k.replace(" ", "_")))
    spec_avg = {k: sum(v) / len(v) for k, v in spec_vals.items()}
    return metrics, spec_avg


def save_pair(metrics, spec_avg, tag: str, out_dir: Path):
    x_labels = ["tomcat", "finagle-http", "finagle-chirper", "verilator", "SPEC average"]
    x = np.arange(len(x_labels))
    width = 0.34

    l1 = [
        metrics["tomcat"]["L1I MPKI"],
        metrics["finagle-http"]["L1I MPKI"],
        metrics["finagle-chirper"]["L1I MPKI"],
        metrics["verilator"]["L1I MPKI"],
        spec_avg["L1I MPKI"],
    ]
    l2 = [
        metrics["tomcat"]["L2 MPKI"],
        metrics["finagle-http"]["L2 MPKI"],
        metrics["finagle-chirper"]["L2 MPKI"],
        metrics["verilator"]["L2 MPKI"],
        spec_avg["L2 MPKI"],
    ]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(x - width / 2, l1, width, label="L1I MPKI")
    ax.bar(x + width / 2, l2, width, label="L2 inst. MPKI")
    ax.set_ylabel("MPKI")
    ax.set_title(f"L1I/L2 inst. MPKI ({tag})")
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.legend()
    plt.tight_layout()
    out1 = out_dir / f"frontend_l1i_l2_mpki_{tag}.png"
    plt.savefig(out1, dpi=300, bbox_inches="tight")
    plt.close()

    itlb = [
        metrics["tomcat"]["iTLB MPKI"],
        metrics["finagle-http"]["iTLB MPKI"],
        metrics["finagle-chirper"]["iTLB MPKI"],
        metrics["verilator"]["iTLB MPKI"],
        spec_avg["iTLB MPKI"],
    ]
    stlb = [
        metrics["tomcat"]["sTLB MPKI"],
        metrics["finagle-http"]["sTLB MPKI"],
        metrics["finagle-chirper"]["sTLB MPKI"],
        metrics["verilator"]["sTLB MPKI"],
        spec_avg["sTLB MPKI"],
    ]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(x - width / 2, itlb, width, label="iTLB MPKI")
    ax.bar(x + width / 2, stlb, width, label="sTLB MPKI")
    ax.set_ylabel("MPKI")
    ax.set_title(f"iTLB/sTLB MPKI ({tag})")
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.legend()
    plt.tight_layout()
    out2 = out_dir / f"frontend_itlb_stlb_mpki_{tag}.png"
    plt.savefig(out2, dpi=300, bbox_inches="tight")
    plt.close()
    return out1, out2


def main():
    ap = argparse.ArgumentParser(description="Plot frontend MPKI variants from main_frontend_all.csv")
    ap.add_argument("--input", required=True, help="main_frontend_all.csv")
    ap.add_argument("--results-dir", default=None, help="output dir (default: input parent)")
    args = ap.parse_args()

    in_csv = Path(args.input)
    out_dir = Path(args.results_dir) if args.results_dir else in_csv.parent
    apply_plot_style()
    rows = load_rows(in_csv)
    lookup = row_lookup(rows)

    m1, s1 = build_variant_metrics(lookup, "jvm1c")
    out_1 = save_pair(m1, s1, "jvm1c", out_dir)

    m86, s86 = build_variant_metrics(lookup, "jvm86c")
    out_86 = save_pair(m86, s86, "jvm86c", out_dir)

    print(f"Saved: {out_1[0]}")
    print(f"Saved: {out_1[1]}")
    print(f"Saved: {out_86[0]}")
    print(f"Saved: {out_86[1]}")


if __name__ == "__main__":
    main()
