#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BENCH_ROOT="${REPO_ROOT}/benchmarks"
PROFILING_ROOT="${REPO_ROOT}/profiling"
TOOLS_ROOT="${BENCH_ROOT}/tools"
LOG_ROOT="${PROFILING_ROOT}/results/benchmark_runs/logs"
TMP_ROOT="${PROFILING_ROOT}/results/benchmark_runs/tmp"
RESULTS_ROOT="${PROFILING_ROOT}/results/benchmark_runs/results"

mkdir -p "${LOG_ROOT}" "${TMP_ROOT}" "${RESULTS_ROOT}"

JAVA_BIN="${TOOLS_ROOT}/jdk17/bin/java"
RENAISSANCE_JAR="${TOOLS_ROOT}/renaissance/renaissance-gpl.jar"
DACAPO_JAR="${TOOLS_ROOT}/dacapo/dacapo-23.11-MR2-chopin.jar"
RISCV_ROOT="${TOOLS_ROOT}/rocket-tools/riscv"

require_file() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "[err] missing required file: $path" >&2
    exit 1
  fi
}

setup_verilator_env() {
  export RISCV="${RISCV_ROOT}"
  export PATH="${TOOLS_ROOT}/bin:${TOOLS_ROOT}/jdk17/bin:${TOOLS_ROOT}/verilator/usr/bin:${TOOLS_ROOT}/dtc/usr/bin:${RISCV_ROOT}/bin:${PATH}"
  export LD_LIBRARY_PATH="${TOOLS_ROOT}/dtc/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
  export VERILATOR_ROOT="${TOOLS_ROOT}/verilator/usr/share/verilator"
}
