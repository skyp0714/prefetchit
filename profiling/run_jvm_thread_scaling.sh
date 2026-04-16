#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/runscript/bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PERF_BIN="${PERF_BIN:-perf}"
OUT_CSV="${OUT_CSV:-${PROFILING_DIR}/results/jvm_context_switch/csv/contextswitch_thread_scaling.csv}"
OUT_PNG_THREAD="${OUT_PNG_THREAD:-${PROFILING_DIR}/results/jvm_context_switch/png/contextswitch_percore_threads.png}"
OUT_PNG_FREQ="${OUT_PNG_FREQ:-${PROFILING_DIR}/results/jvm_context_switch/png/contextswitch_frequency_vs_cores.png}"
PERF_CPU="${PERF_CPU:-0}"
PERF_USER_ONLY="${PERF_USER_ONLY:-1}"
LOG_DIR="${LOG_ROOT}/ctxswitch_thread_scaling"
RAW_DIR="${RAW_DIR:-${PROFILING_DIR}/results/jvm_context_switch/raw}"

CORE_COUNTS="${CORE_COUNTS:-1 2 4 8 16 32 64 86}"
BENCHMARKS="${BENCHMARKS:-tomcat finagle-http finagle-chirper}"
RESUME_CSV="${RESUME_CSV:-1}"

MEASURE_SECS="${MEASURE_SECS:-60}"
SAMPLE_INTERVAL_SECS="${SAMPLE_INTERVAL_SECS:-1}"
STARTUP_TIMEOUT_SECS="${STARTUP_TIMEOUT_SECS:-45}"

# Keep JVM jobs alive for the whole sampling window.
TOMCAT_SIZE="${TOMCAT_SIZE:-large}"
TOMCAT_ITERATIONS="${TOMCAT_ITERATIONS:-100000}"
TOMCAT_WATCHDOG_SECS="${TOMCAT_WATCHDOG_SECS:-3600}"
FINAGLE_RUN_SECONDS="${FINAGLE_RUN_SECONDS:-1800}"

CPU_TOTAL="$(nproc --all)"
mkdir -p "$(dirname "${OUT_CSV}")" "$(dirname "${OUT_PNG_THREAD}")" "$(dirname "${OUT_PNG_FREQ}")" "${LOG_DIR}" "${RAW_DIR}"

if [[ "$(id -u)" -ne 0 ]]; then
  PARANOID="$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo 4)"
  if [[ "${PARANOID}" -gt 1 ]]; then
    echo "[err] perf_event_paranoid=${PARANOID}. run with sudo." >&2
    exit 1
  fi
fi

csv_header="Benchmark,CoreCount,CoreSet,MeasureSec,SampleIntervalSec,ThreadsMin,ThreadsMax,ThreadsAvg,PerCoreThreadsAvg,Samples,Instructions,ContextSwitches,CtxSwitchesPerMInst,ReturnCode,ElapsedSec,PerfRaw,LogFile"
if [[ "${RESUME_CSV}" != "1" || ! -s "${OUT_CSV}" ]]; then
  echo "${csv_header}" > "${OUT_CSV}"
fi

row_completed() {
  local bench="$1"
  local cores="$2"
  [[ -f "${OUT_CSV}" ]] || return 1
  awk -F, -v b="${bench}" -v c="${cores}" '
    NR > 1 && NF >= 17 && $1 == b && $2 == c && ($11 + 0) > 0 && ($14 + 0) == 0 { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "${OUT_CSV}"
}

drop_rows_for_key() {
  local bench="$1"
  local cores="$2"
  local tmp
  tmp="$(mktemp)"
  awk -F, -v b="${bench}" -v c="${cores}" '
    NR == 1 || !($1 == b && $2 == c)
  ' "${OUT_CSV}" > "${tmp}"
  mv "${tmp}" "${OUT_CSV}"
}

core_set_for() {
  local cores="$1"
  if [[ "${cores}" -eq 1 ]]; then
    echo "0"
  else
    echo "0-$((cores - 1))"
  fi
}

bench_cmd() {
  local bench="$1"
  local cores="$2"
  case "${bench}" in
    tomcat)
      # `JAVA_TOOL_OPTIONS` applies ActiveProcessorCount without touching benchmark wrapper code.
      echo "JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount=${cores} SIZE=${TOMCAT_SIZE} DACAPO_CONVERGE=0 ITERATIONS=${TOMCAT_ITERATIONS} WATCHDOG_SECS=${TOMCAT_WATCHDOG_SECS} ./runscript/bench/run_tomcat.sh"
      ;;
    finagle-http)
      echo "ACTIVE_CPUS=${cores} RUN_SECONDS=${FINAGLE_RUN_SECONDS} FINAGLE_PRINT_COMPILATION=1 ./runscript/bench/run_finagle_http.sh"
      ;;
    finagle-chirper)
      echo "ACTIVE_CPUS=${cores} RUN_SECONDS=${FINAGLE_RUN_SECONDS} FINAGLE_PRINT_COMPILATION=1 ./runscript/bench/run_finagle_chirper.sh"
      ;;
    *)
      return 1
      ;;
  esac
}

