#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 ]]; then
  echo "usage: $0 LABEL MEMCACHED_BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
MEMTIER="${ROOT}/benchmarks/dcperf/benchmarks/tao_bench/memtier_client/memtier_benchmark"
PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
LABEL="$1"
BINARY="$(readlink -f "$2")"
OUT="$(readlink -m "$3")"
DURATION="${DURATION:-60}"
WARMUP_DURATION="${WARMUP_DURATION:-20}"
PORT="${PORT:-11262}"
CONNECTIONS_PER_THREAD="${CONNECTIONS_PER_THREAD:-256}"
CLIENT_THREADS="${CLIENT_THREADS:-8}"
SERVICE_THREADS="${SERVICE_THREADS:-8}"
KEY_MAX="${KEY_MAX:-100000}"
PROTOCOL="${PROTOCOL:-memcache_text}"
PIPELINE="${PIPELINE:-1}"
DATA_SIZE="${DATA_SIZE:-64}"
READ_WRITE_RATIO="${READ_WRITE_RATIO:-0:1}"
KEY_PATTERN="${KEY_PATTERN:-R:R}"
HASHPOWER="${HASHPOWER:-0}"
NO_HASH_EXPAND="${NO_HASH_EXPAND:-0}"
PROFILE_RECORD="${PROFILE_RECORD:-0}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-10000}"
SERVICE_CORES="1-24"
CLIENT_CORES="25-40"
ALL_CORES="0-40"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
PROFILE_EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

# shellcheck source=/dev/null
source "${COMMON}"

SERVICE_PID=""
CLIENT_PID=""
PINNERS=()

