#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 ]]; then
  echo "usage: $0 BENCHMARK LABEL MID_TIER_BINARY [OUT_DIR]" >&2
  exit 2
fi

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src"
DATA="${ROOT}/llvm_prefetchit/results/datacenter_goal_20260708/microsuite_screen2/data"
DEPROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
BENCHMARK="$1"
LABEL="$2"
MID_BINARY="$(readlink -f "$3")"
OUT="${4:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_strict/${BENCHMARK}_${LABEL}}"

DURATION="${DURATION:-60}"
PREWARM_DURATION="${PREWARM_DURATION:-0}"
PREWARM_DEPTH="${PREWARM_DEPTH:-${DEPTH:-32}}"
MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION:-0}"
GRPC_CORE_CAP="${GRPC_CORE_CAP:-0}"
PROFILE_RECORD="${PROFILE_RECORD:-0}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-50000}"
PERF_TARGET_ROLE="${PERF_TARGET_ROLE:-mid}"
DISABLE_ASLR="${DISABLE_ASLR:-0}"
ROUTER_PREPOPULATE="${ROUTER_PREPOPULATE:-0}"
ROUTER_LEAF_INSTANCES="${ROUTER_LEAF_INSTANCES:-1}"
ROUTER_FIXED_PREWARM_REQUESTS="${ROUTER_FIXED_PREWARM_REQUESTS:-0}"
ROUTER_FIXED_PREWARM_TIMEOUT="${ROUTER_FIXED_PREWARM_TIMEOUT:-180}"
EVICT_CACHES="${EVICT_CACHES:-0}"
EVICT_CORES="${EVICT_CORES:-1-70}"
EVICT_BYTES_PER_CORE="${EVICT_BYTES_PER_CORE:-8388608}"
EVICT_PASSES="${EVICT_PASSES:-4}"
SYNC_MEASUREMENT_START="${SYNC_MEASUREMENT_START:-0}"
SYNC_MEASUREMENT_TIMEOUT="${SYNC_MEASUREMENT_TIMEOUT:-180}"
CACHE_EVICTOR="${CACHE_EVICTOR:-${ROOT}/llvm_prefetchit/tools/evict_cpu_caches}"
DEPTH="${DEPTH:-32}"
PARALLELISM="${PARALLELISM:-4}"
DISPATCH="${DISPATCH:-4}"
RESPONSES="${RESPONSES:-4}"
CONTROL_CORE=0
MEM_CORES="1-8"
LEAF_CORES="9-20"
MID_CORES="21-55"
CLIENT_CORES="56-70"
ALL_CORES="0-70"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
PROFILE_EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'
GRPC_CORE_CAP_SO="${ROOT}/llvm_prefetchit/tools/grpc_core_cap.so"
THREAD_PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
THREAD_SNAPSHOT="${ROOT}/llvm_prefetchit/tools/snapshot_thread_activity.py"

# shellcheck source=/dev/null
source "${COMMON}"
export LD_LIBRARY_PATH="${DEPROOT}/usr/lib:${DEPROOT}/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

ASLR_PREFIX=()
if ((DISABLE_ASLR == 1)); then
  ASLR_PREFIX=(setarch "$(uname -m)" -R)
fi

MEM_PID=""
LEAF_PID=""
LEAF_PIDS=()
LEAF_CORE_RANGES=()
MID_PID=""
CLIENT_PID=""
PINNER_PIDS=()

stop_pid() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] || return 0
  kill "${pid}" >/dev/null 2>&1 || true
  for _ in {1..30}; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL "${pid}" >/dev/null 2>&1 || true
}

cleanup() {
  set +e
  stop_pid "${CLIENT_PID}"
  stop_pid "${MID_PID}"
  stop_pid "${LEAF_PID}"
  for pid in "${LEAF_PIDS[@]}"; do
    stop_pid "${pid}"
  done
  stop_pid "${MEM_PID}"
  for pid in "${PINNER_PIDS[@]}"; do
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
  done
}

interrupted() {
  trap - INT TERM EXIT
  cleanup
  exit 130
}
trap cleanup EXIT
trap interrupted INT TERM

wait_port() {
  local port="$1" pid="${2:-}" deadline=$((SECONDS + 60))
  while ((SECONDS < deadline)); do
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1 && return 0
    if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
      echo "process ${pid} exited before port ${port} opened" >&2
      return 1
    fi
    sleep 0.1
  done
  echo "port ${port} did not open" >&2
  return 1
}

start_pinner() {
  local pid="$1" cores="$2" name="$3"
  fc_start_pinner "${pid}" "${cores}" "${OUT}/${name}_pinner.log"
  PINNER_PIDS+=("${FC_PINNER_PID}")
}

