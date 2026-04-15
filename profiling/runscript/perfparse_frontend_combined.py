import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

FONT_SCALE = 2.0

profiling_dir = Path(__file__).resolve().parent.parent
results_dir = profiling_dir / "results"

bench_files = {
    "tomcat": results_dir / "tomcat_core.csv",
    "finagle-http": results_dir / "finagle_http_core.csv",
    "finagle-chirper": results_dir / "finagle_chirper_core.csv",
    "verilator-qsort": results_dir / "verilator_qsort_core.csv",
}
spec_files = {
    "602.gcc_s": results_dir / "spec602_core.csv",
    "605.mcf_s": results_dir / "spec605_core.csv",
    "641.leela_s": results_dir / "spec641_core.csv",
}


def load_row(path: Path):
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"No rows in {path}")
    row = rows[0]
    for k in ("Instructions", "Event0", "Event1", "Event2", "Event3"):
        row[k] = float(row[k])
    return row


def to_metrics(row):
    inst_k = row["Instructions"] / 1000.0
    if inst_k <= 0:
        raise RuntimeError("instructions counter is zero")
    itlb_walk = row["Event2"]  # iTLB miss that missed in sTLB (page walk)
    itlb_stlb_hit = row["Event3"]  # iTLB miss that hit in sTLB
    return {
        "L1I MPKI": row["Event0"] / inst_k,
        "L2 MPKI": row["Event1"] / inst_k,
        "iTLB MPKI": (itlb_walk + itlb_stlb_hit) / inst_k,
        "sTLB MPKI": itlb_walk / inst_k,
    }


bench_metrics = {}
for name, f in bench_files.items():
    if not f.exists():
        raise FileNotFoundError(f"Missing benchmark file: {f}")
    bench_metrics[name] = to_metrics(load_row(f))

spec_metrics = {}
for name, f in spec_files.items():
    if not f.exists():
        raise FileNotFoundError(f"Missing SPEC file: {f}")
    spec_metrics[name] = to_metrics(load_row(f))

spec_avg = {}
for metric in ("L1I MPKI", "L2 MPKI", "iTLB MPKI", "sTLB MPKI"):
    spec_avg[metric] = sum(spec_metrics[s][metric] for s in spec_metrics) / len(spec_metrics)

x_labels = ["tomcat", "finagle-http", "finagle-chirper", "verilator", "SPEC average"]
x = np.arange(len(x_labels))

# Plot 1: L1i + L2
width = 0.34
l1_vals = [bench_metrics["tomcat"]["L1I MPKI"], bench_metrics["finagle-http"]["L1I MPKI"], bench_metrics["finagle-chirper"]["L1I MPKI"], bench_metrics["verilator-qsort"]["L1I MPKI"], spec_avg["L1I MPKI"]]
l2_vals = [bench_metrics["tomcat"]["L2 MPKI"], bench_metrics["finagle-http"]["L2 MPKI"], bench_metrics["finagle-chirper"]["L2 MPKI"], bench_metrics["verilator-qsort"]["L2 MPKI"], spec_avg["L2 MPKI"]]

fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(x - width / 2, l1_vals, width, label="L1I MPKI")
ax.bar(x + width / 2, l2_vals, width, label="L2 inst. MPKI")
ax.set_ylabel("MPKI")
ax.set_title("L1I/L2 inst. MPKI (4 Benchmarks + SPEC average)")
ax.set_xticks(x)
ax.set_xticklabels(x_labels, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend()
plt.tight_layout()
plot1 = results_dir / "frontend_l1i_l2_mpki.png"
plt.savefig(plot1, dpi=300, bbox_inches="tight")
plt.close()

# Plot 2: iTLB + sTLB
itlb_vals = [bench_metrics["tomcat"]["iTLB MPKI"], bench_metrics["finagle-http"]["iTLB MPKI"], bench_metrics["finagle-chirper"]["iTLB MPKI"], bench_metrics["verilator-qsort"]["iTLB MPKI"], spec_avg["iTLB MPKI"]]
stlb_vals = [bench_metrics["tomcat"]["sTLB MPKI"], bench_metrics["finagle-http"]["sTLB MPKI"], bench_metrics["finagle-chirper"]["sTLB MPKI"], bench_metrics["verilator-qsort"]["sTLB MPKI"], spec_avg["sTLB MPKI"]]

fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(x - width / 2, itlb_vals, width, label="iTLB MPKI")
ax.bar(x + width / 2, stlb_vals, width, label="sTLB MPKI")
ax.set_ylabel("MPKI")
ax.set_title("iTLB/sTLB MPKI (4 Benchmarks + SPEC average)")
ax.set_xticks(x)
ax.set_xticklabels(x_labels, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend()
plt.tight_layout()
plot2 = results_dir / "frontend_itlb_stlb_mpki.png"
plt.savefig(plot2, dpi=300, bbox_inches="tight")
plt.close()

print("SPEC average MPKI:")
for m in ("L1I MPKI", "L2 MPKI", "iTLB MPKI", "sTLB MPKI"):
    print(f"{m}: {spec_avg[m]:.4f}")
print(f"Saved: {plot1}")
print(f"Saved: {plot2}")
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


apply_plot_style()