cleanup() {
  set +e
  for pid in "${CLIENT_PID}" "${SERVICE_PID}"; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" >/dev/null 2>&1 || true
    for _ in {1..100}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.05
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" >/dev/null 2>&1 || true
    fi
    wait "${pid}" >/dev/null 2>&1 || true
  done
  for pid in "${PINNERS[@]}"; do
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

start_pinner() {
  fc_start_pinner "$1" "$2" "$3"
  PINNERS+=("${FC_PINNER_PID}")
}

wait_port() {
  local deadline=$((SECONDS + 30))
  while ((SECONDS < deadline)); do
    nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

for _ in {1..100}; do
  if ! nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.05
done
if nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
  echo "port ${PORT} is still occupied" >&2
  exit 1
fi

mkdir -p "${OUT}"
rm -f "${OUT}"/*.log "${OUT}"/*.csv "${OUT}"/*.json
[[ -x "${BINARY}" && -x "${MEMTIER}" && -f "${PIN_SO}" ]]
ulimit -n 65536
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_start.csv"

extended_options=(no_lru_crawler no_lru_maintainer)
if ((HASHPOWER > 0)); then extended_options+=("hashpower=${HASHPOWER}"); fi
if ((NO_HASH_EXPAND == 1)); then extended_options+=(no_hashexpand); fi
extended_csv="$(IFS=,; printf '%s' "${extended_options[*]}")"
taskset -c 1 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=2-24 \
  "${BINARY}" -p "${PORT}" -U 0 -t "${SERVICE_THREADS}" -m 4096 -c 4096 \
  -o "${extended_csv}" > "${OUT}/server.log" 2>&1 &
SERVICE_PID="$!"
start_pinner "${SERVICE_PID}" "${SERVICE_CORES}" "${OUT}/service_pinner.log"
wait_port

MEMTIER_BASE=(
  "${MEMTIER}" --server=127.0.0.1 --port="${PORT}"
  --protocol="${PROTOCOL}" --threads="${CLIENT_THREADS}"
  --clients="${CONNECTIONS_PER_THREAD}" --pipeline="${PIPELINE}"
  --data-size="${DATA_SIZE}" --key-minimum=1 --key-maximum="${KEY_MAX}" --hide-histogram
)

taskset -c 25 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=26-40 \
  "${MEMTIER}" --server=127.0.0.1 --port="${PORT}" \
  --protocol=memcache_text --threads=1 --clients=1 --pipeline=32 \
  --data-size="${DATA_SIZE}" --key-minimum=1 --key-maximum="${KEY_MAX}" \
  --ratio=1:0 --requests="${KEY_MAX}" --key-pattern=S:S \
  --hide-histogram \
  > "${OUT}/prefill.log" 2>&1

taskset -c 25 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=26-40 \
  "${MEMTIER_BASE[@]}" --ratio="${READ_WRITE_RATIO}" \
  --test-time="${WARMUP_DURATION}" --key-pattern="${KEY_PATTERN}" \
  > "${OUT}/warmup.log" 2>&1

taskset -c 25 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=26-40 \
  "${MEMTIER_BASE[@]}" --ratio="${READ_WRITE_RATIO}" --test-time="$((DURATION + 3))" \
  --key-pattern="${KEY_PATTERN}" --json-out-file="${OUT}/memtier.json" \
  > "${OUT}/client.log" 2>&1 &
CLIENT_PID="$!"
start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_pinner.log"
sleep 3

audit_ok=1
fc_audit_pid_affinity "${SERVICE_PID}" "${SERVICE_CORES}" "${OUT}/service_affinity.csv" || audit_ok=0
fc_audit_pid_affinity "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_affinity.csv" || audit_ok=0
for pinner_log in "${OUT}"/*_pinner.log; do
  [[ -f "${pinner_log}" ]] || continue
  printf '[%(%F %T)T] MEASUREMENT_START\n' -1 >> "${pinner_log}"
done

record_rc=0
if ((PROFILE_RECORD == 1)); then
  taskset -c 0 perf record -q -e "${PROFILE_EVENT}" -b \
    -c "${PROFILE_SAMPLE_PERIOD}" -o "${OUT}/l2miss_profile.data" \
    -p "${SERVICE_PID}" -- sleep "${DURATION}" \
    > "${OUT}/record.out" 2> "${OUT}/record.err" &
  record_pid="$!"
  taskset -c 0 perf stat -x, -o "${OUT}/perf.csv" \
    -e context-switches,cpu-migrations -p "${SERVICE_PID}" -- sleep "${DURATION}"
  set +e
  wait "${record_pid}"
  record_rc="$?"
  set -e
else
  taskset -c 0 perf stat -x, -o "${OUT}/perf.csv" \
    -e instructions,cycles,"${EVENT}",context-switches,cpu-migrations \
    -p "${SERVICE_PID}" -- sleep "${DURATION}"
fi

wait "${CLIENT_PID}"
client_rc="$?"
CLIENT_PID=""
fc_audit_pid_affinity "${SERVICE_PID}" "${SERVICE_CORES}" "${OUT}/service_affinity_end.csv" || audit_ok=0
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_end.csv" || audit_ok=0
if rg -q 'ERROR' "${OUT}"/*_pinner.log; then audit_ok=0; fi

python3 - "${OUT}" "${LABEL}" "${BINARY}" "${DURATION}" "${client_rc}" "${audit_ok}" \
  "${SERVICE_THREADS}" "${CLIENT_THREADS}" "$((CLIENT_THREADS * CONNECTIONS_PER_THREAD))" \
  "${PROTOCOL}" "${PIPELINE}" "${DATA_SIZE}" "${READ_WRITE_RATIO}" \
  "${KEY_PATTERN}" "${HASHPOWER}" "${NO_HASH_EXPAND}" \
  "${PROFILE_RECORD}" "${PROFILE_SAMPLE_PERIOD}" "${record_rc}" <<'PY'
import csv
import json
import sys
from pathlib import Path

(out, label, binary, duration, client_rc, audit_ok, service_threads,
 client_threads, connections, protocol, pipeline, data_size, ratio,
 key_pattern, hashpower, no_hash_expand, profile_record,
 profile_sample_period, record_rc) = sys.argv[1:]
out = Path(out)
events = {}
with (out / "perf.csv").open() as handle:
    for row in csv.reader(handle):
        if len(row) >= 3:
            try:
                events[row[2]] = float(row[0])
            except ValueError:
                pass
payload = json.loads((out / "memtier.json").read_text())

stats = payload.get("ALL STATS", {})
totals = stats.get("Totals", {})
qps = float(totals.get("Ops/sec", 0.0))
hits = float(totals.get("Hits/sec", 0.0))
misses_per_sec = float(totals.get("Misses/sec", 0.0))
instructions = events.get("instructions", 0.0)
misses = events.get("L2I_CODE_RD_MISS", 0.0)
cycles = events.get("cycles", 0.0)
migrations = int(events.get("cpu-migrations", 0.0))
text = (out / "client.log").read_text(errors="replace").lower()
failed = int("error" in text or "failed" in text)
def correction_counts(path):
    text = path.read_text(errors="replace")
    total = text.count("CORRECT repin")
    marker = text.rfind("MEASUREMENT_START")
    runtime = text[marker:].count("CORRECT repin") if marker >= 0 else total
    return total, runtime
corrections = [correction_counts(path) for path in out.glob("*_pinner.log")]
pinner_corrections_total = sum(pair[0] for pair in corrections)
pinner_corrections = sum(pair[1] for pair in corrections)
profile_data = out / "l2miss_profile.data"
profile_ok = int(profile_record) == 0 or (
    int(record_rc) == 0 and profile_data.is_file() and profile_data.stat().st_size > 0
)
valid = int(int(client_rc) == 0 and int(audit_ok) == 1 and failed == 0 and
            qps > 0 and pinner_corrections == 0 and profile_ok)
result = {
    "benchmark": "memcached", "label": label, "binary": binary,
    "duration_s": int(duration), "service_threads_configured": int(service_threads),
    "client_threads": int(client_threads), "connections": int(connections),
    "protocol": protocol, "pipeline": int(pipeline), "data_size": int(data_size),
    "read_write_ratio": ratio, "key_pattern": key_pattern,
    "hashpower": int(hashpower), "no_hash_expand": int(no_hash_expand),
    "profile_record": int(profile_record),
    "profile_sample_period": int(profile_sample_period),
    "record_rc": int(record_rc),
    "qps": qps, "hits_per_sec": hits, "misses_per_sec": misses_per_sec,
    "hit_rate": hits / (hits + misses_per_sec) if hits + misses_per_sec else 0.0,
    "instructions": instructions, "cycles": cycles,
    "l2i_misses": misses, "l2i_mpki": 1000.0 * misses / instructions if instructions else 0.0,
    "ipc": instructions / cycles if cycles else 0.0,
    "context_switches": int(events.get("context-switches", 0.0)),
    "cpu_migrations": migrations, "client_rc": int(client_rc),
    "migration_policy": "allow-pthread-creation-placement; reject-runtime-repin",
    "pinner_corrections_total": pinner_corrections_total,
    "pinner_corrections": pinner_corrections,
    "audit_ok": int(audit_ok), "failed": failed, "valid": valid,
}
(out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
with (out / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=result)
    writer.writeheader()
    writer.writerow(result)
print(json.dumps(result, sort_keys=True))
PY

[[ "$(jq -r '.valid' "${OUT}/summary.json")" == 1 ]]
