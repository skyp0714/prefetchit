#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BENCH_ROOT="${REPO_ROOT}/benchmarks"
PROFILING_ROOT="${REPO_ROOT}/profiling"
TOOLS_ROOT="${BENCH_ROOT}/tools"
CHIPYARD_ROOT="${BENCH_ROOT}/chipyard"
CHIPYARD_SIM_DIR="${CHIPYARD_ROOT}/sims/verilator"
LOG_ROOT="${PROFILING_ROOT}/results/logs"
TMP_ROOT="${PROFILING_ROOT}/results/logs/tmp"
RESULTS_ROOT="${PROFILING_ROOT}/results/logs/results"

mkdir -p "${LOG_ROOT}" "${TMP_ROOT}" "${RESULTS_ROOT}"

JAVA_BIN="${TOOLS_ROOT}/jdk17/bin/java"
GRAAL_JAVA_DEFAULT="${TOOLS_ROOT}/graalvm-ce-java17/bin/java"
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

resolve_graal_java_bin() {
  local cand
  if [[ -n "${FINAGLE_JAVA_BIN:-}" ]]; then
    cand="${FINAGLE_JAVA_BIN}"
    require_file "${cand}"
    echo "${cand}"
    return 0
  fi
  if [[ -n "${GRAAL_JAVA_BIN:-}" ]]; then
    cand="${GRAAL_JAVA_BIN}"
    require_file "${cand}"
    echo "${cand}"
    return 0
  fi

  for cand in \
    "${GRAAL_JAVA_DEFAULT}" \
    "${TOOLS_ROOT}/graalvm-jdk-17/bin/java" \
    "${TOOLS_ROOT}/graalvm-ce-17/bin/java"; do
    if [[ -x "${cand}" ]]; then
      echo "${cand}"
      return 0
    fi
  done

  if [[ "${ALLOW_NON_GRAAL_FINAGLE:-0}" == "1" ]]; then
    echo "${JAVA_BIN}"
    return 0
  fi

  echo "[err] GraalVM CE 17 java binary not found for finagle runs." >&2
  echo "[err] Expected one of:" >&2
  echo "[err]   ${GRAAL_JAVA_DEFAULT}" >&2
  echo "[err]   ${TOOLS_ROOT}/graalvm-jdk-17/bin/java" >&2
  echo "[err]   ${TOOLS_ROOT}/graalvm-ce-17/bin/java" >&2
  echo "[err] Or set FINAGLE_JAVA_BIN=/abs/path/to/graalvm-java" >&2
  echo "[err] (temporary bypass: ALLOW_NON_GRAAL_FINAGLE=1)" >&2
  return 1
}

setup_verilator_env() {
  local verilator_bin_dir=""
  local verilator_root=""

  if [[ -x "${TOOLS_ROOT}/verilator-5.046-install/bin/verilator" ]]; then
    verilator_bin_dir="${TOOLS_ROOT}/verilator-5.046-install/bin"
    verilator_root="${TOOLS_ROOT}/verilator-5.046-install/share/verilator"
  elif [[ -x "${TOOLS_ROOT}/verilator/usr/bin/verilator" ]]; then
    verilator_bin_dir="${TOOLS_ROOT}/verilator/usr/bin"
    verilator_root="${TOOLS_ROOT}/verilator/usr/share/verilator"
  fi

  if [[ -z "${verilator_bin_dir}" || -z "${verilator_root}" ]]; then
    echo "[err] Verilator not found under ${TOOLS_ROOT}." >&2
    echo "[err] Expected one of:" >&2
    echo "[err]   ${TOOLS_ROOT}/verilator-5.046-install/bin/verilator" >&2
    echo "[err]   ${TOOLS_ROOT}/verilator/usr/bin/verilator" >&2
    return 1
  fi

  export RISCV="${RISCV_ROOT}"
  export PATH="${TOOLS_ROOT}/bin:${TOOLS_ROOT}/jdk17/bin:${verilator_bin_dir}:${TOOLS_ROOT}/dtc/usr/bin:${RISCV_ROOT}/bin:${PATH}"
  export LD_LIBRARY_PATH="${TOOLS_ROOT}/dtc/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
  export VERILATOR_ROOT="${verilator_root}"
}

require_chipyard_tree() {
  require_file "${CHIPYARD_ROOT}/build.sbt"
  require_file "${CHIPYARD_SIM_DIR}/Makefile"
}

