#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/llvm_prefetchit/results/workload_screening/$(date +%Y%m%d_%H%M%S)}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
RUN_TO_COMPLETION="${RUN_TO_COMPLETION:-0}"
CORE="${CORE:-0}"
PIN_THREADS="${PIN_THREADS:-0}"
PIN_INTERVAL_SEC="${PIN_INTERVAL_SEC:-0.05}"
L2_EVENT="${L2_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/}"
BENCHMARKS="${BENCHMARKS:-tailbench_xapian}"
MEASURED_REQS="${MEASURED_REQS:-}"
CONFIG_QPS="${CONFIG_QPS:-}"

mkdir -p "${OUT_DIR}/logs"
RUNS_CSV="${OUT_DIR}/runs.csv"
SUMMARY_MD="${OUT_DIR}/summary.md"
if [[ "${APPEND:-0}" == "1" && -f "${RUNS_CSV}" ]]; then
  :
else
  echo "benchmark,status,rc,elapsed_s,instructions,cycles,l2i_misses,l2i_mpki,ipc,context_switches,cpu_migrations,affinity_core,observed_threads_max,observed_unique_psrs,observed_psr_count,measured_reqs,derived_qps,config_qps,self_metric,workdir,command,perf_csv,log,monitor_log" > "${RUNS_CSV}"
fi

log() {
  printf '[%(%F %T)T] %s\n' -1 "$*" | tee -a "${OUT_DIR}/run.log"
}

expand_core_list() {
  python3 - "$1" <<'PY'
import sys

cores = []
seen = set()
for part in sys.argv[1].split(","):
    part = part.strip()
    if not part:
        continue
    if "-" in part:
        lo_s, hi_s = part.split("-", 1)
        lo, hi = int(lo_s), int(hi_s)
        step = 1 if lo <= hi else -1
        values = range(lo, hi + step, step)
    else:
        values = [int(part)]
    for core in values:
        if core not in seen:
            seen.add(core)
            cores.append(core)
print(" ".join(str(c) for c in cores))
PY
}

