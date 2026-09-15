#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 ]]; then
  echo "usage: $0 LABEL POSTGRES_BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
DATA_TEMPLATE="${POSTGRES_DATA_TEMPLATE:-${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/postgres/data_base}"
PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
LABEL="$1"
POSTGRES="$(readlink -f "$2")"
PREFIX="$(dirname "$(dirname "${POSTGRES}")")"
PGBENCH="${PREFIX}/bin/pgbench"
PG_ISREADY="${PREFIX}/bin/pg_isready"
OUT="$(readlink -m "$3")"
DURATION="${DURATION:-60}"
WARMUP_DURATION="${WARMUP_DURATION:-20}"
PORT="${PORT:-55433}"
SOCKET_DIR="${SOCKET_DIR:-/tmp/prefetchit_pg_${PORT}_$$}"
RUN_DATA="${POSTGRES_RUN_DATA:-/tmp/prefetchit_pgdata_${PORT}_$$}"
CLIENTS="${CLIENTS:-8}"
CLIENT_THREADS="${CLIENT_THREADS:-${CLIENTS}}"
QUERY_MODE="${QUERY_MODE:-prepared}"
PGBENCH_BUILTIN="${PGBENCH_BUILTIN:-tpcb-like}"
PGBENCH_SCRIPT="${PGBENCH_SCRIPT:-}"
PGBENCH_TRANSACTIONS="${PGBENCH_TRANSACTIONS:-0}"
PGBENCH_WARMUP_SEED="${PGBENCH_WARMUP_SEED:-2026071301}"
PGBENCH_SEED="${PGBENCH_SEED:-2026071302}"
PROFILE_RECORD="${PROFILE_RECORD:-0}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-10000}"
SERVER_CORES="1-30"
CLIENT_CORES="31-70"
ALL_CORES="0-70"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
PROFILE_EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

# shellcheck source=/dev/null
source "${COMMON}"

SERVER_PID=""
CLIENT_PID=""
PINNERS=()

cleanup() {
  set +e
  [[ -z "${CLIENT_PID}" ]] || kill "${CLIENT_PID}" >/dev/null 2>&1 || true
  if [[ -n "${SERVER_PID}" ]]; then
    kill -INT "${SERVER_PID}" >/dev/null 2>&1 || true
    for _ in {1..100}; do
      kill -0 "${SERVER_PID}" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
  for pid in "${PINNERS[@]}"; do
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
  done
  rm -rf "${SOCKET_DIR}" "${RUN_DATA}"
}
trap cleanup EXIT INT TERM

