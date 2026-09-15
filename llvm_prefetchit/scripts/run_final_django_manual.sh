#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BENCH_ROOT="${ROOT}/benchmarks/dcperf/benchmarks/django_workload"
SERVER_ROOT="${BENCH_ROOT}/django-workload/django-workload"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
HTTP_CLIENT="${ROOT}/llvm_prefetchit/tools/django_http_load.py"
THREAD_PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
BIN_ROOT="${BIN_ROOT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/django_manual_bins}"
OUT_ROOT="${OUT_ROOT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/django_manual_screen}"

# Cassandra is a JVM dependency and can create roughly 70 mostly-idle helper
# TIDs during schema setup. It is isolated in a disjoint partition and never
# profiled. Every native server and client TID gets a unique physical core.
DB_CORES="${DB_CORES:-1-59}"
MEMCACHED_CORES="${MEMCACHED_CORES:-60-66}"
UWSGI_MASTER_CORES="${UWSGI_MASTER_CORES:-67-71}"
UWSGI_WORKER_CORES="${UWSGI_WORKER_CORES:-72-80}"
UWSGI_CREATE_CORES="${UWSGI_CREATE_CORES:-73-80}"
SERVER_CORES="${SERVER_CORES:-60-80}"
CLIENT_CORES="${CLIENT_CORES:-81-85}"
ALL_CORES="0-85"
SERVER_WORKERS="${SERVER_WORKERS:-1}"
CLIENT_WORKERS="${CLIENT_WORKERS:-1}"
MEMCACHED_THREADS="${MEMCACHED_THREADS:-1}"
CASSANDRA_THREADS="${CASSANDRA_THREADS:-2}"
WARMUP="${WARMUP:-20S}"
WARMUP_REQUESTS="${WARMUP_REQUESTS:-300}"
DURATION="${DURATION:-45S}"
IB_MIN="${IB_MIN:-1000000}"
IB_MAX="${IB_MAX:-2000000}"
VARIANT_SEQUENCE="${VARIANT_SEQUENCE:-all}"
PERF_EVENTS="${PERF_EVENTS:-instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,context-switches,cpu-migrations}"
PROFILE_RECORD="${PROFILE_RECORD:-0}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-50000}"

# shellcheck source=/dev/null
source "${COMMON}"

DB_ROOT_PID=""
SERVER_ROOT_PID=""
SERVER_MASTER_PID=""
MEMCACHED_PID=""
SERVER_PINNER_PIDS=()
CLIENT_ROOT_PID=""
CLIENT_PINNER_PID=""

stop_pid() {
  local pid="${1:-}" signal="${2:-TERM}"
  [[ -n "${pid}" ]] || return 0
  kill -0 "${pid}" 2>/dev/null || return 0
  kill -"${signal}" "${pid}" 2>/dev/null || true
  for _ in {1..100}; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -KILL "${pid}" 2>/dev/null || true
}

stop_pinner_pid() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] || return 0
  kill "${pid}" >/dev/null 2>&1 || true
  wait "${pid}" >/dev/null 2>&1 || true
}

cleanup_server() {
  stop_pid "${SERVER_ROOT_PID}" TERM
  stop_pid "${SERVER_MASTER_PID}" INT
  stop_pid "${MEMCACHED_PID}" TERM
  for pid in "${SERVER_PINNER_PIDS[@]}"; do stop_pinner_pid "${pid}"; done
  SERVER_ROOT_PID=""
  SERVER_MASTER_PID=""
  MEMCACHED_PID=""
  SERVER_PINNER_PIDS=()
  for _ in {1..50}; do
    if ! nc -z 127.0.0.1 8000 >/dev/null 2>&1 && \
       ! nc -z 127.0.0.1 11811 >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  pgrep -u "$(id -u)" -f '/usr/bin/memcached .* -p 11811' | xargs -r kill -KILL || true
  pgrep -u "$(id -u)" -f 'uWSGI (master|worker)' | xargs -r kill -KILL || true
}

