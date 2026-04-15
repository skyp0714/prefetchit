#!/usr/bin/env bash
# Deprecated: kept for legacy data recovery only.
# Main flow now reads/writes `results/main_frontend_all.csv` and plots from it.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PERF_BIN="${PERF_BIN:-perf}"
EVENT_FILE="${EVENT_FILE:-${PROFILING_DIR}/config/perf_events_frontend_mpki_gnr.txt}"
OUT_CSV="${OUT_CSV:-${PROFILING_DIR}/results/contextswitch_core0_frontend4_jvm.csv}"
LOG_DIR="${LOG_ROOT}/ctxswitch_mpki_frontend4"
CORE_LIST="${CORE_LIST:-86}"
BENCHMARKS="${BENCHMARKS:-tomcat finagle-http finagle-chirper}"
RESUME_CSV="${RESUME_CSV:-1}"
PERF_USER_ONLY="${PERF_USER_ONLY:-1}"

TOMCAT_MAX_ITERATIONS="${TOMCAT_MAX_ITERATIONS:-10}"
TOMCAT_WATCHDOG_SECS="${TOMCAT_WATCHDOG_SECS:-3600}"
TOMCAT_DELAY_MS="${TOMCAT_DELAY_MS:-60000}"
FINAGLE_DELAY_MS="${FINAGLE_DELAY_MS:-180000}"
FINAGLE_RUN_SECONDS="${FINAGLE_RUN_SECONDS:-480}"

CPU_TOTAL="$(nproc --all)"
mkdir -p "$(dirname "${OUT_CSV}")" "${LOG_DIR}"

event0_alias="$(awk -F'|' '/^[^#].+\|/{print $1; exit}' "${EVENT_FILE}")"
event0_spec="$(awk -F'|' '/^[^#].+\|/{print $2; exit}' "${EVENT_FILE}")"
event1_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $1; exit}}' "${EVENT_FILE}")"
event1_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $2; exit}}' "${EVENT_FILE}")"
event2_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $1; exit}}' "${EVENT_FILE}")"
event2_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $2; exit}}' "${EVENT_FILE}")"
event3_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $1; exit}}' "${EVENT_FILE}")"
event3_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $2; exit}}' "${EVENT_FILE}")"

if [[ -z "${event0_alias}" || -z "${event1_alias}" || -z "${event2_alias}" || -z "${event3_alias}" ]]; then
  echo "[err] failed to parse first 4 events from ${EVENT_FILE}" >&2
  exit 1
fi

csv_header="Benchmark,CoreCount,CoreSet,DelayMS,Instructions,Event0,Event1,Event2,Event3,L1I_MPKI,L2_MPKI,iTLB_MPKI,sTLB_MPKI,ElapsedSec,ReturnCode,PerfRaw,LogFile"
if [[ "${RESUME_CSV}" != "1" || ! -s "${OUT_CSV}" ]]; then
  echo "${csv_header}" > "${OUT_CSV}"
fi

row_completed() {
  local bench="$1"
  local cores="$2"
  [[ -f "${OUT_CSV}" ]] || return 1
  awk -F, -v b="${bench}" -v c="${cores}" '
    NR > 1 && $1 == b && $2 == c && ($5 + 0) > 0 && ($15 + 0) == 0 { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "${OUT_CSV}"
}

drop_rows_for_key() {
  local bench="$1"
  local cores="$2"
  local tmp
  tmp="$(mktemp)"
  awk -F, -v b="${bench}" -v c="${cores}" '
    NR == 1 || !($1 == b && $2 == c)
  ' "${OUT_CSV}" > "${tmp}"
  mv "${tmp}" "${OUT_CSV}"
}

bench_pattern() {
  local bench="$1"
  case "${bench}" in
    tomcat)
      echo "dacapo-23\\.11-MR2-chopin\\.jar.*tomcat"
      ;;
    finagle-http)
      echo "renaissance-gpl\\.jar.*finagle-http"
      ;;
    finagle-chirper)
      echo "renaissance-gpl\\.jar.*finagle-chirper"
      ;;
    *)
      echo ""
      ;;
  esac
}

