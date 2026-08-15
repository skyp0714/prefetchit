#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"

BENCH="${ROOT}/benchmarks/dcperf/benchmarks/feedsim"
SRC="${BENCH}/src"
BIN_DIR="${BIN_DIR:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/feedsim_manual_bins}"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/feedsim_closedloop_screen}"
LABELS="${LABELS:-base d4_target d4_target_next d8_target d8_target_next d16_target d16_target_next d32_target d32_target_next d64_target d64_target_next d128_target d128_target_next}"
REPS="${REPS:-1}"
ALTERNATE_ORDER="${ALTERNATE_ORDER:-0}"
DURATION="${DURATION:-60}"
WARMUP_DURATION="${WARMUP_DURATION:-20}"
DRAIN_DURATION="${DRAIN_DURATION:-3}"
ICACHE_ITERS="${ICACHE_ITERS:-100000000}"
SERVICE_THREADS="${SERVICE_THREADS:-4}"
DRIVER_THREADS="${DRIVER_THREADS:-4}"
DRIVER_CONNECTIONS="${DRIVER_CONNECTIONS:-2}"
DRIVER_DEPTH="${DRIVER_DEPTH:-1}"
DRIVER_QPS="${DRIVER_QPS:-0}"
LEAF_CORES="${LEAF_CORES:-8-39}"
CLIENT_CORES="${CLIENT_CORES:-48-79}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
LD_PATH="${BENCH}/third_party/build-deps/lib:${BENCH}/third_party/build-deps/lib64:/usr/local/lib:${LD_LIBRARY_PATH:-}"
DRIVER="${SRC}/build/workloads/ranking/DriverNodeRank"

mkdir -p "${OUT}/runs"
SUMMARY="${OUT}/runs.csv"
printf 'rep,label,status,completed_qps,completed_responses,sent_qps,sent_queries,avg_ms,p95_ms,instructions,cycles,l2i_misses,l2i_mpki,ipc,context_switches,cpu_migrations,service_threads,service_affinity_ok,driver_threads,driver_affinity_ok,pinner_errors\n' > "${SUMMARY}"

leaf_pid=""
service_pinner=""
driver_pid=""
driver_pinner=""
cleanup() {
  for pid in "${driver_pinner}" "${service_pinner}"; do
    [[ -n "${pid}" ]] && kill "${pid}" >/dev/null 2>&1 || true
  done
  [[ -n "${driver_pid}" ]] && fc_kill_pid "${driver_pid}"
  [[ -n "${leaf_pid}" ]] && fc_kill_pid "${leaf_pid}"
  return 0
}
trap cleanup EXIT

