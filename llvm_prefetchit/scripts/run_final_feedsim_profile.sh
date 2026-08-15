#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"

BENCH="${ROOT}/benchmarks/dcperf/benchmarks/feedsim"
SRC="${BENCH}/src"
SERVICE_BIN="${SERVICE_BIN:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/feedsim_manual_bins/LeafNodeRank.seed2_base}"
DRIVER="${SRC}/build/workloads/ranking/DriverNodeRank"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/feedsim_seed2_profiles}"
REPS="${REPS:-5}"
DURATION="${DURATION:-30}"
WARMUP_DURATION="${WARMUP_DURATION:-20}"
SAMPLE_PERIOD="${SAMPLE_PERIOD:-50000}"
LEAF_CORES="${LEAF_CORES:-8-39}"
CLIENT_CORES="${CLIENT_CORES:-48-79}"
ICACHE_ITERS="${ICACHE_ITERS:-100000000}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'
LD_PATH="${BENCH}/third_party/build-deps/lib:${BENCH}/third_party/build-deps/lib64:/usr/local/lib:${LD_LIBRARY_PATH:-}"

mkdir -p "${OUT}"
printf 'rep,status,samples,affinity_ok,pinner_errors,trace_dir\n' > "${OUT}/profiles.csv"

leaf_pid=""
driver_pid=""
service_pinner=""
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

for rep in $(seq 1 "${REPS}"); do
  dir="${OUT}/rep${rep}"
  trace="${dir}/trace"
  data="${dir}/l2miss_profile.data"
  port=$((34000 + rep))
  monitor_port=$((34100 + rep))
  driver_monitor_port=$((34200 + rep))
  affinity_ok=1
  rm -rf "${dir}"
  mkdir -p "${trace}"
  fc_assert_frequency "${FC_CONTROL_CORE},${LEAF_CORES},${CLIENT_CORES}" "${dir}/frequency_state.csv"

  taskset -c "${LEAF_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    MALLOC_CONF='narenas:40,dirty_decay_ms:5000' \
    "${SERVICE_BIN}" --port="${port}" --monitor_port="${monitor_port}" \
    --graph_scale=21 --graph_subset=2000000 \
    --threads=4 --cpu_threads=4 --timekeeper_threads=1 --io_threads=1 \
    --srv_threads=4 --srv_io_threads=4 --num_objects=2000 \
    --graph_max_iters=1 --noaffinity --min_icache_iterations="${ICACHE_ITERS}" \
    > "${dir}/leaf.log" 2>&1 &
  leaf_pid="$!"
  fc_start_pinner "${leaf_pid}" "${LEAF_CORES}" "${dir}/service.pin.log"
  service_pinner="${FC_PINNER_PID}"
  wait_for_port "${port}"

  taskset -c "${CLIENT_CORES}" env LD_LIBRARY_PATH="${LD_PATH}" \
    "${DRIVER}" --server="127.0.0.1:${port}" --monitor_port="${driver_monitor_port}" \
    --threads=8 --connections=8 --depth=1 --qps=20 > "${dir}/driver.log" 2>&1 &
  driver_pid="$!"
  fc_start_pinner "${driver_pid}" "${CLIENT_CORES}" "${dir}/driver.pin.log"
  driver_pinner="${FC_PINNER_PID}"
  wait_for_port "${driver_monitor_port}"
  fc_wait_for_stable_pinning "${driver_pid}" "${CLIENT_CORES}" "${dir}/driver_affinity.csv" 20 || affinity_ok=0
  sleep "${WARMUP_DURATION}"
  fc_wait_for_stable_pinning "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity.csv" 30 || affinity_ok=0

  perf record -e "${EVENT}" -b -c "${SAMPLE_PERIOD}" -o "${data}" \
    -p "${leaf_pid}" -- sleep "${DURATION}" > "${dir}/record.out" 2> "${dir}/record.err" || true
  fc_audit_pid_affinity "${leaf_pid}" "${LEAF_CORES}" "${dir}/service_affinity_after.csv" || affinity_ok=0
  fc_audit_pid_affinity "${driver_pid}" "${CLIENT_CORES}" "${dir}/driver_affinity_after.csv" || affinity_ok=0

  kill -INT "${driver_pid}" >/dev/null 2>&1 || true
  wait "${driver_pid}" >/dev/null 2>&1 || true
  driver_pid=""
  kill "${driver_pinner}" >/dev/null 2>&1 || true
  wait "${driver_pinner}" >/dev/null 2>&1 || true
  driver_pinner=""
  kill -INT "${leaf_pid}" >/dev/null 2>&1 || true
  wait "${leaf_pid}" >/dev/null 2>&1 || true
  leaf_pid=""
  kill "${service_pinner}" >/dev/null 2>&1 || true
  wait "${service_pinner}" >/dev/null 2>&1 || true
  service_pinner=""

  if [[ -s "${data}" ]]; then
    "${ROOT}/profiling/analyze_pebs_trace.sh" --data "${data}" --out-dir "${trace}" \
      --event-label "${EVENT}" --binary "${SERVICE_BIN}" > "${dir}/analyze.log" 2>&1 || true
  fi
  samples="$(awk -F: '/LBR samples parsed \(raw\)/ {gsub(/[^0-9]/,"",$2); print $2}' "${trace}/trace_summary.md" 2>/dev/null | head -1)"
  pinner_errors="$( { rg -c 'ERROR' "${dir}/service.pin.log" "${dir}/driver.pin.log" 2>/dev/null || true; } | awk -F: '{s+=$NF} END {print s+0}')"
  status=failed
  [[ -n "${samples}" && "${samples}" -gt 0 && "${affinity_ok}" == 1 && "${pinner_errors}" == 0 ]] && status=ok
  printf '%s,%s,%s,%s,%s,%s\n' "${rep}" "${status}" "${samples:-0}" "${affinity_ok}" "${pinner_errors}" "${trace}" | tee -a "${OUT}/profiles.csv"
  rm -f "${data}"
done

summary_args=()
for rep in $(seq 1 "${REPS}"); do
  summary_args+=(--trace-dir "${OUT}/rep${rep}/trace")
done
python3 "${ROOT}/llvm_prefetchit/tools/summarize_profile_repetition.py" \
  --benchmark feedsim_seed2 --out-dir "${OUT}/repetition_summary" \
  "${summary_args[@]}"

for rep in $(seq 1 "${REPS}"); do
  rm -f "${OUT}/rep${rep}/trace/lbr_raw_dump.txt" \
        "${OUT}/rep${rep}/trace/lbr_symbolic_dump.txt"
done
