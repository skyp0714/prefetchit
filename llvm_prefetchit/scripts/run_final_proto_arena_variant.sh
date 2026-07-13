#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 LABEL BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
COMMON="${ROOT}/llvm_prefetchit/scripts/final_campaign_common.sh"
PIN_SO="${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so"
LABEL="$1"
BINARY="$(readlink -f "$2")"
OUT="$(readlink -m "$3")"
ITERATIONS="${ITERATIONS:-300}"
WARMUP_SECONDS="${WARMUP_SECONDS:-5}"
PROFILE_RECORD="${PROFILE_RECORD:-0}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-5000}"
MEASURE_DURATION="${MEASURE_DURATION:-20}"
PERF_SCOPE="${PERF_SCOPE:-process}"
CONTROL_CORE=0
MAIN_CORE=1
THREAD_CORES="2-32"
ALL_CORES="0-32"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
PROFILE_EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

# shellcheck source=/dev/null
source "${COMMON}"

PERF_PID=""
BENCH_PID=""
PINNER_PID=""

cleanup() {
  set +e
  [[ -z "${PERF_PID}" ]] || kill "${PERF_PID}" >/dev/null 2>&1 || true
  [[ -z "${BENCH_PID}" ]] || kill "${BENCH_PID}" >/dev/null 2>&1 || true
  [[ -z "${PINNER_PID}" ]] || kill "${PINNER_PID}" >/dev/null 2>&1 || true
  [[ -z "${PERF_PID}" ]] || wait "${PERF_PID}" >/dev/null 2>&1 || true
  [[ -z "${PINNER_PID}" ]] || wait "${PINNER_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

mkdir -p "${OUT}"
rm -f "${OUT}"/*.csv "${OUT}"/*.json "${OUT}"/*.log \
  "${OUT}"/l2miss_profile.data "${OUT}"/record.out "${OUT}"/record.err
[[ -x "${BINARY}" && -f "${PIN_SO}" ]] || {
  echo "missing binary or pinning preload" >&2
  exit 2
}
((ITERATIONS > 0 && WARMUP_SECONDS >= 0 && PROFILE_SAMPLE_PERIOD > 0 && MEASURE_DURATION > 0))
[[ "${PERF_SCOPE}" == process || "${PERF_SCOPE}" == main-thread ]]

fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_start.csv"
sha256sum "${BINARY}" > "${OUT}/binary.sha256"
start_ns="$(date +%s%N)"
benchmark_command=(
  taskset -c "${MAIN_CORE}"
  env "LD_PRELOAD=${PIN_SO}${LD_PRELOAD:+:${LD_PRELOAD}}"
      "PREFETCHIT_THREAD_PIN_CORES=${THREAD_CORES}"
      GLIBC_TUNABLES=glibc.pthread.rseq=0
  "${BINARY}"
  '--benchmark_filter=^BM_PROTO_Arena$'
  "--benchmark_min_time=${ITERATIONS}x"
  "--benchmark_min_warmup_time=${WARMUP_SECONDS}"
  --benchmark_repetitions=1
  --benchmark_time_unit=ns
  "--benchmark_out=${OUT}/benchmark.json"
  --benchmark_out_format=json
)

"${benchmark_command[@]}" >"${OUT}/benchmark.log" 2>"${OUT}/benchmark.err" &
BENCH_PID="$!"

fc_start_pinner "${BENCH_PID}" "${MAIN_CORE},${THREAD_CORES}" "${OUT}/benchmark_pinner.log"
PINNER_PID="${FC_PINNER_PID}"
sleep 1
audit_ok=1
fc_audit_pid_affinity "${BENCH_PID}" "${MAIN_CORE},${THREAD_CORES}" \
  "${OUT}/benchmark_affinity.csv" || audit_ok=0
printf '[%(%F %T)T] MEASUREMENT_START\n' -1 >> "${OUT}/benchmark_pinner.log"
remaining_warmup=$((WARMUP_SECONDS + 2 - 1))
if ((remaining_warmup > 0)); then
  sleep "${remaining_warmup}"
fi
kill -0 "${BENCH_PID}" 2>/dev/null || {
  echo "benchmark exited before the steady-state measurement" >&2
  wait "${BENCH_PID}" || true
  exit 1
}
perf_attach=(-p "${BENCH_PID}")
if [[ "${PERF_SCOPE}" == main-thread ]]; then
  perf_attach=(-t "${BENCH_PID}")
fi

if ((PROFILE_RECORD == 1)); then
  taskset -c "${CONTROL_CORE}" perf record -q \
    -e "${PROFILE_EVENT}" -b -c "${PROFILE_SAMPLE_PERIOD}" \
    -o "${OUT}/l2miss_profile.data" "${perf_attach[@]}" -- sleep "${MEASURE_DURATION}" \
    >"${OUT}/record.out" 2>"${OUT}/record.err" &
else
  taskset -c "${CONTROL_CORE}" perf stat --no-big-num -x, \
    -o "${OUT}/perf.csv" \
    -e instructions:u,cycles:u,"${EVENT}",context-switches,cpu-migrations \
    "${perf_attach[@]}" -- sleep "${MEASURE_DURATION}" \
    >"${OUT}/perf.out" 2>"${OUT}/perf.err" &
fi
PERF_PID="$!"
set +e
wait "${PERF_PID}"
perf_rc="$?"
PERF_PID=""
wait "${BENCH_PID}"
bench_rc="$?"
set -e
BENCH_PID=""
run_rc="${bench_rc}"
if ((perf_rc != 0)); then
  run_rc="${perf_rc}"
fi
end_ns="$(date +%s%N)"
kill "${PINNER_PID}" >/dev/null 2>&1 || true
wait "${PINNER_PID}" >/dev/null 2>&1 || true
PINNER_PID=""
fc_assert_frequency "${ALL_CORES}" "${OUT}/frequency_end.csv" || audit_ok=0
if rg -q 'ERROR|CORRECT repin' "${OUT}/benchmark_pinner.log"; then
  audit_ok=0
fi

python3 - "${OUT}" "${LABEL}" "${BINARY}" "${ITERATIONS}" \
  "${WARMUP_SECONDS}" "${PROFILE_RECORD}" "${PROFILE_SAMPLE_PERIOD}" \
  "${MEASURE_DURATION}" "${PERF_SCOPE}" "${perf_rc}" "${bench_rc}" "${run_rc}" \
  "${audit_ok}" "${start_ns}" "${end_ns}" <<'PY'
import csv
import json
import math
import sys
from pathlib import Path

(out_raw, label, binary, iterations_requested, warmup_s, profile_record,
 sample_period, measure_duration, perf_scope, perf_rc, bench_rc, run_rc, audit_ok,
 start_ns, end_ns) = sys.argv[1:]
out = Path(out_raw)

events = {}
perf_path = out / "perf.csv"
if perf_path.is_file():
    with perf_path.open(newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 3 or row[0].startswith("<"):
                continue
            try:
                events[row[2].strip()] = float(row[0])
            except ValueError:
                pass

benchmark_rows = []
benchmark_path = out / "benchmark.json"
if benchmark_path.is_file():
    benchmark_rows = json.loads(benchmark_path.read_text()).get("benchmarks", [])
iterations = [
    row for row in benchmark_rows
    if row.get("name") == "BM_PROTO_Arena"
    and row.get("run_type", "iteration") == "iteration"
]
record = iterations[0] if len(iterations) == 1 else {}
unit_scale = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}
unit = record.get("time_unit", "ns")
real_time_ns = float(record.get("real_time", math.nan)) * unit_scale.get(unit, math.nan)
cpu_time_ns = float(record.get("cpu_time", math.nan)) * unit_scale.get(unit, math.nan)
instructions = events.get("instructions:u", events.get("instructions", 0.0))
cycles = events.get("cycles:u", events.get("cycles", 0.0))
misses = events.get("L2I_CODE_RD_MISS", 0.0)
migrations = int(events.get("cpu-migrations", -1))
profile_path = out / "l2miss_profile.data"
profile_ok = int(profile_record) == 0 or (
    profile_path.is_file() and profile_path.stat().st_size > 0
)
valid = int(
    int(run_rc) == 0
    and int(audit_ok) == 1
    and len(iterations) == 1
    and math.isfinite(real_time_ns)
    and real_time_ns > 0
    and profile_ok
    and (int(profile_record) == 1 or migrations == 0)
)
result = {
    "benchmark": "proto_arena",
    "label": label,
    "binary": binary,
    "iterations_requested": int(iterations_requested),
    "iterations": int(record.get("iterations", 0)),
    "warmup_s": int(warmup_s),
    "profile_record": int(profile_record),
    "profile_sample_period": int(sample_period),
    "measure_duration_s": int(measure_duration),
    "perf_scope": perf_scope,
    "real_time_ns": real_time_ns,
    "cpu_time_ns": cpu_time_ns,
    "wall_time_s": (int(end_ns) - int(start_ns)) / 1e9,
    "instructions": int(instructions),
    "cycles": int(cycles),
    "l2i_misses": int(misses),
    "l2i_mpki": 1000.0 * misses / instructions if instructions else 0.0,
    "ipc": instructions / cycles if cycles else 0.0,
    "context_switches": int(events.get("context-switches", -1)),
    "cpu_migrations": migrations,
    "perf_rc": int(perf_rc),
    "bench_rc": int(bench_rc),
    "run_rc": int(run_rc),
    "audit_ok": int(audit_ok),
    "valid": valid,
}
(out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
with (out / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=result)
    writer.writeheader()
    writer.writerow(result)
print(json.dumps(result, sort_keys=True))
PY

[[ "$(jq -r '.valid' "${OUT}/summary.json")" == 1 ]]
