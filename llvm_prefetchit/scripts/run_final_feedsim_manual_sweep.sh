#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"

BENCH="${ROOT}/benchmarks/dcperf/benchmarks/feedsim"
SRC="${BENCH}/src"
BIN_DIR="${ROOT}/llvm_prefetchit/work/final_campaign_20260711/feedsim_manual_bins"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/feedsim_manual_screen}"
LABELS="${LABELS:-base d4_target d4_target_next d8_target d8_target_next d16_target d16_target_next d32_target d32_target_next d64_target d64_target_next d128_target d128_target_next}"
REPS="${REPS:-1}"
DURATION="${DURATION:-20}"
WARMUP_DURATION="${WARMUP_DURATION:-10}"
REQUESTED_QPS="${REQUESTED_QPS:-20}"
ICACHE_ITERS="${ICACHE_ITERS:-100000000}"
SERVICE_THREADS="${SERVICE_THREADS:-4}"
LEAF_CORES="${LEAF_CORES:-8-39}"
CLIENT_CORES="${CLIENT_CORES:-48-79}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
LD_PATH="${BENCH}/third_party/build-deps/lib:${BENCH}/third_party/build-deps/lib64:/usr/local/lib:${LD_LIBRARY_PATH:-}"

mkdir -p "${OUT}/runs"
SUMMARY="${OUT}/runs.csv"
printf 'rep,label,status,achieved_qps,avg_ms,p95_ms,instructions,cycles,l2i_misses,l2i_mpki,ipc,context_switches,cpu_migrations,service_threads,affinity_ok,pinner_errors\n' > "${SUMMARY}"