cleanup() {
  set +e
  stop_pid "${CLIENT_ROOT_PID}" TERM
  stop_pinner_pid "${CLIENT_PINNER_PID}"
  cleanup_server
  stop_pid "${DB_ROOT_PID}" TERM
  pgrep -u "$(id -u)" -f '/usr/bin/memcached .* -p 11811' | xargs -r kill -KILL
  pgrep -u "$(id -u)" -f 'org.apache.cassandra.service.CassandraDaemon' | xargs -r kill -KILL
}

interrupted() {
  trap - INT TERM EXIT
  cleanup
  exit 130
}
trap cleanup EXIT
trap interrupted INT TERM

wait_port() {
  local host="$1" port="$2" state="$3" timeout_sec="$4"
  local deadline=$((SECONDS + timeout_sec))
  while ((SECONDS < deadline)); do
    if [[ "${state}" == open ]] && nc -z "${host}" "${port}" >/dev/null 2>&1; then return 0; fi
    if [[ "${state}" == closed ]] && ! nc -z "${host}" "${port}" >/dev/null 2>&1; then return 0; fi
    sleep 0.2
  done
  printf 'timeout waiting for %s:%s to become %s\n' "${host}" "${port}" "${state}" >&2
  return 1
}

start_db() {
  local out="${OUT_ROOT}/database"
  mkdir -p "${out}"
  rm -f "${BENCH_ROOT}/cassandra.pid"
  setsid taskset -c "${DB_CORES}" env \
    JVM_EXTRA_OPTS='-XX:ActiveProcessorCount=1 -XX:CICompilerCount=2 -XX:ParallelGCThreads=1 -XX:ConcGCThreads=1' \
    CASSANDRA_CONCURRENT_READS="${CASSANDRA_THREADS}" \
    bash "${BENCH_ROOT}/bin/run.sh" -r db -y "${CASSANDRA_THREADS}" -b 127.0.0.1 \
    >"${out}/stdout.log" 2>"${out}/stderr.log" &
  DB_ROOT_PID="$!"
  wait_port 127.0.0.1 9042 open 180
  sleep 2
  audit_shared_partition "${DB_ROOT_PID}" "${DB_CORES}" "${out}/affinity_start.csv"
}

audit_shared_partition() {
  local root_pid="$1" expected="$2" output="$3" pid tid comm allowed bad=0 java_pid=""
  printf 'pid,tid,comm,allowed_list,status\n' > "${output}"
  while read -r pid; do
    [[ "$(cat "/proc/${pid}/comm" 2>/dev/null || true)" == java ]] || continue
    java_pid="${pid}"
    break
  done < <(fc_collect_tree_pids "${root_pid}")
  [[ -n "${java_pid}" ]] || {
    printf '%s,,,,no-java-process\n' "${root_pid}" >> "${output}"
    return 1
  }
  while read -r tid comm; do
    [[ -n "${tid}" ]] || continue
    allowed="$(awk '/Cpus_allowed_list/ {print $2}' "/proc/${java_pid}/task/${tid}/status" 2>/dev/null || true)"
    if [[ "${allowed}" == "${expected}" ]]; then
      printf '%s,%s,%s,%s,ok-shared-jvm-partition\n' "${java_pid}" "${tid}" "${comm}" "${allowed}" >> "${output}"
    else
      printf '%s,%s,%s,%s,invalid-partition\n' "${java_pid}" "${tid}" "${comm}" "${allowed}" >> "${output}"
      bad=1
    fi
  done < <(ps -L -o tid=,comm= -p "${java_pid}")
  return "${bad}"
}

pin_server_process() {
  local pid="$1" cores="$2" prefix="$3" run_dir="$4"
  fc_start_pinner "${pid}" "${cores}" "${run_dir}/${prefix}_pinner.log"
  SERVER_PINNER_PIDS+=("${FC_PINNER_PID}")
  fc_wait_for_stable_pinning "${pid}" "${cores}" "${run_dir}/${prefix}_affinity_start.csv" 20
}