profile_command() {
  local name="$1"
  local workdir="$2"
  local command="$3"
  local safe_name="${name//[^A-Za-z0-9_.-]/_}"
  local perf_csv="${OUT_DIR}/logs/${safe_name}.perf.csv"
  local run_log="${OUT_DIR}/logs/${safe_name}.run.log"
  local monitor_log="${OUT_DIR}/logs/${safe_name}.monitor.log"
  local time_file="${OUT_DIR}/logs/${safe_name}.time"
  local start_ns end_ns elapsed rc status metrics instructions cycles l2i ctx migrations mpki ipc observed derived_qps self_metric
  local pin_log="${OUT_DIR}/logs/${safe_name}.pin.log"
  local expanded_cores
  expanded_cores="$(expand_core_list "${CORE}")"

  if [[ "${RUN_TO_COMPLETION}" == "1" ]]; then
    log "profile ${name}: run-to-completion core=${CORE} pin_threads=${PIN_THREADS} measured_reqs=${MEASURED_REQS:-} workdir=${workdir}"
  else
    log "profile ${name}: timeout=${TIMEOUT_SECONDS}s core=${CORE} pin_threads=${PIN_THREADS} workdir=${workdir}"
  fi
  start_ns="$(date +%s%N)"
  set +e
  (
    cd "${workdir}"
    (
      while :; do
        pids="$$"
        frontier="$$"
        while [[ -n "${frontier}" ]]; do
          next=""
          for parent in ${frontier}; do
            children="$(pgrep -P "${parent}" 2>/dev/null || true)"
            if [[ -n "${children}" ]]; then
              next="${next} ${children}"
              pids="${pids} ${children}"
            fi
          done
          frontier="${next}"
        done
        pid_csv="$(tr ' ' ',' <<< "${pids}" | sed 's/^,*//; s/,*$//; s/,,*/,/g')"
        {
          printf '[%(%F %T)T] root=%s descendants=%s\n' -1 "$$" "${pid_csv}"
          ps -eLo pid,tid,psr,comm,args | awk -v pids="${pid_csv}" '
            BEGIN {
              split(pids, c, ",")
              for (i in c) if (c[i] != "") allow[c[i]] = 1
            }
            NR == 1 { print; next }
            allow[$1] { print }
          '
        } >> "${monitor_log}" 2>/dev/null
        sleep 0.5
      done
    ) &
    monitor_pid=$!
    pinner_pid=""
    if [[ "${PIN_THREADS}" == "1" ]]; then
      (
        declare -A tid_to_core=()
        next_core_idx=0
        read -r -a pin_cores <<< "${expanded_cores}"
        ignored_re='^(perf|taskset|sleep|ps|awk|pgrep|sed|tr|tee|time|python3?)$'
        wrapper_re='^(timeout|bash|sh)$'
        if [[ "${#pin_cores[@]}" -eq 0 ]]; then
          echo "[err] no cores parsed from CORE=${CORE}" >> "${pin_log}"
          exit 1
        fi
        while :; do
          pids="$$"
          frontier="$$"
          while [[ -n "${frontier}" ]]; do
            next=""
            for parent in ${frontier}; do
              children="$(pgrep -P "${parent}" 2>/dev/null || true)"
              if [[ -n "${children}" ]]; then
                next="${next} ${children}"
                pids="${pids} ${children}"
              fi
            done
            frontier="${next}"
          done
          pid_csv="$(tr ' ' ',' <<< "${pids}" | sed 's/^,*//; s/,*$//; s/,,*/,/g')"
          while read -r pid tid comm; do
            [[ -n "${tid}" ]] || continue
            if [[ "${comm}" =~ ${ignored_re} ]]; then
              continue
            fi
            if [[ "${comm}" =~ ${wrapper_re} ]]; then
              core="${pin_cores[0]}"
              if [[ -z "${tid_to_core[${tid}]:-}" ]]; then
                tid_to_core["${tid}"]="${core}"
                printf '[%(%F %T)T] assign-wrapper tid=%s pid=%s comm=%s core=%s\n' -1 "${tid}" "${pid}" "${comm}" "${core}" >> "${pin_log}"
              fi
            else
              core="${tid_to_core[${tid}]:-}"
            fi
            if [[ -z "${core}" ]]; then
              core="${pin_cores[$((next_core_idx % ${#pin_cores[@]}))]}"
              tid_to_core["${tid}"]="${core}"
              next_core_idx=$((next_core_idx + 1))
              printf '[%(%F %T)T] assign tid=%s pid=%s comm=%s core=%s\n' -1 "${tid}" "${pid}" "${comm}" "${core}" >> "${pin_log}"
            fi
            taskset -pc "${core}" "${tid}" >/dev/null 2>&1 || true
          done < <(ps -eLo pid,tid,comm,args 2>/dev/null | awk -v pids="${pid_csv}" '
            BEGIN {
              split(pids, c, ",")
              for (i in c) if (c[i] != "") allow[c[i]] = 1
            }
            NR > 1 && allow[$1] { print $1, $2, $3 }
          ')
          sleep "${PIN_INTERVAL_SEC}"
        done
      ) &
      pinner_pid=$!
    fi
    if [[ "${RUN_TO_COMPLETION}" == "1" ]]; then
      /usr/bin/time -f '%e' -o "${time_file}" \
        taskset -c "${CORE}" perf stat --no-big-num -x, -o "${perf_csv}" \
          -e "${L2_EVENT},instructions,cycles,context-switches,cpu-migrations" -- \
          bash -lc "${command}"
    else
      /usr/bin/time -f '%e' -o "${time_file}" \
        taskset -c "${CORE}" perf stat --no-big-num -x, -o "${perf_csv}" \
          -e "${L2_EVENT},instructions,cycles,context-switches,cpu-migrations" -- \
          timeout "${TIMEOUT_SECONDS}s" bash -lc "${command}"
    fi
    rc=$?
    if [[ -n "${pinner_pid}" ]]; then
      kill "${pinner_pid}" >/dev/null 2>&1 || true
      wait "${pinner_pid}" >/dev/null 2>&1 || true
    fi
    kill "${monitor_pid}" >/dev/null 2>&1 || true
    wait "${monitor_pid}" >/dev/null 2>&1 || true
    exit "${rc}"
  ) > "${run_log}" 2>&1
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  elapsed="$(awk -v s="${start_ns}" -v e="${end_ns}" 'BEGIN { printf "%.9f", (e - s) / 1000000000.0 }')"
  [[ -s "${time_file}" ]] && elapsed="$(awk 'NF { v=$NF } END { print v }' "${time_file}")"

  if [[ "${rc}" == "0" ]]; then
    status="ok"
  elif [[ "${rc}" == "124" ]]; then
    status="timeout_ok"
  else
    status="failed"
  fi

  metrics="$(python3 - "${perf_csv}" <<'PY'
import csv
import sys

path = sys.argv[1]
out = {"instructions": "", "cycles": "", "l2i_misses": "", "context_switches": "", "cpu_migrations": ""}
try:
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            event = row[2].strip()
            try:
                value = int(row[0].strip())
            except ValueError:
                continue
            if event == "instructions":
                out["instructions"] = str(value)
            elif event == "cycles":
                out["cycles"] = str(value)
            elif event == "L2I_CODE_RD_MISS":
                out["l2i_misses"] = str(value)
            elif event == "context-switches":
                out["context_switches"] = str(value)
            elif event == "cpu-migrations":
                out["cpu_migrations"] = str(value)
except FileNotFoundError:
    pass
print(",".join(out[k] for k in ("instructions", "cycles", "l2i_misses", "context_switches", "cpu_migrations")))
PY
)"
  IFS=',' read -r instructions cycles l2i ctx migrations <<< "${metrics}"
  mpki=""
  ipc=""
  if [[ -n "${instructions}" && -n "${l2i}" && "${instructions}" != "0" ]]; then
    mpki="$(awk -v m="${l2i}" -v i="${instructions}" 'BEGIN { printf "%.9f", 1000.0 * m / i }')"
  fi
  if [[ -n "${instructions}" && -n "${cycles}" && "${cycles}" != "0" ]]; then
    ipc="$(awk -v i="${instructions}" -v c="${cycles}" 'BEGIN { printf "%.9f", i / c }')"
  fi
  derived_qps=""
  if [[ -n "${MEASURED_REQS}" && -n "${elapsed}" ]]; then
    derived_qps="$(awk -v r="${MEASURED_REQS}" -v e="${elapsed}" 'BEGIN { if (e > 0) printf "%.6f", r / e }')"
  fi

  self_metric="$(python3 - "${run_log}" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(errors="replace") if Path(sys.argv[1]).exists() else ""
patterns = [
    (r"(?i)throughput[^0-9]*([0-9]+(?:\.[0-9]+)?)", "throughput"),
    (r"(?i)qps[^0-9]*([0-9]+(?:\.[0-9]+)?)", "qps"),
    (r"(?i)requests[/ ]s[^0-9]*([0-9]+(?:\.[0-9]+)?)", "requests_per_s"),
]
for pat, name in patterns:
    m = re.search(pat, text)
    if m:
        print(f"{name}={m.group(1)}")
        break
PY
)"

  observed="$(python3 - "${monitor_log}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