bench_pattern() {
  local bench="$1"
  case "${bench}" in
    tomcat)
      echo "dacapo-23\\.11-MR2-chopin\\.jar"
      ;;
    finagle-http)
      echo "renaissance-gpl\\.jar.*finagle-http"
      ;;
    finagle-chirper)
      echo "renaissance-gpl\\.jar.*finagle-chirper"
      ;;
    *)
      return 1
      ;;
  esac
}

find_new_pid() {
  local pattern="$1"
  local baseline="$2"
  local runner_pid="$3"

  for _ in $(seq 1 "${STARTUP_TIMEOUT_SECS}"); do
    if ! kill -0 "${runner_pid}" 2>/dev/null; then
      break
    fi
    local current
    current="$(pgrep -f "${pattern}" 2>/dev/null | tr '\n' ' ' || true)"
    for pid in ${current}; do
      if [[ " ${baseline} " != *" ${pid} "* ]]; then
        echo "${pid}"
        return 0
      fi
    done
    sleep 1
  done
  return 1
}

parse_perf_counts() {
  local raw_file="$1"
  "${PYTHON_BIN}" - "${raw_file}" <<'PY'
import sys
from pathlib import Path

raw = Path(sys.argv[1])
counts = {"instructions": 0.0, "context-switches": 0.0}
if raw.exists():
    for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        value = parts[0].strip().replace(" ", "")
        event = parts[2].strip()
        if event.startswith("instructions"):
            key = "instructions"
        elif event.startswith("context-switches"):
            key = "context-switches"
        else:
            continue
        if value.startswith("<") or value in ("notcounted", "not-counted", "not", "notsupported"):
            continue
        try:
            counts[key] = float(value)
        except ValueError:
            continue
print(f"{counts['instructions']} {counts['context-switches']}")
PY
}