start_server() {
  local label="$1" run_dir="$2" lib="${BIN_ROOT}/${label}/libicachebuster.so"
  [[ -f "${lib}" ]] || { echo "missing variant ${lib}" >&2; return 1; }
  cp -f "${lib}" "${SERVER_ROOT}/libicachebuster.so"
  rm -f "${BENCH_ROOT}/uwsgi.pid"
  setsid taskset -c "${SERVER_CORES}" env \
    USER="$(id -un)" THREADS="${MEMCACHED_THREADS}" \
    LD_LIBRARY_PATH="${SERVER_ROOT}:${LD_LIBRARY_PATH:-}" \
    DCPERF_UWSGI_LD_PRELOAD="${THREAD_PIN_SO}" \
    DCPERF_UWSGI_PIN_CORES="${UWSGI_CREATE_CORES}" \
    DCPERF_UWSGI_PIN_AFTER_FORK=1 \
    bash "${BENCH_ROOT}/bin/run.sh" -r server -c 127.0.0.1 \
      -w "${SERVER_WORKERS}" -m "${IB_MIN}" -M "${IB_MAX}" \
    >"${run_dir}/server.out" 2>"${run_dir}/server.err" &
  SERVER_ROOT_PID="$!"
  wait_port 127.0.0.1 8000 open 300
  sleep 2
  SERVER_MASTER_PID="$(<"${BENCH_ROOT}/uwsgi.pid")"
  MEMCACHED_PID="$(pgrep -u "$(id -u)" -f '/usr/bin/memcached .* -p 11811' | head -1)"
  mapfile -t worker_pids < <(pgrep -P "${SERVER_MASTER_PID}")
  if [[ "${#worker_pids[@]}" -ne 1 ]]; then
    printf 'expected one uWSGI worker, found %s\n' "${#worker_pids[@]}" >&2
    return 1
  fi
  pin_server_process "${MEMCACHED_PID}" "${MEMCACHED_CORES}" memcached "${run_dir}"
  pin_server_process "${SERVER_MASTER_PID}" "${UWSGI_MASTER_CORES}" uwsgi_master "${run_dir}"
  pin_server_process "${worker_pids[0]}" "${UWSGI_WORKER_CORES}" uwsgi_worker "${run_dir}"
}

run_warmup() {
  local run_dir="$1"
  local worker_pid warmup_seconds="${WARMUP%S}"
  [[ "${warmup_seconds}" =~ ^[0-9]+$ ]] || {
    echo "warmup must use integer seconds, got ${WARMUP}" >&2
    return 1
  }
  taskset -c "${CLIENT_CORES%%-*}" bash -c '
    set -u
    duration="$1"; minimum="$2"; output="$3"; seen_file="$4"
    deadline=$((SECONDS + duration))
    urls=(
      feed_timeline feed_timeline feed_timeline feed_timeline feed_timeline feed_timeline
      timeline timeline timeline timeline timeline timeline
      bundle_tray bundle_tray bundle_tray
      inbox inbox inbox inbox
      seen
    )
    ok=0; errors=0; index=0
    while ((SECONDS < deadline || ok < minimum)); do
      url="${urls[index % ${#urls[@]}]}"
      if [[ "${url}" == seen ]]; then
        curl_args=(-H "Content-Type: application/json" --data-binary "@${seen_file}")
      else
        curl_args=()
      fi
      if curl -fsS --max-time 10 "${curl_args[@]}" \
          "http://127.0.0.1:8000/${url}" >/dev/null 2>&1; then
        ok=$((ok + 1))
      else
        errors=$((errors + 1))
      fi
      index=$((index + 1))
    done
    printf "duration_s=%s successful_requests=%s errors=%s\n" "$duration" "$ok" "$errors" > "$output"
    ((ok > 0 && errors == 0))
  ' _ "${warmup_seconds}" "${WARMUP_REQUESTS}" "${run_dir}/warmup.out" \
    "${BENCH_ROOT}/django-workload/client/seen.json"
  worker_pid="$(pgrep -P "${SERVER_MASTER_PID}" | head -1)"
  fc_wait_for_stable_pinning "${worker_pid}" "${UWSGI_WORKER_CORES}" \
    "${run_dir}/uwsgi_worker_affinity_after_warmup.csv" 20
  kill -STOP "${worker_pid}"
  for _ in {1..100}; do
    if ps -L -o stat= -p "${worker_pid}" | awk 'NF && $1 !~ /^T/ {bad=1} END {exit bad}'; then
      break
    fi
    sleep 0.01
  done
  kill -CONT "${worker_pid}"
  sleep 1
  ps -L -o pid=,tid=,psr=,stat=,comm= -p "${worker_pid}" \
    > "${run_dir}/uwsgi_worker_residency_after_resume.txt"
}

