#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 4 ]]; then
  echo "usage: $0 BENCHMARK LABEL WORKDIR BINARY [OUT_DIR]" >&2
  exit 2
fi

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
THREAD_PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
BENCHMARK="$1"
LABEL="$2"
WORKDIR="$(readlink -f "$3")"
BINARY="$(readlink -f "$4")"
OUT="$(readlink -m "${5:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/tailbench_strict/${BENCHMARK}_${LABEL}}")"

THREADS="${THREADS:-1}"
WAREHOUSES="${WAREHOUSES:-${THREADS}}"
QPS="${QPS:-100000}"
WARMUP_REQS="${WARMUP_REQS:-1000}"
MEASURE_REQS="${MEASURE_REQS:-10000}"
MIN_SLEEP_NS="${MIN_SLEEP_NS:-0}"
MIN_LIVE_TIDS="${MIN_LIVE_TIDS:-${THREADS}}"
READY_LOG_PATTERN="${READY_LOG_PATTERN:-}"
CONTROL_CORE=0
MAIN_CORE=1
THREAD_CORES="2-24"
ALL_CORES="0-24"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'

# shellcheck source=/dev/null
source "${COMMON}"
[[ -x "${BINARY}" ]] || { echo "missing executable: ${BINARY}" >&2; exit 2; }
[[ -f "${THREAD_PIN_SO}" ]] || { echo "missing pinner preload: ${THREAD_PIN_SO}" >&2; exit 2; }
mkdir -p "${OUT}"
rm -f "${OUT}"/*.{csv,json,log,txt,bin} 2>/dev/null || true
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_start.csv"

TAILBENCH_ROOT="$(dirname "${WORKDIR}")"
# shellcheck source=/dev/null
source "${TAILBENCH_ROOT}/configs.sh"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export LD_PRELOAD="${THREAD_PIN_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
export PREFETCHIT_THREAD_PIN_CORES="${THREAD_CORES}"
export TBENCH_QPS="${QPS}"
export TBENCH_WARMUPREQS="${WARMUP_REQS}"
export TBENCH_MAXREQS="${MEASURE_REQS}"
export TBENCH_MINSLEEPNS="${MIN_SLEEP_NS}"

case "${BENCHMARK}" in
  xapian)
    export LD_LIBRARY_PATH="${WORKDIR}/xapian-core-1.2.13/install/lib:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    export TBENCH_TERMS_FILE="${DATA_ROOT}/xapian/terms.in"
    COMMAND=("${BINARY}" -n "${THREADS}" -d "${DATA_ROOT}/xapian/wiki" -r 1000000000)
    ;;
  moses)
    sed "s#@DATA_ROOT#${DATA_ROOT}#g" "${WORKDIR}/moses.ini.template" > "${OUT}/moses.ini"
    export LD_LIBRARY_PATH="${WORKDIR}/bin:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    COMMAND=("${BINARY}" -config "${OUT}/moses.ini" -input-file "${DATA_ROOT}/moses/testTerms" -threads "${THREADS}" -num-tasks 100000 -verbose 0)
    ;;
  img_dnn|img-dnn)
    export TBENCH_MNIST_DIR="${DATA_ROOT}/img-dnn/mnist"
    COMMAND=("${BINARY}" -r "${THREADS}" -f "${DATA_ROOT}/img-dnn/models/model.xml" -n 100000000)
    ;;
  sphinx)
    export LD_LIBRARY_PATH="${WORKDIR}/sphinx-install/lib:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    export TBENCH_AN4_CORPUS="${DATA_ROOT}/sphinx"
    export TBENCH_AUDIO_SAMPLES="${AUDIO_SAMPLES:-audio_samples}"
    COMMAND=("${BINARY}" -t "${THREADS}")
    ;;
  masstree)
    COMMAND=("${BINARY}" "-j${THREADS}" mycsba masstree)
    ;;
  silo)
    export LD_LIBRARY_PATH="${TAILBENCH_HOME}/.local/apt_silo/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    COMMAND=("${BINARY}" --verbose --bench tpcc --num-threads "${THREADS}" \
      --scale-factor "${WAREHOUSES}" --retry-aborted-transactions \
      --ops-per-worker 10000000)
    ;;
  shore)
    rm -f "${WORKDIR}"/{scratch,log,diskrw,db-tpcc-1,cmdfile,shore.conf,info}
    rm -rf "${OUT}/shore_scratch"
    mkdir -p "${OUT}/shore_scratch/log" "${OUT}/shore_scratch/diskrw"
    ln -s "${OUT}/shore_scratch" "${WORKDIR}/scratch"
    ln -s scratch/log "${WORKDIR}/log"
    ln -s scratch/diskrw "${WORKDIR}/diskrw"
    cp "${DATA_ROOT}/shore/db-tpcc-1" "${OUT}/shore_scratch/"
    ln -s scratch/db-tpcc-1 "${WORKDIR}/db-tpcc-1"
    chmod 644 "${OUT}/shore_scratch/db-tpcc-1"
    sed -e "s#@NTHREADS#${THREADS}#g" -e 's#@REQS#100000000#g' \
      "${WORKDIR}/shore-kits/run-templates/cmdfile.template" > "${WORKDIR}/cmdfile"
    sed "s#@NTHREADS#${THREADS}#g" \
      "${WORKDIR}/shore-kits/run-templates/shore.conf.template" > "${WORKDIR}/shore.conf"
    COMMAND=("${BINARY}" -i cmdfile)
    ;;
  *)
    echo "unsupported benchmark: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

rm -f "${WORKDIR}/lats.bin"
start_ns="$(date +%s%N)"
(
  cd "${WORKDIR}"
  exec taskset -c "${MAIN_CORE}" "${COMMAND[@]}"
) >"${OUT}/run.log" 2>&1 &
APP_PID="$!"

audit_ok=1
PINNER_PID=""
PERF_PID=""
if kill -0 "${APP_PID}" 2>/dev/null; then
  fc_start_pinner "${APP_PID}" "${MAIN_CORE},${THREAD_CORES}" "${OUT}/pinner.log"
  PINNER_PID="${FC_PINNER_PID}"
  if [[ -n "${READY_LOG_PATTERN}" ]]; then
    deadline=$((SECONDS + 30))
    while ((SECONDS < deadline)); do
      rg -q "${READY_LOG_PATTERN}" "${OUT}/run.log" 2>/dev/null && break
      kill -0 "${APP_PID}" 2>/dev/null || break
      sleep 0.05
    done
    if ! rg -q "${READY_LOG_PATTERN}" "${OUT}/run.log" 2>/dev/null; then
      audit_ok=0
    fi
  fi
  deadline=$((SECONDS + 30))
  while ((SECONDS < deadline)); do
    live_tids="$(ps -L -o tid= -p "${APP_PID}" 2>/dev/null | awk 'NF {n++} END {print n+0}')"
    ((live_tids >= MIN_LIVE_TIDS)) && break
    kill -0 "${APP_PID}" 2>/dev/null || break
    sleep 0.05
  done
  if ((live_tids < MIN_LIVE_TIDS)); then
    audit_ok=0
  fi
  fc_wait_for_stable_pinning "${APP_PID}" "${MAIN_CORE},${THREAD_CORES}" "${OUT}/affinity.csv" 20 || audit_ok=0
  if kill -0 "${APP_PID}" 2>/dev/null; then
    taskset -c "${CONTROL_CORE}" perf stat -x, -o "${OUT}/perf.csv" \
      -e instructions,cycles,"${EVENT}",context-switches,cpu-migrations \
      -p "${APP_PID}" >"${OUT}/perf.log" 2>&1 &
    PERF_PID="$!"
  else
    audit_ok=0
  fi
else
  printf 'pid,tid,allowed_list,current_cpu,status\n,,,,app-pid-not-found\n' > "${OUT}/affinity.csv"
  audit_ok=0
fi

set +e
wait "${APP_PID}"
run_rc="$?"
set -e
end_ns="$(date +%s%N)"
python3 - "${start_ns}" "${end_ns}" > "${OUT}/elapsed.txt" <<'PY'
import sys
print((int(sys.argv[2]) - int(sys.argv[1])) / 1_000_000_000)
PY
if [[ -n "${PERF_PID}" ]]; then
  kill -INT "${PERF_PID}" >/dev/null 2>&1 || true
  wait "${PERF_PID}" >/dev/null 2>&1 || true
fi
if [[ -n "${PINNER_PID}" ]]; then
  kill "${PINNER_PID}" >/dev/null 2>&1 || true
  wait "${PINNER_PID}" >/dev/null 2>&1 || true
fi
if rg -q 'ERROR' "${OUT}/pinner.log" 2>/dev/null; then audit_ok=0; fi
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_end.csv" || audit_ok=0

if [[ -f "${WORKDIR}/lats.bin" ]]; then
  cp "${WORKDIR}/lats.bin" "${OUT}/lats.bin"
fi
if [[ "${BENCHMARK}" == shore ]]; then
  rm -f "${WORKDIR}"/{scratch,log,diskrw,db-tpcc-1,cmdfile,shore.conf,info}
fi

python3 - "${OUT}" "${BENCHMARK}" "${LABEL}" "${BINARY}" "${THREADS}" \
  "${QPS}" "${WARMUP_REQS}" "${MEASURE_REQS}" "${MIN_SLEEP_NS}" \
  "${run_rc}" "${audit_ok}" "${APP_PID}" <<'PY'
import csv
import json
import pathlib
import sys

(out_s, benchmark, label, binary, threads, qps, warmup, measured,
 min_sleep, run_rc, audit_ok, app_pid) = sys.argv[1:]
out = pathlib.Path(out_s)
values = {}
if (out / "perf.csv").exists():
    with (out / "perf.csv").open(newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 3 or not row[0] or row[0].startswith("<"):
                continue
            try:
                values[row[2].strip()] = float(row[0])
            except ValueError:
                pass

def event_value(*names):
    for name in names:
        if name in values:
            return values[name]
    return 0.0

elapsed = 0.0
if (out / "elapsed.txt").exists():
    for line in reversed((out / "elapsed.txt").read_text().splitlines()):
        try:
            elapsed = float(line.strip())
            break
        except ValueError:
            pass
instructions = event_value("instructions")
cycles = event_value("cycles")
misses = event_value("L2I_CODE_RD_MISS", "cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/")
context_switches = int(event_value("context-switches"))
migrations = int(event_value("cpu-migrations"))
lat_bytes = (out / "lats.bin").stat().st_size if (out / "lats.bin").exists() else 0
latency_records = lat_bytes // 24
expected = int(measured)
record_delta = latency_records - expected
valid = int(
    int(run_rc) == 0 and int(audit_ok) == 1 and migrations == 0
    and elapsed > 0 and abs(record_delta) <= max(1, int(threads))
)
summary = {
    "benchmark": benchmark,
    "label": label,
    "binary": binary,
    "threads": int(threads),
    "configured_qps": float(qps),
    "warmup_requests": int(warmup),
    "measured_requests": expected,
    "min_sleep_ns": int(min_sleep),
    "elapsed_s": elapsed,
    "derived_qps": (int(warmup) + expected) / elapsed if elapsed else 0.0,
    "instructions": instructions,
    "cycles": cycles,
    "ipc": instructions / cycles if cycles else 0.0,
    "l2i_misses": misses,
    "l2i_mpki": 1000.0 * misses / instructions if instructions else 0.0,
    "context_switches": context_switches,
    "cpu_migrations": migrations,
    "latency_records": latency_records,
    "latency_record_delta": record_delta,
    "run_rc": int(run_rc),
    "audit_ok": int(audit_ok),
    "app_pid": int(app_pid) if app_pid else None,
    "valid": valid,
}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, sort_keys=True))
PY

[[ "$(jq -r .valid "${OUT}/summary.json")" == 1 ]]