mkdir -p "${OUT}"
rm -f "${OUT}"/*.log "${OUT}"/*.csv "${OUT}"/*.json "${OUT}/l2miss_profile.data"
[[ -x "${MID_BINARY}" ]] || { echo "missing executable: ${MID_BINARY}" >&2; exit 2; }
[[ -f "${THREAD_PIN_SO}" ]] || {
  echo "missing pthread core-pin preload: ${THREAD_PIN_SO}" >&2
  exit 2
}
BASE_PRELOAD="${THREAD_PIN_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
MID_PRELOAD="${BASE_PRELOAD}"
LEAF_PRELOAD="${BASE_PRELOAD}"
CLIENT_PRELOAD="${BASE_PRELOAD}"
if ((GRPC_CORE_CAP > 0)); then
  [[ -f "${GRPC_CORE_CAP_SO}" ]] || {
    echo "missing gRPC core-cap preload: ${GRPC_CORE_CAP_SO}" >&2
    exit 2
  }
  MID_PRELOAD="${THREAD_PIN_SO}:${GRPC_CORE_CAP_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
  LEAF_PRELOAD="${THREAD_PIN_SO}:${GRPC_CORE_CAP_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
  CLIENT_PRELOAD="${THREAD_PIN_SO}:${GRPC_CORE_CAP_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
fi
MID_ENV=(env "LD_PRELOAD=${MID_PRELOAD}" "PREFETCHIT_THREAD_PIN_CORES=22-55")
if ((GRPC_CORE_CAP > 0)); then
  MID_ENV+=("PREFETCHIT_GRPC_CORE_CAP=${GRPC_CORE_CAP}")
fi
LEAF_ENV=(env "LD_PRELOAD=${LEAF_PRELOAD}" "PREFETCHIT_THREAD_PIN_CORES=10-20")
CLIENT_ENV=(env "LD_PRELOAD=${CLIENT_PRELOAD}" "PREFETCHIT_THREAD_PIN_CORES=57-70")
if ((GRPC_CORE_CAP > 0)); then
  LEAF_ENV+=("PREFETCHIT_GRPC_CORE_CAP=${GRPC_CORE_CAP}")
  CLIENT_ENV+=("PREFETCHIT_GRPC_CORE_CAP=${GRPC_CORE_CAP}")
fi
MEM_ENV=(env "LD_PRELOAD=${BASE_PRELOAD}" "PREFETCHIT_THREAD_PIN_CORES=2-8")
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_start.csv"
if ((EVICT_CACHES == 1)); then
  [[ -x "${CACHE_EVICTOR}" ]] || {
    echo "missing cache evictor: ${CACHE_EVICTOR}" >&2
    exit 2
  }
  "${CACHE_EVICTOR}" --cores "${EVICT_CORES}" \
    --bytes-per-core "${EVICT_BYTES_PER_CORE}" --passes "${EVICT_PASSES}" \
    > "${OUT}/cache_evictor.log"
fi

case "${BENCHMARK}" in
  router)
    ((ROUTER_LEAF_INSTANCES >= 1 && ROUTER_LEAF_INSTANCES <= 4)) || {
      echo "ROUTER_LEAF_INSTANCES must be between 1 and 4" >&2
      exit 2
    }
    : > "${OUT}/leaf_ips.txt"
    taskset -c 1 "${ASLR_PREFIX[@]}" "${MEM_ENV[@]}" \
      memcached -p 61211 -u "${USER}" -t 2 -m 256 >"${OUT}/memcached.log" 2>&1 &
    MEM_PID="$!"
    start_pinner "${MEM_PID}" "${MEM_CORES}" memcached
    wait_port 61211 "${MEM_PID}"
    if ((ROUTER_PREPOPULATE == 1)); then
      python3 "${ROOT}/llvm_prefetchit/tools/populate_router_memcached.py" \
        --input "${DATA}/router_queries.bin" --port 61211 \
        > "${OUT}/memcached_population.json"
    fi

    for ((leaf_index=0; leaf_index<ROUTER_LEAF_INSTANCES; leaf_index++)); do
      leaf_port=$((61251 + leaf_index))
      leaf_core_start=$((9 + leaf_index * 6))
      leaf_core_end=$((leaf_core_start + 5))
      leaf_thread_start=$((leaf_core_start + 1))
      leaf_core_range="${leaf_core_start}-${leaf_core_end}"
      leaf_env=(
        env "LD_PRELOAD=${LEAF_PRELOAD}"
        "PREFETCHIT_THREAD_PIN_CORES=${leaf_thread_start}-${leaf_core_end}"
      )
      if ((GRPC_CORE_CAP > 0)); then
        leaf_env+=("PREFETCHIT_GRPC_CORE_CAP=${GRPC_CORE_CAP}")
      fi
      printf '127.0.0.1:%s\n' "${leaf_port}" >> "${OUT}/leaf_ips.txt"
      taskset -c "${leaf_core_start}" "${ASLR_PREFIX[@]}" "${leaf_env[@]}" \
        "${SRC}/Router/lookup_service/service/lookup_server" \
        "127.0.0.1:${leaf_port}" 61211 2 1 \
        >"${OUT}/leaf${leaf_index}.log" 2>&1 &
      leaf_pid="$!"
      LEAF_PIDS+=("${leaf_pid}")
      LEAF_CORE_RANGES+=("${leaf_core_range}")
      start_pinner "${leaf_pid}" "${leaf_core_range}" "leaf${leaf_index}"
      wait_port "${leaf_port}" "${leaf_pid}"
    done

    if ((ROUTER_LEAF_INSTANCES > 1)); then
      MID_CORES="33-55"
      router_mid_env=(
        env "LD_PRELOAD=${MID_PRELOAD}" "PREFETCHIT_THREAD_PIN_CORES=34-55"
      )
      if ((GRPC_CORE_CAP > 0)); then
        router_mid_env+=("PREFETCHIT_GRPC_CORE_CAP=${GRPC_CORE_CAP}")
      fi
      mid_start_core=33
    else
      router_mid_env=("${MID_ENV[@]}")
      mid_start_core=21
    fi
    taskset -c "${mid_start_core}" "${ASLR_PREFIX[@]}" \
      "${router_mid_env[@]}" "${MID_BINARY}" \
      "${ROUTER_LEAF_INSTANCES}" "${OUT}/leaf_ips.txt" 127.0.0.1:61250 \
      "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" 1 \
      >"${OUT}/mid.log" 2>&1 &
    MID_PID="$!"
    start_pinner "${MID_PID}" "${MID_CORES}" mid
    wait_port 61250 "${MID_PID}"
    CLIENT_COMMAND=(
      "${SRC}/Router/load_generator/load_generator_closed_loop"
      "${DATA}/router_queries.bin" "${OUT}/result.txt" "${DURATION}"
      "${DEPTH}" 127.0.0.1:61250 1 1
    )
    ;;
  setalgebra)
    printf '127.0.0.1:62251\n' > "${OUT}/leaf_ips.txt"
    taskset -c 9 "${ASLR_PREFIX[@]}" "${LEAF_ENV[@]}" \
      "${SRC}/SetAlgebra/intersection_service/service/intersection_server" \
      127.0.0.1:62251 "${DATA}/set_dataset.txt" 2 1 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 62251 "${LEAF_PID}"

    taskset -c 21 "${ASLR_PREFIX[@]}" "${MID_ENV[@]}" "${MID_BINARY}" \
      1 "${OUT}/leaf_ips.txt" 127.0.0.1:62250 \
      "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" \
      >"${OUT}/mid.log" 2>&1 &
    MID_PID="$!"
    start_pinner "${MID_PID}" "${MID_CORES}" mid
    wait_port 62250 "${MID_PID}"
    CLIENT_COMMAND=(
      "${SRC}/SetAlgebra/load_generator/load_generator_closed_loop"
      "${DATA}/set_queries.txt" "${OUT}/result.txt" "${DURATION}"
      "${DEPTH}" 127.0.0.1:62250
    )
    ;;
  hdsearch)
    HD_DATA="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/microsuite/hdsearch_synth_data_8192"
    HD_LOADGEN="${HD_LOADGEN:-${SRC}/HDSearch/load_generator/load_generator_closed_loop}"
    printf '127.0.0.1:64251\n' > "${OUT}/leaf_ips.txt"
    taskset -c 9 "${ASLR_PREFIX[@]}" "${LEAF_ENV[@]}" \
      "${SRC}/HDSearch/bucket_service/service/bucket_server" \
      "${HD_DATA}/dataset.bin" 127.0.0.1:64251 2 1 0 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 64251 "${LEAF_PID}"

    taskset -c 21 "${ASLR_PREFIX[@]}" "${MID_ENV[@]}" "${MID_BINARY}" \
      "${HD_HASH_TABLES:-8}" "${HD_KEY_LENGTH:-12}" "${HD_PROBES:-2}" \
      1 "${OUT}/leaf_ips.txt" "${HD_DATA}/dataset.bin" 2 \
      127.0.0.1:64250 "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" 0 \
      >"${OUT}/mid.log" 2>&1 &
    MID_PID="$!"
    start_pinner "${MID_PID}" "${MID_CORES}" mid
    wait_port 64250 "${MID_PID}"
    CLIENT_COMMAND=(
      "${HD_LOADGEN}"
      "${HD_DATA}/queries.bin" "${OUT}/result.txt" 1 "${DURATION}"
      "${DEPTH}" 127.0.0.1:64250 "${OUT}/timing.txt"
      "${OUT}/qps.txt" "${OUT}/util.txt"
    )
    ;;
  recommend)
    RECOMMEND_LOADGEN="${RECOMMEND_LOADGEN:-${SRC}/Recommend/load_generator/load_generator_closed_loop}"
    RECOMMEND_CF_SERVER="${RECOMMEND_CF_SERVER:-${SRC}/Recommend/cf_service/service/cf_server}"
    printf '127.0.0.1:63251\n' > "${OUT}/leaf_ips.txt"
    taskset -c 9 "${ASLR_PREFIX[@]}" "${LEAF_ENV[@]}" \
      "${RECOMMEND_CF_SERVER}" \
      "${DATA}/recommend_dataset.csv" 127.0.0.1:63251 1 2 1 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 63251 "${LEAF_PID}"

    taskset -c 21 "${ASLR_PREFIX[@]}" "${MID_ENV[@]}" "${MID_BINARY}" \
      1 "${OUT}/leaf_ips.txt" 127.0.0.1:63250 \
      "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" \
      >"${OUT}/mid.log" 2>&1 &
    MID_PID="$!"
    start_pinner "${MID_PID}" "${MID_CORES}" mid
    wait_port 63250 "${MID_PID}"
    CLIENT_COMMAND=(
      "${RECOMMEND_LOADGEN}"
      "${DATA}/recommend_queries.txt" "${OUT}/result.txt" "${DURATION}"
      "${DEPTH}" 127.0.0.1:63250
    )
    ;;
  *)
    echo "unsupported benchmark: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

case "${PERF_TARGET_ROLE}" in
  mid)
    PERF_TARGET_PID="${MID_PID}"
    PERF_TARGET_ACTIVITY_PREFIX=mid
    ;;
  leaf)
    if [[ -n "${LEAF_PID}" ]]; then
      PERF_TARGET_PID="${LEAF_PID}"
    elif ((${#LEAF_PIDS[@]} == 1)); then
      PERF_TARGET_PID="${LEAF_PIDS[0]}"
    else
      echo "PERF_TARGET_ROLE=leaf requires exactly one leaf process" >&2
      exit 2
    fi
    PERF_TARGET_ACTIVITY_PREFIX=leaf_perf_target
    ;;
  *)
    echo "PERF_TARGET_ROLE must be mid or leaf" >&2
    exit 2
    ;;
esac
PERF_TARGET_BINARY="$(readlink -f "/proc/${PERF_TARGET_PID}/exe")"

sleep 2
if ((PREWARM_DURATION > 0)); then
  PREWARM_COMMAND=("${CLIENT_COMMAND[@]}")
  PREWARM_ENV=(env)
  replaced=0
  duration_index=-1
  for i in "${!PREWARM_COMMAND[@]}"; do
    if ((replaced == 0)) && [[ "${PREWARM_COMMAND[$i]}" == "${DURATION}" ]]; then
      PREWARM_COMMAND[$i]="${PREWARM_DURATION}"
      replaced=1
      duration_index="${i}"
    fi
  done
  ((replaced == 1)) || { echo 'could not set prewarm duration' >&2; exit 1; }
  PREWARM_COMMAND[$((duration_index + 1))]="${PREWARM_DEPTH}"
  if [[ "${BENCHMARK}" == router ]] && ((ROUTER_FIXED_PREWARM_REQUESTS > 0)); then
    PREWARM_ENV+=("PREFETCHIT_FIXED_REQUESTS=${ROUTER_FIXED_PREWARM_REQUESTS}")
    PREWARM_ENV+=("PREFETCHIT_FIXED_TIMEOUT_SECONDS=${ROUTER_FIXED_PREWARM_TIMEOUT}")
  fi
  taskset -c 56 "${ASLR_PREFIX[@]}" "${CLIENT_ENV[@]}" \
    "${PREWARM_ENV[@]}" "${PREWARM_COMMAND[@]}" \
    >"${OUT}/prewarm_loadgen.log" 2>&1 &
  CLIENT_PID="$!"
  start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" prewarm_client
  sleep 0.5
  fc_audit_pid_affinity "${CLIENT_PID}" "${CLIENT_CORES}" \
    "${OUT}/prewarm_client_affinity.csv"
  rg -q ',ok$' "${OUT}/prewarm_client_affinity.csv" || {
    echo "prewarm client exited before affinity audit" >&2
    exit 1
  }
  set +e
  wait "${CLIENT_PID}"
  prewarm_rc="$?"
  set -e
  CLIENT_PID=""
  if ((prewarm_rc != 0)); then
    echo "prewarm client failed: ${prewarm_rc}" >&2
    exit "${prewarm_rc}"
  fi
  sleep 2
fi

MEASURE_COMMAND=("${CLIENT_COMMAND[@]}")
if ((MEASURE_SETTLE_DURATION > 0)); then
  replaced=0
  for i in "${!MEASURE_COMMAND[@]}"; do
    if ((replaced == 0)) && [[ "${MEASURE_COMMAND[$i]}" == "${DURATION}" ]]; then
      MEASURE_COMMAND[$i]="$((DURATION + MEASURE_SETTLE_DURATION))"
      replaced=1
    fi
  done
  ((replaced == 1)) || { echo 'could not extend measurement duration' >&2; exit 1; }
fi

MEASURE_CLIENT_ENV=("${CLIENT_ENV[@]}")
if ((SYNC_MEASUREMENT_START == 1)); then
  rm -f "${OUT}/measurement.ready" "${OUT}/measurement.start" \
    "${OUT}/measurement.done" "${OUT}/record.ready"
  MEASURE_CLIENT_ENV+=(
    "PREFETCHIT_MEASUREMENT_READY_FILE=${OUT}/measurement.ready"
    "PREFETCHIT_MEASUREMENT_START_FILE=${OUT}/measurement.start"
    "PREFETCHIT_MEASUREMENT_DONE_FILE=${OUT}/measurement.done"
    "PREFETCHIT_EXIT_AFTER_FIXED_WORK=1"
  )
fi
taskset -c 56 "${ASLR_PREFIX[@]}" "${MEASURE_CLIENT_ENV[@]}" \
  "${MEASURE_COMMAND[@]}" >"${OUT}/loadgen.log" 2>&1 &
CLIENT_PID="$!"
start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" client

if ((SYNC_MEASUREMENT_START == 1)); then
  deadline=$((SECONDS + SYNC_MEASUREMENT_TIMEOUT))
  while [[ ! -s "${OUT}/measurement.ready" ]]; do
    kill -0 "${CLIENT_PID}" 2>/dev/null || {
      echo "client exited before measurement-ready handshake" >&2
      exit 1
    }
    ((SECONDS < deadline)) || {
      echo "measurement-ready handshake timed out" >&2
      exit 1
    }
    sleep 0.1
  done
else
  # Every upstream MicroSuite closed-loop client has an internal 20-second warmup.
  sleep "$((21 + MEASURE_SETTLE_DURATION))"
fi
audit_ok=1
fc_audit_pid_affinity "${MID_PID}" "${MID_CORES}" "${OUT}/mid_affinity_measure.csv" || audit_ok=0
if ((${#LEAF_PIDS[@]} > 0)); then
  for index in "${!LEAF_PIDS[@]}"; do
    fc_audit_pid_affinity "${LEAF_PIDS[$index]}" "${LEAF_CORE_RANGES[$index]}" \
      "${OUT}/leaf${index}_affinity_measure.csv" || audit_ok=0
  done
else
  fc_audit_pid_affinity "${LEAF_PID}" "${LEAF_CORES}" "${OUT}/leaf_affinity_measure.csv" || audit_ok=0
fi
[[ -z "${MEM_PID}" ]] || fc_audit_pid_affinity "${MEM_PID}" "${MEM_CORES}" "${OUT}/mem_affinity_measure.csv" || audit_ok=0
fc_audit_pid_affinity "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_affinity_measure.csv" || audit_ok=0
for pinner_log in "${OUT}"/*_pinner.log; do
  [[ -f "${pinner_log}" ]] || continue
  printf '[%(%F %T)T] MEASUREMENT_START\n' -1 >> "${pinner_log}"
done
python3 "${THREAD_SNAPSHOT}" "${MID_PID}" "${OUT}/mid_thread_activity_start.csv"
if [[ "${PERF_TARGET_ROLE}" != mid ]]; then
  python3 "${THREAD_SNAPSHOT}" "${PERF_TARGET_PID}" \
    "${OUT}/${PERF_TARGET_ACTIVITY_PREFIX}_thread_activity_start.csv"
fi

PERF_WINDOW=(sleep "${DURATION}")
RECORD_WINDOW=(sleep "${DURATION}")
if ((SYNC_MEASUREMENT_START == 1)); then
  record_ready=""
  if ((PROFILE_RECORD == 1)); then
    record_ready="${OUT}/record.ready"
  fi
  PERF_WINDOW=(bash -c '
    start_file="$1"
    done_file="$2"
    client_pid="$3"
    timeout_s="$4"
    record_ready="$5"
    deadline=$((SECONDS + timeout_s))
    while [[ -n "${record_ready}" && ! -e "${record_ready}" ]]; do
      kill -0 "${client_pid}" 2>/dev/null || exit 1
      ((SECONDS < deadline)) || exit 124
      sleep 0.01
    done
    : > "${start_file}"
    while [[ ! -s "${done_file}" ]]; do
      kill -0 "${client_pid}" 2>/dev/null || exit 1
      ((SECONDS < deadline)) || exit 124
      sleep 0.01
    done
  ' _ "${OUT}/measurement.start" "${OUT}/measurement.done" \
    "${CLIENT_PID}" "${SYNC_MEASUREMENT_TIMEOUT}" "${record_ready}")
  RECORD_WINDOW=(bash -c '
    ready_file="$1"
    start_file="$2"
    done_file="$3"
    client_pid="$4"
    timeout_s="$5"
    : > "${ready_file}"
    deadline=$((SECONDS + timeout_s))
    while [[ ! -e "${start_file}" ]]; do
      kill -0 "${client_pid}" 2>/dev/null || exit 1
      ((SECONDS < deadline)) || exit 124
      sleep 0.01
    done
    while [[ ! -s "${done_file}" ]]; do
      kill -0 "${client_pid}" 2>/dev/null || exit 1
      ((SECONDS < deadline)) || exit 124
      sleep 0.01
    done
  ' _ "${OUT}/record.ready" "${OUT}/measurement.start" \
    "${OUT}/measurement.done" "${CLIENT_PID}" "${SYNC_MEASUREMENT_TIMEOUT}")
fi

record_rc=0
if ((PROFILE_RECORD == 1)); then
  taskset -c "${CONTROL_CORE}" perf record -q \
    -e "${PROFILE_EVENT}" -b -c "${PROFILE_SAMPLE_PERIOD}" \
    -o "${OUT}/l2miss_profile.data" -p "${PERF_TARGET_PID}" -- "${RECORD_WINDOW[@]}" \
    >"${OUT}/record.out" 2>"${OUT}/record.err" &
  record_pid="$!"
  taskset -c "${CONTROL_CORE}" perf stat -x, -o "${OUT}/perf.csv" \
    -e context-switches,cpu-migrations -p "${PERF_TARGET_PID}" -- "${PERF_WINDOW[@]}"
  set +e
  wait "${record_pid}"
  record_rc="$?"
  set -e
else
  taskset -c "${CONTROL_CORE}" perf stat -x, -o "${OUT}/perf.csv" \
    -e instructions,cycles,"${EVENT}",context-switches,cpu-migrations \
    -p "${PERF_TARGET_PID}" -- "${PERF_WINDOW[@]}"
fi
python3 "${THREAD_SNAPSHOT}" "${MID_PID}" "${OUT}/mid_thread_activity_end.csv"
if [[ "${PERF_TARGET_ROLE}" != mid ]]; then
  python3 "${THREAD_SNAPSHOT}" "${PERF_TARGET_PID}" \
    "${OUT}/${PERF_TARGET_ACTIVITY_PREFIX}_thread_activity_end.csv"
fi

set +e
wait "${CLIENT_PID}"
client_rc="$?"
set -e
CLIENT_PID=""
fc_audit_pid_affinity "${MID_PID}" "${MID_CORES}" "${OUT}/mid_affinity_end.csv" || audit_ok=0
if rg -q 'ERROR' "${OUT}"/*_pinner.log; then audit_ok=0; fi
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_end.csv" || audit_ok=0

python3 - "${OUT}" "${BENCHMARK}" "${LABEL}" "${MID_BINARY}" "${DURATION}" "${DEPTH}" \
  "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" "${PREWARM_DURATION}" "${PREWARM_DEPTH}" \
  "${MEASURE_SETTLE_DURATION}" "${GRPC_CORE_CAP}" "${PROFILE_RECORD}" "${PROFILE_SAMPLE_PERIOD}" "${record_rc}" \
  "${DISABLE_ASLR}" "${ROUTER_PREPOPULATE}" "${ROUTER_LEAF_INSTANCES}" \
  "${ROUTER_FIXED_PREWARM_REQUESTS}" \
  "${ROUTER_FIXED_PREWARM_TIMEOUT}" \
  "${EVICT_CACHES}" "${EVICT_BYTES_PER_CORE}" "${EVICT_PASSES}" \
  "${client_rc}" "${audit_ok}" "${PERF_TARGET_ROLE}" \
  "${PERF_TARGET_BINARY}" "${GRPC_POLL_STRATEGY:-default}" <<'PY'
import csv
import json
import math
import pathlib
import re
import sys

(out, benchmark, label, binary, duration, depth, parallelism, dispatch,
 responses_cfg, prewarm_duration, prewarm_depth, measure_settle_duration,
 grpc_core_cap, profile_record,
 profile_sample_period, record_rc, disable_aslr, router_prepopulate,
 router_leaf_instances, router_fixed_prewarm_requests, router_fixed_prewarm_timeout,
 evict_caches, evict_bytes_per_core, evict_passes,
 client_rc, audit_ok, perf_target_role, perf_target_binary,
 grpc_poll_strategy) = sys.argv[1:]
root = pathlib.Path(out)
text = (root / "loadgen.log").read_text(errors="replace")
numbers = [
    float(line.strip())
    for line in text.splitlines()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", line.strip())
]
responses = numbers[0] if numbers else math.nan
qps = numbers[1] if len(numbers) > 1 else math.nan
failed_match = re.search(r"failed_responses=(\d+)", text)
failed = int(failed_match.group(1)) if failed_match else 0
fixed_requests_match = re.search(r"prefetchit_fixed_requests=(\d+)", text)
fixed_warmup_match = re.search(r"prefetchit_fixed_warmup_requests=(\d+)", text)
fixed_runtime_match = re.search(r"prefetchit_fixed_runtime_us=(\d+)", text)
fixed_qps_match = re.search(r"prefetchit_fixed_qps=([0-9.]+)", text)
fixed_overrun_match = re.search(r"prefetchit_fixed_window_overrun=(\d+)", text)
fixed_requests = int(fixed_requests_match.group(1)) if fixed_requests_match else 0
fixed_warmup_requests = int(fixed_warmup_match.group(1)) if fixed_warmup_match else 0
fixed_runtime_us = int(fixed_runtime_match.group(1)) if fixed_runtime_match else 0
fixed_qps = float(fixed_qps_match.group(1)) if fixed_qps_match else 0.0
fixed_window_overrun = int(fixed_overrun_match.group(1)) if fixed_overrun_match else 0

events = {}
with (root / "perf.csv").open(newline="") as handle:
    for row in csv.reader(handle):
        if len(row) < 3 or row[0].lstrip().startswith("<"):
            continue
        try:
            events[row[2].strip()] = float(row[0].replace(",", ""))
        except ValueError:
            pass
instructions = events.get("instructions", 0.0)
cycles = events.get("cycles", 0.0)
misses = events.get("L2I_CODE_RD_MISS", 0.0)
migrations = events.get("cpu-migrations", -1.0)
pinner_errors = sum(
    path.read_text(errors="replace").count("ERROR")
    for path in root.glob("*_pinner.log")
)
def correction_counts(path):
    text = path.read_text(errors="replace")
    total = text.count("CORRECT repin")
    marker = text.rfind("MEASUREMENT_START")
    runtime = text[marker:].count("CORRECT repin") if marker >= 0 else total
    return total, runtime

correction_pairs = [correction_counts(path) for path in root.glob("*_pinner.log")]
pinner_corrections_total = sum(pair[0] for pair in correction_pairs)
pinner_corrections = sum(pair[1] for pair in correction_pairs)

def tids(path):
    with path.open(newline="") as handle:
        return sum(row.get("status") == "ok" for row in csv.DictReader(handle))

def thread_activity(prefix):
    start_path = root / f"{prefix}_thread_activity_start.csv"
    end_path = root / f"{prefix}_thread_activity_end.csv"
    if not start_path.exists() or not end_path.exists():
        return 0, 0.0, 0.0
    with start_path.open(newline="") as handle:
        start = {row["tid"]: row for row in csv.DictReader(handle)}
    with end_path.open(newline="") as handle:
        end = {row["tid"]: row for row in csv.DictReader(handle)}
    activity = []
    for tid in sorted(start.keys() & end.keys(), key=int):
        before = start[tid]
        after = end[tid]
        runtime_ns = int(after["runtime_ns"]) - int(before["runtime_ns"])
        activity.append(
            {
                "tid": int(tid),
                "comm": after["comm"],
                "processor": int(after["processor"]),
                "allowed_list": after["allowed_list"],
                "runtime_ns": runtime_ns,
                "runqueue_wait_ns": int(after["runqueue_wait_ns"])
                - int(before["runqueue_wait_ns"]),
                "timeslices": int(after["timeslices"]) - int(before["timeslices"]),
                "voluntary_context_switches": int(
                    after["voluntary_context_switches"]
                ) - int(before["voluntary_context_switches"]),
                "nonvoluntary_context_switches": int(
                    after["nonvoluntary_context_switches"]
                ) - int(before["nonvoluntary_context_switches"]),
            }
        )
    if activity:
        with (root / f"{prefix}_thread_activity.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=activity[0])
            writer.writeheader()
            writer.writerows(activity)
    active = [entry for entry in activity if entry["runtime_ns"] > 0]
    total_runtime = sum(entry["runtime_ns"] for entry in active)
    shares = [entry["runtime_ns"] / total_runtime for entry in active] if total_runtime else []
    return (
        len(active),
        max(shares, default=0.0),
        sum(share * share for share in shares),
    )

mid_active_tids, mid_max_thread_cpu_share, mid_thread_cpu_share_hhi = thread_activity("mid")
perf_activity_prefix = "mid" if perf_target_role == "mid" else "leaf_perf_target"
(perf_target_active_tids, perf_target_max_thread_cpu_share,
 perf_target_thread_cpu_share_hhi) = thread_activity(perf_activity_prefix)

row = {
    "benchmark": benchmark,
    "label": label,
    "binary": binary,
    "perf_target_role": perf_target_role,
    "perf_target_binary": perf_target_binary,
    "grpc_poll_strategy": grpc_poll_strategy,
    "duration_s": int(duration),
    "prewarm_duration_s": int(prewarm_duration),
    "prewarm_depth": int(prewarm_depth),
    "measure_settle_duration_s": int(measure_settle_duration),
    "grpc_core_cap": int(grpc_core_cap),
    "profile_record": int(profile_record),
    "profile_sample_period": int(profile_sample_period),
    "disable_aslr": int(disable_aslr),
    "router_prepopulate": int(router_prepopulate),
    "router_leaf_instances": int(router_leaf_instances),
    "router_fixed_prewarm_requests": int(router_fixed_prewarm_requests),
    "router_fixed_prewarm_timeout_s": int(router_fixed_prewarm_timeout),
    "evict_caches": int(evict_caches),
    "evict_bytes_per_core": int(evict_bytes_per_core),
    "evict_passes": int(evict_passes),
    "record_rc": int(record_rc),
    "depth": int(depth),
    "parallelism": int(parallelism),
    "dispatch": int(dispatch),
    "response_threads": int(responses_cfg),
    "responses": responses,
    "qps": qps,
    "fixed_requests": fixed_requests,
    "fixed_warmup_requests": fixed_warmup_requests,
    "fixed_runtime_us": fixed_runtime_us,
    "fixed_qps": fixed_qps,
    "fixed_window_overrun": fixed_window_overrun,
    "failed_responses": failed,
    "instructions": int(instructions),
    "cycles": int(cycles),
    "l2i_misses": int(misses),
    "l2i_mpki": misses / instructions * 1000 if instructions else 0,
    "ipc": instructions / cycles if cycles else 0,
    "context_switches": int(events.get("context-switches", -1)),
    "cpu_migrations": int(migrations),
    "migration_policy": "allow-pthread-creation-placement; reject-runtime-repin",
    "mid_tids": tids(root / "mid_affinity_measure.csv"),
    "mid_active_tids": mid_active_tids,
    "mid_max_thread_cpu_share": mid_max_thread_cpu_share,
    "mid_thread_cpu_share_hhi": mid_thread_cpu_share_hhi,
    "perf_target_active_tids": perf_target_active_tids,
    "perf_target_max_thread_cpu_share": perf_target_max_thread_cpu_share,
    "perf_target_thread_cpu_share_hhi": perf_target_thread_cpu_share_hhi,
    "leaf_tids": sum(tids(path) for path in root.glob("leaf*_affinity_measure.csv")),
    "client_tids": tids(root / "client_affinity_measure.csv"),
    "client_rc": int(client_rc),
    "audit_ok": int(audit_ok),
    "pinner_errors": pinner_errors,
    "pinner_corrections_total": pinner_corrections_total,
    "pinner_corrections": pinner_corrections,
    "valid": int(
        int(client_rc) == 0
        and int(record_rc) == 0
        and int(audit_ok) == 1
        and math.isfinite(qps)
        and qps > 0
        and fixed_window_overrun == 0
        and failed == 0
        and int(migrations) == 0
        and pinner_errors == 0
        and pinner_corrections == 0
        and (
            int(profile_record) == 0
            or (root / "l2miss_profile.data").stat().st_size > 0
        )
    ),
}
with (root / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=row)
    writer.writeheader()
    writer.writerow(row)
(root / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
print(json.dumps(row, sort_keys=True))
raise SystemExit(0 if row["valid"] else 1)
PY