uwsgi_worker_pids() {
  local master retries=100
  while ((retries-- > 0)); do
    if [[ -s "${BENCH_ROOT}/uwsgi.pid" ]]; then
      master="$(<"${BENCH_ROOT}/uwsgi.pid")"
      pgrep -P "${master}" 2>/dev/null | paste -sd, -
      return 0
    fi
    sleep 0.1
  done
  return 1
}

parse_run() {
  local run_dir="$1" label="$2" run_index="$3" perf_rc="$4" worker_pids="$5" audit_ok="$6"
  python3 - "${run_dir}" "${label}" "${run_index}" "${perf_rc}" "${worker_pids}" "${audit_ok}" \
    "${DURATION}" "${WARMUP}" "${IB_MIN}" "${IB_MAX}" "${DB_CORES}" "${SERVER_CORES}" "${CLIENT_CORES}" <<'PY'
import csv
import json
import pathlib
import re
import sys

(run_dir, label, run_index, perf_rc, workers, audit_ok, duration, warmup,
 ib_min, ib_max, db_cores, server_cores, client_cores) = sys.argv[1:]
root = pathlib.Path(run_dir)

siege = {}
metrics_path = root / "client_metrics.json"
if metrics_path.exists():
    metrics = json.loads(metrics_path.read_text())
    siege = {
        "transactions": metrics.get("completed", ""),
        "elapsed_time": metrics.get("elapsed_time_s", ""),
        "transaction_rate": metrics.get("completed_qps", ""),
        "availability": metrics.get("availability_pct", ""),
        "response_time": metrics.get("mean_response_time_s", ""),
        "failed_transactions": metrics.get("failed", ""),
    }
for path in sorted(root.glob("siege_out_*")):
    text = path.read_text(errors="replace")
    match = re.search(r"\{.*?\}", text, re.S)
    if match:
        siege = json.loads(match.group(0))
        break

events = {}
with (root / "perf.csv").open(newline="") as handle:
    for row in csv.reader(handle):
        if len(row) < 3 or not row[0].strip() or row[0].lstrip().startswith("<"):
            continue
        try:
            events[row[2].strip()] = float(row[0].replace(",", ""))
        except ValueError:
            pass

instructions = events.get("instructions", 0.0)
cycles = events.get("cycles", 0.0)
l2i = events.get("L2I_CODE_RD_MISS", 0.0)
migrations = events.get("cpu-migrations", -1.0)
contexts = events.get("context-switches", -1.0)
pinner_errors = 0
for path in root.glob("*pinner.log"):
    pinner_errors += path.read_text(errors="replace").count("ERROR")

def audit_threads(pattern):
    count = 0
    for path in root.glob(pattern):
        with path.open(newline="") as handle:
            count += sum(1 for row in csv.DictReader(handle) if row.get("status") == "ok")
    return count

server_audit_patterns = (
    "memcached_affinity_measure.csv",
    "uwsgi_master_affinity_measure.csv",
    "uwsgi_worker_affinity_measure.csv",
)
server_tids = sum(audit_threads(pattern) for pattern in server_audit_patterns)
db_tids = 0
for path in root.glob("db_affinity_measure.csv"):
    with path.open(newline="") as handle:
        db_tids += sum(
            1 for row in csv.DictReader(handle)
            if row.get("status") == "ok-shared-jvm-partition"
        )

row = {
    "run_index": run_index,
    "label": label,
    "duration": duration,
    "warmup": warmup,
    "ib_min": ib_min,
    "ib_max": ib_max,
    "db_cores": db_cores,
    "server_cores": server_cores,
    "client_cores": client_cores,
    "uwsgi_worker_pids": workers,
    "transactions": siege.get("transactions", ""),
    "elapsed_time_s": siege.get("elapsed_time", ""),
    "transaction_rate_qps": siege.get("transaction_rate", ""),
    "availability_pct": siege.get("availability", ""),
    "response_time_s": siege.get("response_time", ""),
    "failed_transactions": siege.get("failed_transactions", ""),
    "load_generator": "python-http.client-single-connection",
    "instructions": int(instructions),
    "cycles": int(cycles),
    "l2i_misses": int(l2i),
    "l2i_mpki": l2i / instructions * 1000 if instructions else 0,
    "ipc": instructions / cycles if cycles else 0,
    "context_switches": int(contexts),
    "cpu_migrations": int(migrations),
    "server_tids_audited": server_tids,
    "client_tids_audited": audit_threads("client_affinity_*.csv"),
    "db_tids_partitioned": db_tids,
    "db_thread_policy": "shared-disjoint-jvm-dependency",
    "native_thread_policy": "one-tid-per-physical-core",
    "pinner_errors": pinner_errors,
    "perf_rc": int(perf_rc),
    "audit_ok": int(audit_ok),
    "valid": int(
        int(perf_rc) == 0
        and int(audit_ok) == 1
        and migrations == 0
        and pinner_errors == 0
        and float(siege.get("transaction_rate", 0) or 0) > 0
        and int(siege.get("failed_transactions", -1)) == 0
        and float(siege.get("availability", 0) or 0) == 100.0
    ),
}
with (root / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=row)
    writer.writeheader()
    writer.writerow(row)
print(json.dumps(row, sort_keys=True))
PY
}