validate_boom_multicore_config() {
  local cfg="$1"
  local match file lineno context
  local have_large_or_mega=0
  local have_multicore=0

  if command -v rg >/dev/null 2>&1; then
    match="$(rg -n "class[[:space:]]+${cfg}\\b" "${CHIPYARD_ROOT}/generators" -g '*.scala' -S | head -n1 || true)"
  else
    match="$(grep -RnsE "class[[:space:]]+${cfg}\\b" "${CHIPYARD_ROOT}/generators" --include='*.scala' | head -n1 || true)"
  fi
  if [[ -z "${match}" ]]; then
    echo "[err] Could not locate class ${cfg} under ${CHIPYARD_ROOT}/generators" >&2
    echo "[err] Set CHIPYARD_CONFIG to a valid Chipyard BOOM config class name." >&2
    return 1
  fi

  file="${match%%:*}"
  lineno="${match#*:}"
  lineno="${lineno%%:*}"
  context="$(sed -n "${lineno},$((lineno + 220))p" "${file}")"

  if echo "${context}" | grep -Eq 'WithLargeBooms|WithNLargeBooms|LargeBoom|WithMegaBooms|WithNMegaBooms|MegaBoom'; then
    have_large_or_mega=1
  fi

  if echo "${context}" | grep -Eq 'WithNBoomCores\([^)]*([2-9][0-9]*)'; then
    have_multicore=1
  fi
  if echo "${context}" | grep -Eq 'WithNBoomCores\([^)]*n[[:space:]]*=[[:space:]]*([2-9][0-9]*)'; then
    have_multicore=1
  fi
  if echo "${context}" | grep -Eq 'WithNLargeBooms\([^)]*([2-9][0-9]*)'; then
    have_multicore=1
  fi
  if echo "${context}" | grep -Eq 'WithNLargeBooms\([^)]*n[[:space:]]*=[[:space:]]*([2-9][0-9]*)'; then
    have_multicore=1
  fi
  if echo "${context}" | grep -Eq 'WithNMegaBooms\([^)]*([2-9][0-9]*)'; then
    have_multicore=1
  fi
  if echo "${context}" | grep -Eq 'WithNMegaBooms\([^)]*n[[:space:]]*=[[:space:]]*([2-9][0-9]*)'; then
    have_multicore=1
  fi

  if [[ "${have_large_or_mega}" -ne 1 || "${have_multicore}" -ne 1 ]]; then
    echo "[err] ${cfg} does not look like a large/mega multi-core BOOM config." >&2
    echo "[err] Need both: large/mega BOOM flavor and >=2 BOOM cores." >&2
    echo "[err] If your config is composed indirectly, set SKIP_BOOM_CONFIG_CHECK=1 to bypass." >&2
    return 1
  fi

  echo "[ok] BOOM config check passed: ${cfg} (${file}:${lineno})"
}

resolve_chipyard_simulator() {
  local cfg="$1"
  local pkg="${2:-chipyard}"
  local candidate found

  for candidate in \
    "${CHIPYARD_SIM_DIR}/simulator-${pkg}-${cfg}" \
    "${CHIPYARD_SIM_DIR}/simulator-chipyard-${cfg}"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done

  found="$(find "${CHIPYARD_SIM_DIR}" -maxdepth 1 -type f -name "simulator-*-${cfg}" | head -n1 || true)"
  if [[ -n "${found}" ]]; then
    echo "${found}"
    return 0
  fi
  return 1
}

kill_pid_and_group() {
  local pid="$1"
  local sig="${2:-TERM}"
  local pgid=""

  if [[ -z "${pid}" ]]; then
    return 0
  fi
  if ! kill -0 "${pid}" 2>/dev/null; then
    return 0
  fi

  pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  kill -"${sig}" "${pid}" 2>/dev/null || true
  if [[ -n "${pgid}" && "${pgid}" =~ ^[0-9]+$ && "${pgid}" -gt 1 ]]; then
    kill -"${sig}" -- "-${pgid}" 2>/dev/null || true
  fi
}

kill_pattern() {
  local pattern="$1"
  local sig="${2:-TERM}"
  if [[ -z "${pattern}" ]]; then
    return 0
  fi
  pkill -"${sig}" -f "${pattern}" 2>/dev/null || true
}

benchmark_orphan_patterns() {
  cat <<'EOF'
dacapo-23\.11-MR2-chopin\.jar.*tomcat
renaissance-gpl\.jar.*finagle-http
renaissance-gpl\.jar.*finagle-chirper
simulator-.*qsort\.riscv
EOF
}

cleanup_known_benchmark_orphans() {
  local term_sleep="${1:-2}"
  local pattern

  while IFS= read -r pattern; do
    kill_pattern "${pattern}" "TERM"
  done < <(benchmark_orphan_patterns)
  sleep "${term_sleep}"
  while IFS= read -r pattern; do
    kill_pattern "${pattern}" "KILL"
  done < <(benchmark_orphan_patterns)
}