leaf_pid=""
service_pinner=""
client_pinner=""
warmup_pid=""
warmup_pinner=""
cleanup() {
  for pid in "${client_pinner}" "${warmup_pinner}" "${service_pinner}"; do
    [[ -n "${pid}" ]] && kill "${pid}" >/dev/null 2>&1 || true
  done
  [[ -n "${warmup_pid}" ]] && fc_kill_pid "${warmup_pid}"
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

parse_run() {
  local rep="$1" label="$2" dir="$3" affinity_ok="$4" pinner_errors="$5"
  python3 - "${rep}" "${label}" "${dir}" "${affinity_ok}" "${pinner_errors}" <<'PY'
import csv
import math
import pathlib
import sys

rep, label, raw_dir, affinity_ok, pinner_errors = sys.argv[1:]
run = pathlib.Path(raw_dir)
result_files = list(run.glob("result*.txt"))
result = {}
if result_files:
    rows = list(csv.DictReader(result_files[0].open()))
    if rows:
        result = rows[-1]
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
status = "ok" if result and math.isfinite(mpki) else "failed"
values = [
    rep, label, status, result.get("achieved_qps", "nan"), result.get("avg_ms", "nan"),
    result.get("95p_ms", "nan"), inst, cycles, miss, mpki, ipc,
    perf.get("context-switches", math.nan), perf.get("cpu-migrations", math.nan),
    sum(1 for _ in (run / "service_affinity.csv").open()) - 1 if (run / "service_affinity.csv").exists() else 0,
    affinity_ok, pinner_errors,
]
print(",".join(str(value) for value in values))
PY
}

run_one() {
  local rep="$1" label="$2" ordinal="$3"
  local dir="${OUT}/runs/rep${rep}_${label}"
  local binary="${BIN_DIR}/LeafNodeRank.${label}"
  local port=$((28000 + rep * 100 + ordinal))
  local monitor_port=$((29000 + rep * 100 + ordinal))
  local driver_monitor_port=$((30000 + rep * 100 + ordinal))
  local result="${dir}/result.txt"
  local affinity_ok=1 pinner_errors=0 measure_pid rc
  rm -rf "${dir}"
  mkdir -p "${dir}"
  fc_assert_frequency "${FC_CONTROL_CORE},${LEAF_CORES},${CLIENT_CORES}" "${dir}/frequency_state.csv"
  [[ -x "${binary}" ]] || { echo "missing ${binary}" >&2; return 1; }

  taskset -c "${LEAF_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    MALLOC_CONF='narenas:40,dirty_decay_ms:5000' \
    "${binary}" \
      --port="${port}" --monitor_port="${monitor_port}" \
      --graph_scale=21 --graph_subset=2000000 \
      --threads="${SERVICE_THREADS}" --cpu_threads="${SERVICE_THREADS}" \
      --timekeeper_threads=1 --io_threads=1 \
      --srv_threads="${SERVICE_THREADS}" --srv_io_threads="${SERVICE_THREADS}" \
      --num_objects=2000 --graph_max_iters=1 --noaffinity \
      --min_icache_iterations="${ICACHE_ITERS}" \
      > "${dir}/leaf.log" 2>&1 &
  leaf_pid="$!"
  fc_start_pinner "${leaf_pid}" "${LEAF_CORES}" "${dir}/service.pin.log"
  service_pinner="${FC_PINNER_PID}"
  wait_for_port "${port}"

  # Exercise the same connection path before attaching the PMU. FeedSim
  # creates request-processing threads lazily on the first queries; pinning
  # those threads during the measured interval would otherwise be counted as
  # workload CPU migrations.
  set +e
  taskset -c "${CLIENT_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    "${SRC}/scripts/search_qps.sh" -s 95p -t "${WARMUP_DURATION}" -w 2 -m 0 \
    -q "${REQUESTED_QPS}" -o "${dir}/warmup_result.txt" -- \
    "${SRC}/build/workloads/ranking/DriverNodeRank" \
    --server="127.0.0.1:${port}" --monitor_port="$((driver_monitor_port + 1000))" \
    --threads=8 --connections=8 \
    > "${dir}/warmup_driver.log" 2>&1 &
  warmup_pid="$!"
  fc_start_tree_pinner "${warmup_pid}" "${CLIENT_CORES}" "${dir}/warmup_client.pin.log"
  warmup_pinner="${FC_PINNER_PID}"
  wait "${warmup_pid}"
  local warmup_rc=$?
  set -e
  printf '%s\n' "${warmup_rc}" > "${dir}/warmup_exit_code.txt"
  warmup_pid=""
  kill "${warmup_pinner}" >/dev/null 2>&1 || true
  wait "${warmup_pinner}" >/dev/null 2>&1 || true
  warmup_pinner=""
  # A short high-icache-cost warmup can legitimately end before receiving a
  # completed response, making search_qps return 1. Its only success criteria
  # here are that the server remains alive and all lazily-created threads have
  # reached stable one-core affinities, which are checked below.
  kill -0 "${leaf_pid}" 2>/dev/null || affinity_ok=0
  fc_wait_for_stable_pinning "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity.csv" 30 || affinity_ok=0

  set +e
  perf stat -x, -o "${dir}/perf.csv" \
    -e "instructions,cycles,${EVENT},context-switches,cpu-migrations" \
    -p "${leaf_pid}" -- \
    taskset -c "${CLIENT_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
      "${SRC}/scripts/search_qps.sh" -s 95p -t "${DURATION}" -m 0 \
      -q "${REQUESTED_QPS}" -o "${result}" -- \
      "${SRC}/build/workloads/ranking/DriverNodeRank" \
      --server="127.0.0.1:${port}" --monitor_port="${driver_monitor_port}" \
      --threads=8 --connections=8 \
      > "${dir}/driver.log" 2>&1 &
  measure_pid="$!"
  fc_start_tree_pinner "${measure_pid}" "${CLIENT_CORES}" "${dir}/client.pin.log"
  client_pinner="${FC_PINNER_PID}"
  wait "${measure_pid}"
  rc=$?
  set -e
  kill "${client_pinner}" >/dev/null 2>&1 || true
  wait "${client_pinner}" >/dev/null 2>&1 || true
  client_pinner=""
  pinner_errors="$(rg -c 'ERROR' "${dir}/service.pin.log" "${dir}/warmup_client.pin.log" "${dir}/client.pin.log" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}')"
  fc_audit_pid_affinity "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity_after.csv" || affinity_ok=0
  kill -INT "${leaf_pid}" >/dev/null 2>&1 || true
  wait "${leaf_pid}" >/dev/null 2>&1 || true
  leaf_pid=""
  kill "${service_pinner}" >/dev/null 2>&1 || true
  wait "${service_pinner}" >/dev/null 2>&1 || true
  service_pinner=""
  parse_run "${rep}" "${label}" "${dir}" "${affinity_ok}" "${pinner_errors}" | tee -a "${SUMMARY}"
  return "${rc}"
}

for rep in $(seq 1 "${REPS}"); do
  ordinal=0
  for label in ${LABELS}; do
    ordinal=$((ordinal + 1))
    run_one "${rep}" "${label}" "${ordinal}" || true
  done
done

cat "${SUMMARY}"