run_measurement() {
  local label="$1" run_index="$2" run_dir="$3"
  local worker_pids perf_rc audit_ok=1 record_pid="" record_rc=0
  worker_pids="$(uwsgi_worker_pids)"
  [[ -n "${worker_pids}" ]] || { echo 'no uWSGI worker PIDs' >&2; return 1; }
  printf '%s\n' "${worker_pids}" > "${run_dir}/uwsgi_worker_pids.txt"
  local measurement_seconds="${DURATION%S}"
  [[ "${measurement_seconds}" =~ ^[0-9]+$ ]] || {
    echo "duration must use integer seconds, got ${DURATION}" >&2
    return 1
  }

  if ((PROFILE_RECORD == 1)); then
    taskset -c 0 perf record -q \
      -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' \
      -b -c "${PROFILE_SAMPLE_PERIOD}" \
      -o "${run_dir}/l2miss_profile.data" -p "${worker_pids}" -- \
      sleep "${measurement_seconds}" \
      >"${run_dir}/record.out" 2>"${run_dir}/record.err" &
    record_pid="$!"
  fi

  taskset -c 0 perf stat -x, -o "${run_dir}/perf.csv" -e "${PERF_EVENTS}" \
    -p "${worker_pids}" -- \
    taskset -c "${CLIENT_CORES}" \
      python3 "${HTTP_CLIENT}" --duration "${measurement_seconds}" \
        --seen-body "${BENCH_ROOT}/django-workload/client/seen.json" \
        --output "${run_dir}/client_metrics.json" --seed 1 \
      >"${run_dir}/client.out" 2>"${run_dir}/client.err" &
  CLIENT_ROOT_PID="$!"
  fc_start_tree_pinner "${CLIENT_ROOT_PID}" "${CLIENT_CORES}" "${run_dir}/client_pinner.log"
  CLIENT_PINNER_PID="${FC_PINNER_PID}"
  sleep 2

  audit_shared_partition "${DB_ROOT_PID}" "${DB_CORES}" "${run_dir}/db_affinity_measure.csv" || audit_ok=0
  fc_audit_pid_affinity "${MEMCACHED_PID}" "${MEMCACHED_CORES}" "${run_dir}/memcached_affinity_measure.csv" || audit_ok=0
  fc_audit_pid_affinity "${SERVER_MASTER_PID}" "${UWSGI_MASTER_CORES}" "${run_dir}/uwsgi_master_affinity_measure.csv" || audit_ok=0
  for pid in ${worker_pids//,/ }; do
    fc_audit_pid_affinity "${pid}" "${UWSGI_WORKER_CORES}" "${run_dir}/uwsgi_worker_affinity_measure.csv" || audit_ok=0
  done
  fc_audit_tree_affinity "${CLIENT_ROOT_PID}" "${CLIENT_CORES}" "${run_dir}/client_affinity_measure.csv" || audit_ok=0

  set +e
  wait "${CLIENT_ROOT_PID}"
  perf_rc="$?"
  set -e
  if [[ -n "${record_pid}" ]]; then
    set +e
    wait "${record_pid}"
    record_rc="$?"
    set -e
    if ((record_rc != 0)) || [[ ! -s "${run_dir}/l2miss_profile.data" ]]; then
      audit_ok=0
    fi
  fi
  CLIENT_ROOT_PID=""
  stop_pinner_pid "${CLIENT_PINNER_PID}"
  CLIENT_PINNER_PID=""
  audit_shared_partition "${DB_ROOT_PID}" "${DB_CORES}" "${run_dir}/db_affinity_end.csv" || audit_ok=0
  fc_audit_pid_affinity "${MEMCACHED_PID}" "${MEMCACHED_CORES}" "${run_dir}/memcached_affinity_end.csv" || audit_ok=0
  fc_audit_pid_affinity "${SERVER_MASTER_PID}" "${UWSGI_MASTER_CORES}" "${run_dir}/uwsgi_master_affinity_end.csv" || audit_ok=0
  for pid in ${worker_pids//,/ }; do
    fc_audit_pid_affinity "${pid}" "${UWSGI_WORKER_CORES}" "${run_dir}/uwsgi_worker_affinity_end.csv" || audit_ok=0
  done
  if rg -q 'ERROR' "${run_dir}"/*_pinner.log; then
    audit_ok=0
  fi
  parse_run "${run_dir}" "${label}" "${run_index}" "${perf_rc}" "${worker_pids}" "${audit_ok}"
}

mkdir -p "${OUT_ROOT}"
if [[ -e "${OUT_ROOT}/runs.csv" ]]; then
  cp -f "${OUT_ROOT}/runs.csv" "${OUT_ROOT}/runs.before.$(date +%s).csv"
fi
rm -f "${OUT_ROOT}/runs.csv"
fc_assert_frequency "${ALL_CORES}" "${OUT_ROOT}/frequency_start.csv"

if [[ "${VARIANT_SEQUENCE}" == all ]]; then
  mapfile -t VARIANTS < <(awk -F, 'NR > 1 {print $1}' "${BIN_ROOT}/manifest.csv")
else
  read -r -a VARIANTS <<< "${VARIANT_SEQUENCE//,/ }"
fi

start_db
run_index=0
for label in "${VARIANTS[@]}"; do
  run_index=$((run_index + 1))
  run_dir="${OUT_ROOT}/run_$(printf '%03d' "${run_index}")_${label}"
  mkdir -p "${run_dir}"
  fc_assert_frequency "${ALL_CORES}" "${run_dir}/frequency.csv"
  start_server "${label}" "${run_dir}"
  run_warmup "${run_dir}"
  run_measurement "${label}" "${run_index}" "${run_dir}"
  cleanup_server

  if [[ ! -s "${OUT_ROOT}/runs.csv" ]]; then
    cp "${run_dir}/summary.csv" "${OUT_ROOT}/runs.csv"
  else
    tail -n +2 "${run_dir}/summary.csv" >> "${OUT_ROOT}/runs.csv"
  fi
done

fc_assert_frequency "${ALL_CORES}" "${OUT_ROOT}/frequency_end.csv"
printf 'completed %s Django runs: %s\n' "${#VARIANTS[@]}" "${OUT_ROOT}/runs.csv"
