import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

profiling_dir = Path(__file__).resolve().parent.parent
results_dir = profiling_dir / "results"

profile_core = int(os.environ.get("PROFILE_CORE", "1"))

spec_files = {
    "602.gcc_s": results_dir / "spec602_core.csv",
    "605.mcf_s": results_dir / "spec605_core.csv",
    "641.leela_s": results_dir / "spec641_core.csv",
}


def parse_core_snapshots(path: Path, core_id: int):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    snapshots = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("Core,IPC,Instructions"):
            i += 1
            continue

        header = [x.strip() for x in lines[i].split(",") if x.strip()]
        i += 1
        core_row = None

        while i < len(lines):
            row_line = lines[i].strip()
            if not row_line:
                break
            if row_line.startswith("Core,IPC,Instructions"):
                i -= 1
                break

            parts = [x.strip() for x in lines[i].split(",")]
            if len(parts) >= len(header):
                rec = {header[j]: parts[j] for j in range(len(header))}
                if rec.get("Core") == str(core_id):
                    core_row = rec
            i += 1

        if core_row is not None:
            snapshots.append(core_row)
        i += 1

    if not snapshots:
        raise RuntimeError(f"No samples found for core {core_id} in {path}")
    return snapshots


def aggregate_metric_row(path: Path):
    snapshots = parse_core_snapshots(path, profile_core)
    inst = 0.0
    ev0 = 0.0
    ev1 = 0.0
    ev2 = 0.0
    ev3 = 0.0
    for row in snapshots:
        inst += float(row["Instructions"])
        ev0 += float(row["Event0"])
        ev1 += float(row["Event1"])
        ev2 += float(row["Event2"])
        ev3 += float(row["Event3"])

    inst_k = inst / 1000.0
    if inst_k <= 0:
        raise RuntimeError(f"Invalid instructions count in {path}")

    return {
        "L1I MPKI (all code rd)": ev0 / inst_k,
        "L2I Miss MPKI": ev1 / inst_k,
        "iTLB Walk MPKI": ev2 / inst_k,
        "iTLB Retired MPKI": ev3 / inst_k,
    }


spec_metrics = {}
for name, file_path in spec_files.items():
    if not file_path.exists():
        raise FileNotFoundError(f"Missing input CSV: {file_path}")
    spec_metrics[name] = aggregate_metric_row(file_path)

avg = {}
for metric in ["L1I MPKI (all code rd)", "L2I Miss MPKI", "iTLB Walk MPKI", "iTLB Retired MPKI"]:
    avg[metric] = sum(spec_metrics[b][metric] for b in spec_metrics) / len(spec_metrics)

# Plot 1: Per-benchmark SPEC values
bench_names = list(spec_metrics.keys())
metric_names = list(avg.keys())
x = np.arange(len(bench_names))
width = 0.18

fig, ax = plt.subplots(figsize=(12, 6))
for i, metric in enumerate(metric_names):
    vals = [spec_metrics[b][metric] for b in bench_names]
    ax.bar(x + (i - 1.5) * width, vals, width, label=metric)

ax.set_ylabel("MPKI")
ax.set_title(f"SPEC Single-Core Front-End MPKI (core {profile_core})")
ax.set_xticks(x)
ax.set_xticklabels(bench_names)
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend()
plt.tight_layout()
plot1 = results_dir / "spec_frontend_mpki_per_bench.png"
plt.savefig(plot1, dpi=300, bbox_inches="tight")
plt.close()

# Plot 2: x-axis is SPEC average (single category), bars are the metrics
fig, ax = plt.subplots(figsize=(8, 6))
x = np.array([0.0])
width = 0.18
for i, metric in enumerate(metric_names):
    ax.bar(x + (i - 1.5) * width, [avg[metric]], width, label=metric)
ax.set_ylabel("MPKI")
ax.set_title(f"SPEC Average Front-End MPKI (Single Core {profile_core})")
ax.set_xticks([0.0])
ax.set_xticklabels(["SPEC average"])
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend()
plt.tight_layout()
plot2 = results_dir / "spec_frontend_mpki_avg.png"
plt.savefig(plot2, dpi=300, bbox_inches="tight")
plt.close()

print("SPEC MPKI summary:")
for m in metric_names:
    print(f"{m}: {avg[m]:.4f}")
print(f"Saved: {plot1}")
print(f"Saved: {plot2}")