run_one() {
  local bench="$1"
  local cores="$2"
  local cset run_cmd pattern log_file raw_file
  local runner_pid java_pid perf_pid
  local threads_min=0 threads_max=0 threads_sum=0 samples=0
  local perf_rc=1 elapsed
  local start

  if [[ "${cores}" -gt "${CPU_TOTAL}" ]]; then
    echo "[warn] skip ${bench}: cores=${cores} > cpu_total=${CPU_TOTAL}"
    return 0
  fi

  if [[ "${RESUME_CSV}" == "1" ]] && row_completed "${bench}" "${cores}"; then
    echo "[inf] skip ${bench}: cores=${cores} already present in ${OUT_CSV}"
    return 0
  fi

  cset="$(core_set_for "${cores}")"
  run_cmd="$(bench_cmd "${bench}" "${cores}")"
  pattern="$(bench_pattern "${bench}")"
  log_file="${LOG_DIR}/${bench}_${cores}c.log"
  raw_file="${RAW_DIR}/ctxswitch_threads_${bench}_${cores}c.perfraw"

  local scope_txt="user+kernel"
  local user_only_args=()
  if [[ "${PERF_USER_ONLY}" == "1" ]]; then
    scope_txt="user-only"
    user_only_args=(--all-user)
  fi

  echo "[inf] ${bench}: cores=${cores} cset=${cset} perf_cpu=${PERF_CPU} scope=${scope_txt} measure=${MEASURE_SECS}s"
  start="$(date +%s)"

  kill_pattern "${pattern}" "TERM"
  sleep 1
  kill_pattern "${pattern}" "KILL"

  cleanup_bench() {
    kill_pid_and_group "${java_pid:-}" "TERM"
    kill_pid_and_group "${runner_pid:-}" "TERM"
    sleep 2
    kill_pid_and_group "${java_pid:-}" "KILL"
    kill_pid_and_group "${runner_pid:-}" "KILL"
    kill_pattern "${pattern}" "TERM"
    sleep 1
    kill_pattern "${pattern}" "KILL"
  }

  local baseline_pids
  baseline_pids="$(pgrep -f "${pattern}" 2>/dev/null | tr '\n' ' ' || true)"

  setsid taskset -c "${cset}" bash -lc "${run_cmd}" > "${log_file}" 2>&1 &
  runner_pid=$!

  if ! java_pid="$(find_new_pid "${pattern}" "${baseline_pids}" "${runner_pid}")"; then
    echo "[warn] ${bench}: unable to detect JVM pid within ${STARTUP_TIMEOUT_SECS}s"
    cleanup_bench
    wait "${runner_pid}" 2>/dev/null || true
    drop_rows_for_key "${bench}" "${cores}"
    elapsed=$(( $(date +%s) - start ))
    echo "${bench},${cores},${cset},${MEASURE_SECS},${SAMPLE_INTERVAL_SECS},0,0,0,0,0,0,0,0,1,${elapsed},${raw_file},${log_file}" >> "${OUT_CSV}"
    rm -f "${raw_file}"
    return 0
  fi

  "${PERF_BIN}" stat --no-big-num -x, -C "${PERF_CPU}" -o "${raw_file}" \
    "${user_only_args[@]}" \
    -e instructions,context-switches -- sleep "${MEASURE_SECS}" &
  perf_pid=$!

  while kill -0 "${perf_pid}" 2>/dev/null; do
    if [[ -d "/proc/${java_pid}/task" ]]; then
      local th
      th="$(ls "/proc/${java_pid}/task" 2>/dev/null | wc -l | tr -d ' ')"
      if [[ -n "${th}" ]]; then
        if [[ "${samples}" -eq 0 ]]; then
          threads_min="${th}"
          threads_max="${th}"
        else
          if (( th < threads_min )); then
            threads_min="${th}"
          fi
          if (( th > threads_max )); then
            threads_max="${th}"
          fi
        fi
        threads_sum=$((threads_sum + th))
        samples=$((samples + 1))
      fi
    fi
    sleep "${SAMPLE_INTERVAL_SECS}"
  done

  set +e
  wait "${perf_pid}"
  perf_rc=$?
  set -e

  # Stop the benchmark after the fixed measurement window and reap descendants.
  cleanup_bench
  wait "${runner_pid}" 2>/dev/null || true

  local inst_count ctx_count
  read -r inst_count ctx_count <<<"$(parse_perf_counts "${raw_file}")"

  local threads_avg per_core ctx_per_minst final_rc
  if [[ "${samples}" -gt 0 ]]; then
    threads_avg="$(awk -v s="${threads_sum}" -v n="${samples}" 'BEGIN{printf "%.6f", s/n}')"
  else
    threads_avg="0"
  fi
  per_core="$(awk -v t="${threads_avg}" -v c="${cores}" 'BEGIN{if(c>0) printf "%.6f", t/c; else print "0"}')"
  ctx_per_minst="$(awk -v c="${ctx_count}" -v i="${inst_count}" 'BEGIN{if(i>0) printf "%.6f", (c*1000000.0)/i; else print "0"}')"

  elapsed=$(( $(date +%s) - start ))
  if awk "BEGIN{exit !(${inst_count} > 0)}" && [[ "${perf_rc}" -eq 0 ]]; then
    final_rc=0
  else
    final_rc=1
  fi

  drop_rows_for_key "${bench}" "${cores}"
  echo "${bench},${cores},${cset},${MEASURE_SECS},${SAMPLE_INTERVAL_SECS},${threads_min},${threads_max},${threads_avg},${per_core},${samples},${inst_count},${ctx_count},${ctx_per_minst},${final_rc},${elapsed},${raw_file},${log_file}" >> "${OUT_CSV}"
  rm -f "${raw_file}"
}

for bench in ${BENCHMARKS}; do
  for cores in ${CORE_COUNTS}; do
    run_one "${bench}" "${cores}"
  done
done

"${PYTHON_BIN}" "${SCRIPT_DIR}/runscript/plot/plot_ctxswitch_thread_scaling.py" \
  --input "${OUT_CSV}" \
  --out-thread "${OUT_PNG_THREAD}" \
  --out-frequency "${OUT_PNG_FREQ}"

echo "[ok] saved ${OUT_CSV}"
echo "[ok] saved ${OUT_PNG_THREAD}"
echo "[ok] saved ${OUT_PNG_FREQ}"
