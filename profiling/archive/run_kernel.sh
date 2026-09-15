#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/runscript/bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PERF_BIN="${PERF_BIN:-perf}"
EVENT_FILE="${EVENT_FILE:-${PROFILING_DIR}/config/gnr_frontend_perf_events.txt}"
CORES="${CORES:-0-85}"
TOMCAT_CORES="${TOMCAT_CORES:-86}"
IDLE_SECS="${IDLE_SECS:-120}"
BUSY_WARMUP_SECS="${BUSY_WARMUP_SECS:-60}"
BUSY_SECS="${BUSY_SECS:-120}"
KEEP_PERFRAW="${KEEP_PERFRAW:-0}"

TOMCAT_SIZE="${TOMCAT_SIZE:-large}"
TOMCAT_ITERATIONS="${TOMCAT_ITERATIONS:-100000}"
TOMCAT_WATCHDOG_SECS="${TOMCAT_WATCHDOG_SECS:-3600}"

OUT_CSV="${OUT_CSV:-${PROFILING_DIR}/results/kernel/csv/kernel_idle_busy.csv}"
OUT_MD="${OUT_MD:-${PROFILING_DIR}/results/kernel/csv/kernel_idle_busy.md}"
OUT_PERCORE_CSV="${OUT_PERCORE_CSV:-${PROFILING_DIR}/results/kernel/csv/kernel_idle_busy_percore.csv}"
OUT_L1I_PNG="${OUT_L1I_PNG:-${PROFILING_DIR}/results/kernel/png/kernel_idle_busy_percore_l1i.png}"
OUT_L2I_PNG="${OUT_L2I_PNG:-${PROFILING_DIR}/results/kernel/png/kernel_idle_busy_percore_l2i.png}"
LOG_DIR="${LOG_ROOT}/kernel_idle_busy"
RAW_DIR="${RAW_DIR:-${PROFILING_DIR}/results/kernel/raw}"
mkdir -p "$(dirname "${OUT_CSV}")" "$(dirname "${OUT_L1I_PNG}")" "$(dirname "${OUT_L2I_PNG}")" "${RAW_DIR}" "${LOG_DIR}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[err] run as root (sudo) for kernel-mode perf counting." >&2
  exit 1
fi

event0_alias="$(awk -F'|' '/^[^#].+\|/{print $1; exit}' "${EVENT_FILE}")"
event0_spec="$(awk -F'|' '/^[^#].+\|/{print $2; exit}' "${EVENT_FILE}")"
event1_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $1; exit}}' "${EVENT_FILE}")"
event1_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $2; exit}}' "${EVENT_FILE}")"
event2_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $1; exit}}' "${EVENT_FILE}")"
event2_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $2; exit}}' "${EVENT_FILE}")"
event3_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $1; exit}}' "${EVENT_FILE}")"
event3_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $2; exit}}' "${EVENT_FILE}")"

if [[ -z "${event0_alias}" || -z "${event0_spec}" || -z "${event1_alias}" || -z "${event1_spec}" || -z "${event2_alias}" || -z "${event2_spec}" || -z "${event3_alias}" || -z "${event3_spec}" ]]; then
  echo "[err] failed to parse first 4 events from ${EVENT_FILE}" >&2
  exit 1
fi

idle_raw="${RAW_DIR}/kernel_idle_percore.perfraw"
busy_raw="${RAW_DIR}/kernel_busy_percore.perfraw"
busy_log="${LOG_DIR}/kernel_busy_tomcat_86c.log"

tomcat_pattern='dacapo-23\.11-MR2-chopin\.jar.*tomcat'
busy_pid=""

cleanup_busy() {
  kill_pid_and_group "${busy_pid:-}" "TERM"
  kill_pattern "${tomcat_pattern}" "TERM"
  sleep 2
  kill_pid_and_group "${busy_pid:-}" "KILL"
  kill_pattern "${tomcat_pattern}" "KILL"
}
trap cleanup_busy EXIT INT TERM

echo "[inf] kernel_idle(per-core): cores=${CORES} scope=kernel_only secs=${IDLE_SECS}"
"${PERF_BIN}" stat --no-big-num -x, -A -C "${CORES}" --all-kernel -o "${idle_raw}" \
  -e "${event0_spec},${event1_spec},${event2_spec},${event3_spec},instructions" -- \
  sleep "${IDLE_SECS}"