run_one() {
  local bench="$1"
  local cores="$2"
  local delay_ms="$3"
  local run_cmd="$4"
  local cset raw_file log_file start elapsed rc pattern

  if [[ "${cores}" -gt "${CPU_TOTAL}" ]]; then
    echo "[warn] skip ${bench}: cores=${cores} > cpu_total=${CPU_TOTAL}"
    return 0
  fi
  if [[ "${cores}" -eq 1 ]]; then
    cset="0"
  else
    cset="0-$((cores - 1))"
  fi

  raw_file="${PROFILING_DIR}/results/ctxswitch4_${bench}_${cores}c_core0.perfraw"
  log_file="${LOG_DIR}/${bench}_${cores}c.log"

  if [[ "${RESUME_CSV}" == "1" ]] && row_completed "${bench}" "${cores}"; then
    echo "[inf] skip ${bench}: cores=${cores} already present in ${OUT_CSV}"
    return 0
  fi

  pattern="$(bench_pattern "${bench}")"
  kill_pattern "${pattern}" "TERM"
  sleep 1
  kill_pattern "${pattern}" "KILL"

  local scope_txt="user+kernel"
  local user_only_args=()
  if [[ "${PERF_USER_ONLY}" == "1" ]]; then
    scope_txt="user-only"
    user_only_args=(--all-user)
  fi

  echo "[inf] ${bench}: cores=${cores} cset=${cset} delay=${delay_ms}ms scope=${scope_txt}"
  start="$(date +%s)"

  set +e
  "${PERF_BIN}" stat --no-big-num -x, -C 0 -o "${raw_file}" \
    "${user_only_args[@]}" \
    -e "${event0_spec},${event1_spec},${event2_spec},${event3_spec},instructions" \
    ${delay_ms:+-D "${delay_ms}"} -- \
    taskset -c "${cset}" setsid bash -lc "${run_cmd}" > "${log_file}" 2>&1
  rc=$?
  set -e

  kill_pattern "${pattern}" "TERM"
  sleep 1
  kill_pattern "${pattern}" "KILL"

  elapsed=$(( $(date +%s) - start ))
  echo "[inf] done ${bench}: cores=${cores} rc=${rc} elapsed_sec=${elapsed}"

  read -r inst_count e0_count e1_count e2_count e3_count <<<"$(
    "${PYTHON_BIN}" - "${raw_file}" "${event0_alias}" "${event1_alias}" "${event2_alias}" "${event3_alias}" <<'PY'
import sys
from pathlib import Path

raw = Path(sys.argv[1])
e0 = sys.argv[2]
e1 = sys.argv[3]
e2 = sys.argv[4]
e3 = sys.argv[5]
counts = {e0: 0.0, e1: 0.0, e2: 0.0, e3: 0.0, "instructions": 0.0}
for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
    parts = line.split(",")
    if len(parts) < 3:
        continue
    value = parts[0].strip().replace(" ", "")
    event = parts[2].strip()
    if event not in counts:
        continue
    if value.startswith("<") or value in ("notcounted", "not-counted", "not", "notsupported"):
        continue
    try:
        counts[event] = float(value)
    except ValueError:
        pass
print(f"{counts['instructions']} {counts[e0]} {counts[e1]} {counts[e2]} {counts[e3]}")
PY
  )"

  local l1_mpki l2_mpki itlb_mpki stlb_mpki
  if awk "BEGIN{exit !(${inst_count} > 0)}"; then
    l1_mpki="$(awk -v e="${e0_count}" -v i="${inst_count}" 'BEGIN{printf "%.6f", (e*1000.0)/i}')"
    l2_mpki="$(awk -v e="${e1_count}" -v i="${inst_count}" 'BEGIN{printf "%.6f", (e*1000.0)/i}')"
    itlb_mpki="$(awk -v w="${e2_count}" -v h="${e3_count}" -v i="${inst_count}" 'BEGIN{printf "%.6f", ((w+h)*1000.0)/i}')"
    stlb_mpki="$(awk -v w="${e2_count}" -v i="${inst_count}" 'BEGIN{printf "%.6f", (w*1000.0)/i}')"
  else
    l1_mpki="0"
    l2_mpki="0"
    itlb_mpki="0"
    stlb_mpki="0"
  fi

  drop_rows_for_key "${bench}" "${cores}"
  echo "${bench},${cores},${cset},${delay_ms},${inst_count},${e0_count},${e1_count},${e2_count},${e3_count},${l1_mpki},${l2_mpki},${itlb_mpki},${stlb_mpki},${elapsed},${rc},${raw_file},${log_file}" >> "${OUT_CSV}"
}

bench_enabled() {
  local target="$1"
  local b
  for b in ${BENCHMARKS}; do
    if [[ "${b}" == "${target}" ]]; then
      return 0
    fi
  done
  return 1
}

for cores in ${CORE_LIST}; do
  if bench_enabled "tomcat"; then
    run_one \
      "tomcat" \
      "${cores}" \
      "${TOMCAT_DELAY_MS}" \
      "DACAPO_CONVERGE=1 MAX_ITERATIONS=${TOMCAT_MAX_ITERATIONS} WATCHDOG_SECS=${TOMCAT_WATCHDOG_SECS} ./runscript/run_tomcat.sh"
  fi

  if bench_enabled "finagle-http"; then
    run_one \
      "finagle-http" \
      "${cores}" \
      "${FINAGLE_DELAY_MS}" \
      "ACTIVE_CPUS=${cores} RUN_SECONDS=${FINAGLE_RUN_SECONDS} FINAGLE_PRINT_COMPILATION=1 ./runscript/run_finagle_http.sh"
  fi

  if bench_enabled "finagle-chirper"; then
    run_one \
      "finagle-chirper" \
      "${cores}" \
      "${FINAGLE_DELAY_MS}" \
      "ACTIVE_CPUS=${cores} RUN_SECONDS=${FINAGLE_RUN_SECONDS} FINAGLE_PRINT_COMPILATION=1 ./runscript/run_finagle_chirper.sh"
  fi
done

echo "[ok] saved ${OUT_CSV}"
