#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${RUN_ID:-tailbench_manual_highmpki_eval_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/llvm_prefetchit/results/${RUN_ID}}"
WORK_ROOT="${WORK_ROOT:-${ROOT_DIR}/llvm_prefetchit/work/tailbench_cf_manual_o0_o064_buildcheck_20260710_111413}"
TAILBENCH_HOME="${TAILBENCH_HOME:-${ROOT_DIR}/benchmarks/tailbench}"
REPS="${REPS:-1}"
LABELS="${LABELS:-clangbase cf4_o0 cf4_o064 cf8_o0 cf8_o064}"
BENCHMARKS="${BENCHMARKS:-xapian moses}"
CORE="${CORE:-0-5}"

mkdir -p "${OUT_DIR}"

run_one() {
  local bench="$1"
  local label="$2"
  local rep="$3"
  local workdir="${WORK_ROOT}/${bench}_${label}/tailbench/${bench}"
  local name="${bench}_highmpki_${label}_rep${rep}"
  local measured_reqs config_qps cmd

  case "${bench}" in
    xapian)
      measured_reqs="${XAPIAN_REQUESTS:-24000}"
      config_qps="${XAPIAN_QPS:-200}"
      cmd="LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NSERVERS=${XAPIAN_NSERVERS:-4} QPS=${config_qps} WARMUPREQS=${XAPIAN_WARMUPREQS:-400} REQUESTS=${measured_reqs} bash ./run.sh"
      ;;
    moses)
      measured_reqs="${MOSES_REQUESTS:-48000}"
      config_qps="${MOSES_QPS:-400}"
      cmd="LD_LIBRARY_PATH=./bin:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=${MOSES_THREADS:-4} QPS=${config_qps} WARMUPREQS=${MOSES_WARMUPREQS:-400} MAXREQS=${measured_reqs} bash ./run.sh"
      ;;
    *)
      echo "unknown benchmark: ${bench}" >&2
      return 2
      ;;
  esac

  if [[ ! -d "${workdir}" ]]; then
    echo "missing workdir: ${workdir}" >&2
    return 1
  fi

  OUT_DIR="${OUT_DIR}/eval_runs" APPEND=1 BENCHMARKS=custom CUSTOM_NAME="${name}" \
    CUSTOM_WORKDIR="${workdir}" CUSTOM_CMD="${cmd}" RUN_TO_COMPLETION=1 \
    MEASURED_REQS="${measured_reqs}" CONFIG_QPS="${config_qps}" CORE="${CORE}" \
    PIN_THREADS=1 bash "${ROOT_DIR}/llvm_prefetchit/scripts/run_workload_l2_screen.sh"
}

summarize() {
  python3 - "${OUT_DIR}" "${LABELS}" <<'PY'
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

out = Path(sys.argv[1])
labels = sys.argv[2].split()
runs = out / "eval_runs" / "runs.csv"
summary_csv = out / "manual_highmpki_summary.csv"
summary_md = out / "manual_highmpki_summary.md"

def fnum(row, key):
    try:
        return float(row.get(key, ""))
    except Exception:
        return float("nan")

def median(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return statistics.median(vals) if vals else float("nan")

def mean(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return statistics.mean(vals) if vals else float("nan")

def stdev(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return statistics.stdev(vals) if len(vals) >= 2 else 0.0

rows = []
if runs.exists():
    with runs.open(newline="") as f:
        rows = list(csv.DictReader(f))

groups = defaultdict(list)
for row in rows:
    name = row.get("benchmark", "")
    for bench in ("xapian", "moses"):
        prefix = bench + "_highmpki_"
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        for label in labels:
            suffix = "_rep"
            if rest.startswith(label + suffix):
                groups[(bench, label)].append(row)
                break

csv_rows = []
lines = [
    "# TailBench Manual High-MPKI Evaluation",
    "",
    f"- Result dir: `{out}`",
    "- Config: xapian `NSERVERS=4 QPS=200`, moses `THREADS=4 QPS=400`; fixed request run-to-completion.",
    "",
    "| benchmark | label | reps | median runtime s | speedup | runtime stdev s | median qps | qps speedup | median L2I MPKI | L2I reduction | median migrations | observed CPUs |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
]
for bench in ("xapian", "moses"):
    base = groups.get((bench, "clangbase"), [])
    base_runtime = median([fnum(r, "elapsed_s") for r in base])
    base_qps = median([fnum(r, "derived_qps") for r in base])
    base_mpki = median([fnum(r, "l2i_mpki") for r in base])
    for label in labels:
        rs = groups.get((bench, label), [])
        if not rs:
            continue
        runtimes = [fnum(r, "elapsed_s") for r in rs]
        qps_vals = [fnum(r, "derived_qps") for r in rs]
        mpki_vals = [fnum(r, "l2i_mpki") for r in rs]
        migrations = [fnum(r, "cpu_migrations") for r in rs]
        runtime = median(runtimes)
        qps = median(qps_vals)
        mpki = median(mpki_vals)
        speedup = base_runtime / runtime if base_runtime > 0 and runtime > 0 else float("nan")
        qps_speedup = qps / base_qps if base_qps > 0 and qps > 0 else float("nan")
        l2_reduction = (base_mpki - mpki) / base_mpki if base_mpki > 0 and mpki >= 0 else float("nan")
        cpus = ";".join(sorted({r.get("observed_unique_psrs", "") for r in rs if r.get("observed_unique_psrs", "")}))
        out_row = {
            "benchmark": bench,
            "label": label,
            "reps": len(rs),
            "median_runtime_s": f"{runtime:.6f}" if not math.isnan(runtime) else "",
            "speedup": f"{speedup:.9f}" if not math.isnan(speedup) else "",
            "runtime_stdev_s": f"{stdev(runtimes):.6f}",
            "median_qps": f"{qps:.6f}" if not math.isnan(qps) else "",
            "qps_speedup": f"{qps_speedup:.9f}" if not math.isnan(qps_speedup) else "",
            "median_l2i_mpki": f"{mpki:.9f}" if not math.isnan(mpki) else "",
            "l2i_reduction": f"{l2_reduction:.9f}" if not math.isnan(l2_reduction) else "",
            "median_cpu_migrations": f"{median(migrations):.0f}" if not math.isnan(median(migrations)) else "",
            "observed_cpus": cpus,
        }
        csv_rows.append(out_row)
        lines.append("| {benchmark} | {label} | {reps} | {median_runtime_s} | {speedup} | {runtime_stdev_s} | {median_qps} | {qps_speedup} | {median_l2i_mpki} | {l2i_reduction} | {median_cpu_migrations} | {observed_cpus} |".format(**out_row))

with summary_csv.open("w", newline="") as f:
    fields = [
        "benchmark", "label", "reps", "median_runtime_s", "speedup", "runtime_stdev_s",
        "median_qps", "qps_speedup", "median_l2i_mpki", "l2i_reduction",
        "median_cpu_migrations", "observed_cpus",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(csv_rows)
summary_md.write_text("\n".join(lines) + "\n")
PY
}

for rep in $(seq 1 "${REPS}"); do
  for bench in ${BENCHMARKS}; do
    for label in ${LABELS}; do
      run_one "${bench}" "${label}" "${rep}"
      summarize
    done
  done
done

summarize
echo "summary: ${OUT_DIR}/manual_highmpki_summary.md"