echo "[inf] kernel_busy: start tomcat on cores=${CORES} active_processors=${TOMCAT_CORES}"
kill_pattern "${tomcat_pattern}" "TERM"
sleep 1
kill_pattern "${tomcat_pattern}" "KILL"
setsid taskset -c "${CORES}" bash -lc \
  "cd '${PROFILING_DIR}' && JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount=${TOMCAT_CORES} SIZE=${TOMCAT_SIZE} DACAPO_CONVERGE=0 ITERATIONS=${TOMCAT_ITERATIONS} WATCHDOG_SECS=${TOMCAT_WATCHDOG_SECS} ./runscript/bench/run_tomcat.sh" \
  > "${busy_log}" 2>&1 &
busy_pid=$!

if ! kill -0 "${busy_pid}" 2>/dev/null; then
  echo "[err] tomcat workload failed to start." >&2
  exit 1
fi

echo "[inf] kernel_busy: warmup ${BUSY_WARMUP_SECS}s"
sleep "${BUSY_WARMUP_SECS}"
if ! kill -0 "${busy_pid}" 2>/dev/null; then
  echo "[err] tomcat workload exited during warmup (see ${busy_log})." >&2
  exit 1
fi

echo "[inf] kernel_busy(per-core): cores=${CORES} scope=kernel_only secs=${BUSY_SECS}"
"${PERF_BIN}" stat --no-big-num -x, -A -C "${CORES}" --all-kernel -o "${busy_raw}" \
  -e "${event0_spec},${event1_spec},${event2_spec},${event3_spec},instructions" -- \
  sleep "${BUSY_SECS}"

cleanup_busy
wait "${busy_pid}" 2>/dev/null || true

"${PYTHON_BIN}" "${SCRIPT_DIR}/runscript/build/build_kernel_idle_busy_csvs.py" \
  --idle-raw "${idle_raw}" \
  --busy-raw "${busy_raw}" \
  --cores "${CORES}" \
  --idle-secs "${IDLE_SECS}" \
  --busy-secs "${BUSY_SECS}" \
  --event0 "${event0_alias}" \
  --event1 "${event1_alias}" \
  --event2 "${event2_alias}" \
  --event3 "${event3_alias}" \
  --main-csv "${OUT_CSV}" \
  --percore-csv "${OUT_PERCORE_CSV}" \
  --busy-log "${busy_log}"

"${PYTHON_BIN}" - "${OUT_CSV}" "${OUT_MD}" <<'PY'
import csv
import sys
from pathlib import Path

csv_path = Path(sys.argv[1])
md_path = Path(sys.argv[2])
rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8", newline="")))
by_scenario = {r["Scenario"]: r for r in rows}
order = ["kernel_idle", "kernel_busy"]

lines = []
lines.append("| Scenario | L1i MPKI | L2 inst. MPKI | iTLB MPKI | sTLB MPKI |")
lines.append("|---|---:|---:|---:|---:|")
for scenario in order:
    r = by_scenario.get(scenario, {})
    l1 = r.get("L1I_MPKI", "0")
    l2 = r.get("L2I_MPKI", "0")
    itlb = r.get("iTLB_MPKI", "0")
    stlb = r.get("sTLB_MPKI", "0")
    lines.append(f"| {scenario} | {l1} | {l2} | {itlb} | {stlb} |")

md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[ok] saved {md_path}")
PY

"${PYTHON_BIN}" "${SCRIPT_DIR}/runscript/plot/plot_kernel_idle_busy_percore.py" \
  --input "${OUT_PERCORE_CSV}" \
  --out-l1i "${OUT_L1I_PNG}" \
  --out-l2i "${OUT_L2I_PNG}"

if [[ "${KEEP_PERFRAW}" != "1" ]]; then
  rm -f "${idle_raw}" "${busy_raw}"
fi

echo "[ok] saved ${OUT_CSV}"
echo "[ok] saved ${OUT_MD}"
echo "[ok] saved ${OUT_PERCORE_CSV}"
echo "[ok] saved ${OUT_L1I_PNG}"
echo "[ok] saved ${OUT_L2I_PNG}"
