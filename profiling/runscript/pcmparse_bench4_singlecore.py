import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

profiling_dir = Path(__file__).resolve().parent.parent
results_dir = profiling_dir / "results"

profile_core = int(os.environ.get("PROFILE_CORE", "1"))
warmup_samples = int(os.environ.get("MPKI_WARMUP_SAMPLES", "0"))

bench_files = {
    "tomcat": results_dir / "tomcat_core.csv",
    "finagle-http": results_dir / "finagle_http_core.csv",
    "finagle-chirper": results_dir / "finagle_chirper_core.csv",
    "verilator-qsort": results_dir / "verilator_qsort_core.csv",
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
    selected = snapshots[warmup_samples:] if len(snapshots) > warmup_samples else snapshots

    inst = 0.0
    ev0 = 0.0
    ev1 = 0.0
    ev2 = 0.0
    ev3 = 0.0
    for row in selected:
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


stats = {}
for name, file_path in bench_files.items():
    if not file_path.exists():
        raise FileNotFoundError(f"Missing input CSV: {file_path}")
    stats[name] = aggregate_metric_row(file_path)

benchmarks = list(stats.keys())
metrics = ["L1I MPKI (all code rd)", "L2I Miss MPKI", "iTLB Walk MPKI", "iTLB Retired MPKI"]
x = np.arange(len(benchmarks))
width = 0.18

fig, ax = plt.subplots(figsize=(12, 6))
for i, metric in enumerate(metrics):
    vals = [stats[b][metric] for b in benchmarks]
    ax.bar(x + (i - 1.5) * width, vals, width, label=metric)

ax.set_ylabel("MPKI")
ax.set_title(
    f"Single-Core Front-End MPKI Across 4 Benchmarks (core {profile_core}, warmup_drop={warmup_samples})"
)
ax.set_xticks(x)
ax.set_xticklabels(benchmarks, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend()
plt.tight_layout()
out = results_dir / "bench4_singlecore_frontend_mpki.png"
plt.savefig(out, dpi=300, bbox_inches="tight")
plt.close()

print(f"Saved: {out}")