wait_for_port() {
  local port="$1"
  for _ in {1..300}; do
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

start_driver() {
  local port="$1" monitor_port="$2" log="$3" pin_log="$4"
  taskset -c "${CLIENT_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    "${DRIVER}" --server="127.0.0.1:${port}" --monitor_port="${monitor_port}" \
    --threads="${DRIVER_THREADS}" --connections="${DRIVER_CONNECTIONS}" \
    --depth="${DRIVER_DEPTH}" --qps="${DRIVER_QPS}" > "${log}" 2>&1 &
  driver_pid="$!"
  fc_start_pinner "${driver_pid}" "${CLIENT_CORES}" "${pin_log}"
  driver_pinner="${FC_PINNER_PID}"
}

stop_driver() {
  kill -INT "${driver_pid}" >/dev/null 2>&1 || true
  for _ in $(seq 1 $((DRAIN_DURATION * 10))); do
    kill -0 "${driver_pid}" 2>/dev/null || break
    sleep 0.1
  done
  fc_kill_pid "${driver_pid}"
  wait "${driver_pid}" >/dev/null 2>&1 || true
  driver_pid=""
  kill "${driver_pinner}" >/dev/null 2>&1 || true
  wait "${driver_pinner}" >/dev/null 2>&1 || true
  driver_pinner=""
}

parse_run() {
  local rep="$1" label="$2" dir="$3" service_ok="$4" driver_ok="$5" pinner_errors="$6"
  python3 - "${rep}" "${label}" "${dir}" "${service_ok}" "${driver_ok}" "${pinner_errors}" <<'PY'
import csv
import math
import pathlib
import re
import sys

rep, label, raw_dir, service_ok, driver_ok, pinner_errors = sys.argv[1:]
run = pathlib.Path(raw_dir)
text = (run / "driver.log").read_text(errors="replace") if (run / "driver.log").exists() else ""

def match(pattern):
    found = re.search(pattern, text, re.MULTILINE)
    return float(found.group(1)) if found else math.nan

def integer(pattern):
    found = re.search(pattern, text, re.MULTILINE)
    return int(found.group(1)) if found else 0

def totals(name):
    path = run / name
    if not path.exists():
        return 0, 0
    rows = list(csv.DictReader(path.open()))
    return (
        sum(int(row.get("sent", 0)) for row in rows),
        sum(int(row.get("completed", 0)) for row in rows),
    )

sent_before, completed_before = totals("completion_before.csv")
sent_after, completed_after = totals("completion_after.csv")
sent_queries = max(0, sent_after - sent_before)
completed_responses = max(0, completed_after - completed_before)
duration = float((run / "measurement_duration.txt").read_text())
completed_qps = completed_responses / duration
sent_qps = sent_queries / duration
avg_ms = match(r"^\s*avg:\s*([0-9.]+) ms")
p95_ms = match(r"^\s*95p:\s*([0-9.]+) ms")

perf = {}
path = run / "perf.csv"
if path.exists():
    for row in csv.reader(path.open()):
        if len(row) < 3 or row[0].startswith("<"):
            continue
        try:
            perf[row[2].strip()] = float(row[0])
        except ValueError:
            pass
inst = perf.get("instructions", math.nan)
cycles = perf.get("cycles", math.nan)
miss = perf.get("L2I_CODE_RD_MISS", math.nan)
mpki = miss / inst * 1000.0 if inst and math.isfinite(inst) else math.nan
ipc = inst / cycles if cycles and math.isfinite(cycles) else math.nan
status = "ok" if completed_responses > 0 and math.isfinite(mpki) and service_ok == "1" and driver_ok == "1" else "failed"

def thread_count(name):
    p = run / name
    return max(0, sum(1 for _ in p.open()) - 1) if p.exists() else 0

values = [
    rep, label, status, completed_qps, completed_responses, sent_qps, sent_queries,
    avg_ms, p95_ms, inst, cycles, miss, mpki, ipc,
    perf.get("context-switches", math.nan), perf.get("cpu-migrations", math.nan),
    thread_count("service_affinity_after.csv"), service_ok,
    thread_count("driver_affinity.csv"), driver_ok, pinner_errors,
]
print(",".join(str(value) for value in values))
PY
}

run_one() {
  local rep="$1" label="$2" ordinal="$3"
  local dir="${OUT}/runs/rep${rep}_${label}"
  local binary="${BIN_DIR}/LeafNodeRank.${label}"
  local port=$((31000 + rep * 100 + ordinal))
  local monitor_port=$((32000 + rep * 100 + ordinal))
  local service_ok=1 driver_ok=1 pinner_errors
  rm -rf "${dir}"
  mkdir -p "${dir}"
  fc_assert_frequency "${FC_CONTROL_CORE},${LEAF_CORES},${CLIENT_CORES}" "${dir}/frequency_state.csv"
  [[ -x "${binary}" && -x "${DRIVER}" ]] || return 1

  taskset -c "${LEAF_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    MALLOC_CONF='narenas:40,dirty_decay_ms:5000' \
    "${binary}" --port="${port}" --monitor_port="${monitor_port}" \
    --graph_scale=21 --graph_subset=2000000 \
    --threads="${SERVICE_THREADS}" --cpu_threads="${SERVICE_THREADS}" \
    --timekeeper_threads=1 --io_threads=1 \
    --srv_threads="${SERVICE_THREADS}" --srv_io_threads="${SERVICE_THREADS}" \
    --num_objects=2000 --graph_max_iters=1 --noaffinity \
    --min_icache_iterations="${ICACHE_ITERS}" > "${dir}/leaf.log" 2>&1 &
  leaf_pid="$!"
  fc_start_pinner "${leaf_pid}" "${LEAF_CORES}" "${dir}/service.pin.log"
  service_pinner="${FC_PINNER_PID}"
  wait_for_port "${port}"

  local driver_monitor_port=$((monitor_port + 1000))
  start_driver "${port}" "${driver_monitor_port}" "${dir}/driver.log" "${dir}/driver.pin.log"
  wait_for_port "${driver_monitor_port}"
  fc_wait_for_stable_pinning "${driver_pid}" "${CLIENT_CORES}" "${dir}/driver_affinity.csv" 20 || driver_ok=0
  sleep "${WARMUP_DURATION}"
  fc_wait_for_stable_pinning "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity.csv" 30 || service_ok=0
  curl --fail --silent "http://127.0.0.1:${driver_monitor_port}/completion_totals" > "${dir}/completion_before.csv"
  printf '%s\n' "${DURATION}" > "${dir}/measurement_duration.txt"
  perf stat -x, -o "${dir}/perf.csv" \
    -e "instructions,cycles,${EVENT},context-switches,cpu-migrations" \
    -p "${leaf_pid}" -- sleep "${DURATION}"
  curl --fail --silent "http://127.0.0.1:${driver_monitor_port}/completion_totals" > "${dir}/completion_after.csv"
  fc_audit_pid_affinity "${driver_pid}" "${CLIENT_CORES}" "${dir}/driver_affinity_after.csv" || driver_ok=0
  stop_driver
  fc_audit_pid_affinity "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity_after.csv" || service_ok=0
  pinner_errors="$(rg -c 'ERROR' "${dir}/service.pin.log" "${dir}/driver.pin.log" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')"

  kill -INT "${leaf_pid}" >/dev/null 2>&1 || true
  wait "${leaf_pid}" >/dev/null 2>&1 || true
  leaf_pid=""
  kill "${service_pinner}" >/dev/null 2>&1 || true
  wait "${service_pinner}" >/dev/null 2>&1 || true
  service_pinner=""
  parse_run "${rep}" "${label}" "${dir}" "${service_ok}" "${driver_ok}" "${pinner_errors}" | tee -a "${SUMMARY}"
}

for rep in $(seq 1 "${REPS}"); do
  ordinal=0
  labels_this_rep="${LABELS}"
  if [[ "${ALTERNATE_ORDER}" == "1" && $((rep % 2)) -eq 0 ]]; then
    labels_this_rep="$(xargs -n1 <<< "${LABELS}" | tac | xargs)"
  fi
  for label in ${labels_this_rep}; do
    ordinal=$((ordinal + 1))
    run_one "${rep}" "${label}" "${ordinal}" || true
  done
done

cat "${SUMMARY}"