mkdir -p "${OUT}" "${SOCKET_DIR}"
rm -f "${OUT}"/*.log "${OUT}"/*.csv "${OUT}"/*.json "${SOCKET_DIR}"/.s.PGSQL.*
[[ -x "${POSTGRES}" && -x "${PGBENCH}" && -x "${PG_ISREADY}" && -f "${PIN_SO}" ]]
[[ -d "${DATA_TEMPLATE}" && ! -e "${DATA_TEMPLATE}/postmaster.pid" ]]
[[ ! -e "${RUN_DATA}" ]]
mkdir -p "${RUN_DATA}"
cp -a --reflink=auto "${DATA_TEMPLATE}/." "${RUN_DATA}/"
chmod 700 "${RUN_DATA}"
DATA="${RUN_DATA}"
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_start.csv"

workload_args=(-b "${PGBENCH_BUILTIN}")
if [[ -n "${PGBENCH_SCRIPT}" ]]; then
  PGBENCH_SCRIPT="$(readlink -f "${PGBENCH_SCRIPT}")"
  [[ -s "${PGBENCH_SCRIPT}" ]]
  workload_args=(-f "${PGBENCH_SCRIPT}")
fi
roi_limit_args=(-T "$((DURATION + 8))")
if ((PGBENCH_TRANSACTIONS > 0)); then
  roi_limit_args=(-t "${PGBENCH_TRANSACTIONS}")
fi

taskset -c 1 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=2-30 \
  LD_LIBRARY_PATH="${PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  "${POSTGRES}" -D "${DATA}" -p "${PORT}" -k "${SOCKET_DIR}" \
  -c autovacuum=off -c checkpoint_timeout=1h -c max_wal_size=10GB \
  -c bgwriter_lru_maxpages=0 \
  > "${OUT}/postgres.log" 2>&1 &
SERVER_PID="$!"
fc_start_tree_pinner "${SERVER_PID}" "${SERVER_CORES}" "${OUT}/server_pinner.log"
PINNERS+=("${FC_PINNER_PID}")

for _ in {1..300}; do
  "${PG_ISREADY}" -h "${SOCKET_DIR}" -p "${PORT}" >/dev/null 2>&1 && break
  sleep 0.1
done
"${PG_ISREADY}" -h "${SOCKET_DIR}" -p "${PORT}" >/dev/null

taskset -c 31 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=32-70 \
  "${PGBENCH}" -h "${SOCKET_DIR}" -p "${PORT}" -c "${CLIENTS}" -j "${CLIENT_THREADS}" \
  -n "${workload_args[@]}" \
  -T "${WARMUP_DURATION}" -M "${QUERY_MODE}" --random-seed="${PGBENCH_WARMUP_SEED}" \
  postgres > "${OUT}/warmup.log" 2>&1

taskset -c 31 env LD_PRELOAD="${PIN_SO}" PREFETCHIT_THREAD_PIN_CORES=32-70 \
  "${PGBENCH}" -h "${SOCKET_DIR}" -p "${PORT}" -c "${CLIENTS}" -j "${CLIENT_THREADS}" \
  -n "${workload_args[@]}" \
  "${roi_limit_args[@]}" -M "${QUERY_MODE}" --random-seed="${PGBENCH_SEED}" \
  postgres > "${OUT}/pgbench.log" 2>&1 &
CLIENT_PID="$!"
fc_start_pinner "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_pinner.log"
PINNERS+=("${FC_PINNER_PID}")
sleep 3

audit_ok=1
fc_audit_tree_affinity "${SERVER_PID}" "${SERVER_CORES}" "${OUT}/server_affinity.csv" || audit_ok=0
fc_audit_pid_affinity "${CLIENT_PID}" "${CLIENT_CORES}" "${OUT}/client_affinity.csv" || audit_ok=0
ps -o pid=,args= --ppid "${SERVER_PID}" > "${OUT}/server_processes.txt"
mapfile -t backend_pids < <(awk '/\[local\]/ {print $1}' "${OUT}/server_processes.txt")
if ((${#backend_pids[@]} != CLIENTS)); then
  mapfile -t backend_pids < <(awk '{print $1}' "${OUT}/server_processes.txt" | sort -n | tail -"${CLIENTS}")
fi
if ((${#backend_pids[@]} != CLIENTS)); then
  echo "expected ${CLIENTS} PostgreSQL client backends, found ${#backend_pids[@]}" >&2
  exit 1
fi
printf '%s\n' "${backend_pids[@]}" > "${OUT}/measured_backend_pids.txt"
pid_list="$(printf '%s\n' "${backend_pids[@]}" | paste -sd, -)"
for pinner_log in "${OUT}"/*_pinner.log; do
  [[ -f "${pinner_log}" ]] || continue
  printf '[%(%F %T)T] MEASUREMENT_START\n' -1 >> "${pinner_log}"
done

record_rc=0
if ((PROFILE_RECORD == 1)); then
  taskset -c 0 perf record -q -e "${PROFILE_EVENT}" -b \
    -c "${PROFILE_SAMPLE_PERIOD}" -o "${OUT}/l2miss_profile.data" \
    -p "${pid_list}" -- sleep "${DURATION}" \
    > "${OUT}/record.out" 2> "${OUT}/record.err" &
  record_pid="$!"
  taskset -c 0 perf stat --per-thread -x, -o "${OUT}/perf.csv" \
    -e context-switches,cpu-migrations -p "${pid_list}" -- sleep "${DURATION}"
  set +e
  wait "${record_pid}"
  record_rc="$?"
  set -e
else
  taskset -c 0 perf stat --per-thread -x, -o "${OUT}/perf.csv" \
    -e instructions,cycles,"${EVENT}",context-switches,cpu-migrations \
    -p "${pid_list}" -- sleep "${DURATION}"
fi

wait "${CLIENT_PID}"
client_rc="$?"
CLIENT_PID=""
fc_audit_tree_affinity "${SERVER_PID}" "${SERVER_CORES}" "${OUT}/server_affinity_end.csv" || audit_ok=0
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_end.csv" || audit_ok=0
if rg -q 'ERROR' "${OUT}"/*_pinner.log; then audit_ok=0; fi

python3 - "${OUT}" "${LABEL}" "${POSTGRES}" "${DATA_TEMPLATE}" \
  "${DURATION}" "${WARMUP_DURATION}" \
  "${client_rc}" "${audit_ok}" \
  "${CLIENTS}" "${CLIENT_THREADS}" "${QUERY_MODE}" \
  "${PGBENCH_BUILTIN}" "${PGBENCH_SCRIPT}" "${PGBENCH_TRANSACTIONS}" \
  "${PGBENCH_WARMUP_SEED}" "${PGBENCH_SEED}" \
  "${PROFILE_RECORD}" "${PROFILE_SAMPLE_PERIOD}" "${record_rc}" <<'PY'
import csv, json, re, sys
from pathlib import Path
(out, label, binary, data_template, duration, warmup_duration, client_rc, audit_ok,
 clients, client_threads, query_mode, pgbench_builtin, pgbench_script,
 transactions, warmup_seed, seed, profile_record, profile_sample_period,
 record_rc) = sys.argv[1:]
out = Path(out)
events = {}
migration_sources = []
for row in csv.reader((out / "perf.csv").open()):
    if len(row) < 3:
        continue
    try:
        value = float(row[0])
        event = row[2]
        owner = "aggregate"
    except ValueError:
        if len(row) < 4:
            continue
        try: value = float(row[1])
        except ValueError: continue
        event = row[3]
        owner = row[0]
    events[event] = events.get(event, 0.0) + value
    if event == "cpu-migrations" and value:
        migration_sources.append({"thread": owner, "count": int(value)})
text = (out / "pgbench.log").read_text(errors="replace")
tps_match = re.search(r"^tps = ([0-9.]+)", text, re.M)
failed_match = re.search(r"number of failed transactions: ([0-9]+)", text)
processed_match = re.search(r"number of transactions actually processed: ([0-9]+)", text)
latency_match = re.search(r"latency average = ([0-9.]+) ms", text)
tps = float(tps_match.group(1)) if tps_match else 0.0
failed = int(failed_match.group(1)) if failed_match else -1
processed = int(processed_match.group(1)) if processed_match else 0
latency_ms = float(latency_match.group(1)) if latency_match else 0.0
instructions = events.get("instructions", 0.0)
cycles = events.get("cycles", 0.0)
misses = events.get("L2I_CODE_RD_MISS", 0.0)
migrations = int(events.get("cpu-migrations", 0.0))
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
expected = int(clients) * int(transactions) if int(transactions) > 0 else 0
fixed_work_ok = expected == 0 or processed == expected
valid = int(int(client_rc) == 0 and int(audit_ok) == 1 and failed == 0 and
            tps > 0 and pinner_corrections == 0 and profile_ok and fixed_work_ok)
result = {
    "benchmark": "postgresql", "label": label, "binary": binary,
    "data_template": data_template,
    "duration_s": int(duration), "warmup_duration_s": int(warmup_duration),
    "clients": int(clients),
    "client_threads": int(client_threads), "query_mode": query_mode,
    "pgbench_builtin": pgbench_builtin, "pgbench_script": pgbench_script,
    "transactions_per_client": int(transactions),
    "pgbench_warmup_seed": warmup_seed, "pgbench_seed": seed,
    "profile_record": int(profile_record),
    "profile_sample_period": int(profile_sample_period),
    "record_rc": int(record_rc),
    "tps": tps, "latency_average_ms": latency_ms,
    "processed_transactions": processed,
    "application_runtime_s": processed / tps if tps else 0.0,
    "failed_transactions": failed,
    "instructions": instructions, "cycles": cycles, "l2i_misses": misses,
    "l2i_mpki": 1000 * misses / instructions if instructions else 0.0,
    "ipc": instructions / cycles if cycles else 0.0,
    "context_switches": int(events.get("context-switches", 0.0)),
    "cpu_migrations": migrations, "client_rc": int(client_rc),
    "migration_policy": "allow-pthread-creation-placement; reject-runtime-repin",
    "pinner_corrections_total": pinner_corrections_total,
    "pinner_corrections": pinner_corrections,
    "migration_sources": migration_sources,
    "audit_ok": int(audit_ok), "valid": valid,
}
(out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
with (out / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=result)
    writer.writeheader(); writer.writerow(result)
print(json.dumps(result, sort_keys=True))
PY

[[ "$(jq -r '.valid' "${OUT}/summary.json")" == 1 ]]
