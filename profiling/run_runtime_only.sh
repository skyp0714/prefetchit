#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/runscript/bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"

WORKLOAD="${WORKLOAD:-verilator-qsort}"
WORKLOAD_BIN="${WORKLOAD_BIN:-}"
WORKLOAD_NAME="${WORKLOAD_NAME:-}"
CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-DualMegaBoomAndSingleRocketConfig}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
SIM_BINARY="${SIM_BINARY:-}"
MAX_CYCLES="${MAX_CYCLES:-80000}"
PROFILE_CORE="${PROFILE_CORE:-0}"
ITERATIONS="${ITERATIONS:-5}"
RESULTS_BASE="${RESULTS_BASE:-${PROFILING_DIR}/results/runtime_only}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"
MBIN="${MBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/mm.riscv}"

usage() {
  cat <<'EOF'
Usage: ./run_runtime_only.sh [options]

Options:
  --workload <name>              Workload: verilator-qsort | verilator-mm | verilator-custom
  --workload-bin <path>          Custom workload binary path (for verilator-custom)
  --workload-name <name>         Output folder name override
  --chipyard-config <Config>     Config class name (for auto simulator resolve)
  --chipyard-config-package <P>  Config package (default: chipyard)
  --sim-binary <path>            Simulator binary override
  --max-cycles <N>               +max-cycles (default: 80000)
  --profile-core <N>             taskset core (default: 0)
  --iterations <N>               Runtime repetitions (default: 5)
  --results-base <path>          Output base dir
  --qbin <path>                  qsort binary path
  --mbin <path>                  mm binary path
  -h, --help                     Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workload)
      WORKLOAD="${2:-}"
      shift 2
      ;;
    --workload-bin)
      WORKLOAD_BIN="${2:-}"
      shift 2
      ;;
    --workload-name)
      WORKLOAD_NAME="${2:-}"
      shift 2
      ;;
    --chipyard-config)
      CHIPYARD_CONFIG="${2:-}"
      shift 2
      ;;
    --chipyard-config-package)
      CHIPYARD_CONFIG_PACKAGE="${2:-}"
      shift 2
      ;;
    --sim-binary)
      SIM_BINARY="${2:-}"
      shift 2
      ;;
    --max-cycles)
      MAX_CYCLES="${2:-}"
      shift 2
      ;;
    --profile-core)
      PROFILE_CORE="${2:-}"
      shift 2
      ;;
    --iterations)
      ITERATIONS="${2:-}"
      shift 2
      ;;
    --results-base)
      RESULTS_BASE="${2:-}"
      shift 2
      ;;
    --qbin)
      QBIN="${2:-}"
      shift 2
      ;;
    --mbin)
      MBIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[err] unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "${MAX_CYCLES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --max-cycles must be positive integer" >&2
  exit 1
fi
if ! [[ "${PROFILE_CORE}" =~ ^[0-9]+$ ]]; then
  echo "[err] --profile-core must be non-negative integer" >&2
  exit 1
fi
if ! [[ "${ITERATIONS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --iterations must be positive integer" >&2
  exit 1
fi

setup_verilator_env
require_chipyard_tree

case "${WORKLOAD}" in
  verilator-qsort)
    WORKLOAD_BIN="${QBIN}"
    require_file "${WORKLOAD_BIN}"
    ;;
  verilator-mm)
    WORKLOAD_BIN="${MBIN}"
    require_file "${WORKLOAD_BIN}"
    ;;
  verilator-custom)
    if [[ -z "${WORKLOAD_BIN}" ]]; then
      echo "[err] --workload-bin is required for verilator-custom" >&2
      exit 1
    fi
    require_file "${WORKLOAD_BIN}"
    ;;
  *)
    echo "[err] unsupported workload: ${WORKLOAD}" >&2
    exit 1
    ;;
esac

if [[ -n "${SIM_BINARY}" ]]; then
  EMU="${SIM_BINARY}"
else
  EMU="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
  if [[ -z "${EMU}" ]]; then
    echo "[err] simulator binary not found for config=${CHIPYARD_CONFIG}" >&2
    exit 1
  fi
fi
require_file "${EMU}"

if [[ -z "${WORKLOAD_NAME}" ]]; then
  if [[ "${WORKLOAD}" == "verilator-custom" ]]; then
    base="$(basename "${WORKLOAD_BIN}")"
    WORKLOAD_NAME="verilator-${base%.riscv}"
  else
    WORKLOAD_NAME="${WORKLOAD}"
  fi
fi

sim_base="$(basename "${EMU}")"
OUT_DIR="${RESULTS_BASE}/${WORKLOAD_NAME}/${sim_base}"
mkdir -p "${OUT_DIR}"

CSV="${OUT_DIR}/runtime_iterations.csv"
SUMMARY="${OUT_DIR}/runtime_summary.csv"

echo "iteration,elapsed_sec,return_code,status,log" > "${CSV}"

echo "[inf] simulator=${EMU}"
echo "[inf] workload=${WORKLOAD_BIN}"
echo "[inf] iterations=${ITERATIONS}"
echo "[inf] out_dir=${OUT_DIR}"

for iter in $(seq 1 "${ITERATIONS}"); do
  log="${OUT_DIR}/iter$(printf '%03d' "${iter}").log"
  cmd="$(printf '%q %q +max-cycles=%q' "${EMU}" "${WORKLOAD_BIN}" "${MAX_CYCLES}")"
  start_ns="$(date +%s%N)"
  set +e
  taskset -c "${PROFILE_CORE}" bash -lc "${cmd}" > "${log}" 2>&1
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  elapsed="$(awk "BEGIN { printf \"%.6f\", (${end_ns}-${start_ns})/1000000000 }")"
  status="finished"
  if [[ "${rc}" -ne 0 ]]; then
    if grep -q "*** FAILED ***" "${log}" && grep -q "(timeout)" "${log}"; then
      status="max_cycles"
    else
      status="failed"
    fi
  fi
  printf '%s,%s,%s,%s,"%s"\n' "${iter}" "${elapsed}" "${rc}" "${status}" "${log}" >> "${CSV}"
done

python3 - <<'PY' "${CSV}" "${SUMMARY}"
import csv, statistics, sys
in_csv, out_csv = sys.argv[1], sys.argv[2]
vals = []
statuses = {}
with open(in_csv, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        try:
            vals.append(float(row["elapsed_sec"]))
        except Exception:
            pass
        st = row.get("status", "")
        statuses[st] = statuses.get(st, 0) + 1
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["count", "mean_sec", "median_sec", "min_sec", "max_sec", "stdev_sec", "status_counts"])
    if vals:
        w.writerow([
            len(vals),
            f"{statistics.mean(vals):.6f}",
            f"{statistics.median(vals):.6f}",
            f"{min(vals):.6f}",
            f"{max(vals):.6f}",
            f"{statistics.pstdev(vals):.6f}",
            " | ".join(f"{k}:{v}" for k, v in sorted(statuses.items())),
        ])
PY

echo "[ok] saved ${CSV}"
echo "[ok] saved ${SUMMARY}"
