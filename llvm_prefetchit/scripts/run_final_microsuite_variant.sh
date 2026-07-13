#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 ]]; then
  echo "usage: $0 BENCHMARK LABEL MID_TIER_BINARY [OUT_DIR]" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
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
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
PROFILE_EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'
GRPC_CORE_CAP_SO="${ROOT}/llvm_prefetchit/tools/grpc_core_cap.so"
THREAD_PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"

# shellcheck source=/dev/null
source "${COMMON}"
export LD_LIBRARY_PATH="${DEPROOT}/usr/lib:${DEPROOT}/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

MEM_PID=""
LEAF_PID=""
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

case "${BENCHMARK}" in
  router)
    printf '127.0.0.1:61251\n' > "${OUT}/leaf_ips.txt"
    taskset -c 1 "${MEM_ENV[@]}" memcached -p 61211 -u "${USER}" -t 2 -m 256 >"${OUT}/memcached.log" 2>&1 &
    MEM_PID="$!"
    start_pinner "${MEM_PID}" "${MEM_CORES}" memcached

    taskset -c 9 "${LEAF_ENV[@]}" \
      "${SRC}/Router/lookup_service/service/lookup_server" \
      127.0.0.1:61251 61211 2 1 >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 61251 "${LEAF_PID}"

    taskset -c 21 "${MID_ENV[@]}" "${MID_BINARY}" \
      1 "${OUT}/leaf_ips.txt" 127.0.0.1:61250 \
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
    taskset -c 9 "${LEAF_ENV[@]}" \
      "${SRC}/SetAlgebra/intersection_service/service/intersection_server" \
      127.0.0.1:62251 "${DATA}/set_dataset.txt" 2 1 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 62251 "${LEAF_PID}"

    taskset -c 21 "${MID_ENV[@]}" "${MID_BINARY}" \
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
    taskset -c 9 "${LEAF_ENV[@]}" \
      "${SRC}/HDSearch/bucket_service/service/bucket_server" \
      "${HD_DATA}/dataset.bin" 127.0.0.1:64251 2 1 0 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 64251 "${LEAF_PID}"

    taskset -c 21 "${MID_ENV[@]}" "${MID_BINARY}" \
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
    printf '127.0.0.1:63251\n' > "${OUT}/leaf_ips.txt"
    taskset -c 9 "${LEAF_ENV[@]}" \
      "${SRC}/Recommend/cf_service/service/cf_server" \
      "${DATA}/recommend_dataset.csv" 127.0.0.1:63251 1 2 1 1 \
      >"${OUT}/leaf.log" 2>&1 &
    LEAF_PID="$!"
    start_pinner "${LEAF_PID}" "${LEAF_CORES}" leaf
    wait_port 63251 "${LEAF_PID}"

    taskset -c 21 "${MID_ENV[@]}" "${MID_BINARY}" \
      1 "${OUT}/leaf_ips.txt" 127.0.0.1:63250 \
      "${PARALLELISM}" "${DISPATCH}" "${RESPONSES}" \
      >"${OUT}/mid.log" 2>&1 &
    MID_PID="$!"
    start_pinner "${MID_PID}" "${MID_CORES}" mid
    wait_port 63250 "${MID_PID}"
    CLIENT_COMMAND=(
      "${SRC}/Recommend/load_generator/load_generator_closed_loop"
      "${DATA}/recommend_queries.txt" "${OUT}/result.txt" "${DURATION}"
      "${DEPTH}" 127.0.0.1:63250
    )
    ;;
  *)
    echo "unsupported benchmark: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

sleep 2
if ((PREWARM_DURATION > 0)); then
  PREWARM_COMMAND=("${CLIENT_COMMAND[@]}")
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
  taskset -c 56 "${CLIENT_ENV[@]}" "${PREWARM_COMMAND[@]}" >"${OUT}/prewarm_loadgen.log" 2>&1 &
  CLIENT_PID="$!"
  start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" prewarm_client
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

taskset -c 56 "${CLIENT_ENV[@]}" "${MEASURE_COMMAND[@]}" >"${OUT}/loadgen.log" 2>&1 &
CLIENT_PID="$!"
start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" client

# Every MicroSuite closed-loop client has an internal 20-second warmup.
sleep "$((21 + MEASURE_SETTLE_DURATION))"
audit_ok=1
fc_audit_pid_affinity "${MID_PID}" "${MID_CORES}" "${OUT}/mid_affinity_measure.csv" || audit_ok=0
fc_audit_pid_affinity "${LEAF_PID}" "${LEAF_CORES}" "${OUT}/leaf_affinity_measure.csv" || audit_ok=0
[[ -z "${MEM_PID}" ]] || fc_audit_pid_affinity "${MEM_PID}" "${MEM_CORES}" "${OUT}/mem_affinity_measure.csv" || audit_ok=0
fc_audit_pid_affinity "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_affinity_measure.csv" || audit_ok=0
for pinner_log in "${OUT}"/*_pinner.log; do
  [[ -f "${pinner_log}" ]] || continue
  printf '[%(%F %T)T] MEASUREMENT_START\n' -1 >> "${pinner_log}"
done

record_rc=0
if ((PROFILE_RECORD == 1)); then
  taskset -c "${CONTROL_CORE}" perf record -q \
    -e "${PROFILE_EVENT}" -b -c "${PROFILE_SAMPLE_PERIOD}" \
    -o "${OUT}/l2miss_profile.data" -p "${MID_PID}" -- sleep "${DURATION}" \
    >"${OUT}/record.out" 2>"${OUT}/record.err" &
  record_pid="$!"
  taskset -c "${CONTROL_CORE}" perf stat -x, -o "${OUT}/perf.csv" \
    -e context-switches,cpu-migrations -p "${MID_PID}" -- sleep "${DURATION}"
  set +e
  wait "${record_pid}"
  record_rc="$?"
  set -e
else
  taskset -c "${CONTROL_CORE}" perf stat -x, -o "${OUT}/perf.csv" \
    -e instructions,cycles,"${EVENT}",context-switches,cpu-migrations \
    -p "${MID_PID}" -- sleep "${DURATION}"
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
  "${client_rc}" "${audit_ok}" <<'PY'
import csv
import json
import math
import pathlib
import re
import sys

(out, benchmark, label, binary, duration, depth, parallelism, dispatch,
 responses_cfg, prewarm_duration, prewarm_depth, measure_settle_duration,
 grpc_core_cap, profile_record,
 profile_sample_period, record_rc, client_rc, audit_ok) = sys.argv[1:]
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

row = {
    "benchmark": benchmark,
    "label": label,
    "binary": binary,
    "duration_s": int(duration),
    "prewarm_duration_s": int(prewarm_duration),
    "prewarm_depth": int(prewarm_depth),
    "measure_settle_duration_s": int(measure_settle_duration),
    "grpc_core_cap": int(grpc_core_cap),
    "profile_record": int(profile_record),
    "profile_sample_period": int(profile_sample_period),
    "record_rc": int(record_rc),
    "depth": int(depth),
    "parallelism": int(parallelism),
    "dispatch": int(dispatch),
    "response_threads": int(responses_cfg),
    "responses": responses,
    "qps": qps,
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
    "leaf_tids": tids(root / "leaf_affinity_measure.csv"),
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
        and failed == 0
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
PY