psrs = set()
threads_max = 0
ignored = {
    "perf", "timeout", "taskset", "bash", "sh", "sleep", "ps", "awk", "pgrep",
    "sed", "tr",
}
if path.exists():
    current = 0
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit():
            comm = parts[3]
            if comm not in ignored:
                current += 1
                try:
                    psrs.add(int(parts[2]))
                except ValueError:
                    pass
        elif line.startswith("["):
            threads_max = max(threads_max, current)
            current = 0
    threads_max = max(threads_max, current)
print(f"{threads_max};{','.join(str(x) for x in sorted(psrs))};{len(psrs)}")
PY
)"
  IFS=';' read -r observed_threads observed_psrs observed_psr_count <<< "${observed}"

  python3 - "${RUNS_CSV}" "${name}" "${status}" "${rc}" "${elapsed}" \
    "${instructions}" "${cycles}" "${l2i}" "${mpki}" "${ipc}" "${ctx}" "${migrations}" \
    "${CORE}" "${observed_threads}" "${observed_psrs}" "${observed_psr_count}" \
    "${MEASURED_REQS}" "${derived_qps}" "${CONFIG_QPS}" "${self_metric}" "${workdir}" \
    "${command}" "${perf_csv}" "${run_log}" "${monitor_log}" <<'PY'
import csv
import sys

csv_path = sys.argv[1]
row = sys.argv[2:]
with open(csv_path, "a", newline="") as f:
    csv.writer(f).writerow(row)
PY
}

emit_summary() {
  python3 - "${RUNS_CSV}" "${SUMMARY_MD}" <<'PY'
import csv
import math
import sys
from pathlib import Path

runs = Path(sys.argv[1])
summary = Path(sys.argv[2])
rows = list(csv.DictReader(runs.open()))

def num(row, key):
    try:
        return float(row.get(key, ""))
    except ValueError:
        return float("nan")

rows.sort(key=lambda r: (math.inf if math.isnan(num(r, "l2i_mpki")) else -num(r, "l2i_mpki"), r["benchmark"]))
lines = [
    "# Workload L2I MPKI Screening",
    "",
    "| benchmark | status | elapsed s | measured reqs | derived qps | configured qps | affinity core | observed CPUs | migrations | L2I MPKI | IPC | instructions | L2I misses |",
    "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
]
for r in rows:
    lines.append(
        f"| {r['benchmark']} | {r['status']} | {float(r['elapsed_s']):.3f} | "
        f"{r.get('measured_reqs', '')} | {r.get('derived_qps', '')} | {r.get('config_qps', '')} | "
        f"{r.get('affinity_core', '')} | {r.get('observed_unique_psrs', '')} | "
        f"{r.get('cpu_migrations', '')} | "
        f"{num(r, 'l2i_mpki'):.3f} | {num(r, 'ipc'):.3f} | "
        f"{r['instructions']} | {r['l2i_misses']} |"
    )
summary.write_text("\n".join(lines) + "\n")
PY
}

for bench in ${BENCHMARKS}; do
  case "${bench}" in
    tailbench_xapian)
      profile_command \
        "tailbench_xapian" \
        "${ROOT_DIR}/benchmarks/tailbench/tailbench/xapian" \
        "bash ./run.sh"
      ;;
    tailbench_masstree)
      profile_command \
        "tailbench_masstree" \
        "${ROOT_DIR}/benchmarks/tailbench/tailbench/masstree" \
        "bash ./run.sh"
      ;;
    custom)
      : "${CUSTOM_NAME:?CUSTOM_NAME is required for BENCHMARKS=custom}"
      : "${CUSTOM_WORKDIR:?CUSTOM_WORKDIR is required for BENCHMARKS=custom}"
      : "${CUSTOM_CMD:?CUSTOM_CMD is required for BENCHMARKS=custom}"
      profile_command "${CUSTOM_NAME}" "${CUSTOM_WORKDIR}" "${CUSTOM_CMD}"
      ;;
    *)
      log "unknown benchmark ${bench}"
      ;;
  esac
done

emit_summary
log "done ${SUMMARY_MD}"
