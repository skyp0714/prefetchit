#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SPEC_ROOT="${SPEC_ROOT:-${REPO_ROOT}/benchmarks/cpu2026}"
SPEC_CONFIG="${SPEC_CONFIG:-prefetchit-gcc-profile}"
SPEC_SIZE="${SPEC_SIZE:-train}"
SPEC_TUNE="${SPEC_TUNE:-base}"
BUILD_NCPUS="${BUILD_NCPUS:-$(nproc)}"
ITERATIONS="${ITERATIONS:-1}"
PROFILE_CORE="${PROFILE_CORE:-0}"
USE_TASKSET="${USE_TASKSET:-1}"
PERF_BIN="${PERF_BIN:-perf}"
L2_EVENT="${L2_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/}"
RESULTS_BASE="${RESULTS_BASE:-${SCRIPT_DIR}/results/spec_l2_mpki}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
BENCHMARKS="${BENCHMARKS:-}"

usage() {
  cat <<'EOF'
Usage: ./run_spec_singlethread_l2_mpki.sh [options]

Runs SPEC CPU2026 single-thread speed benchmarks (*_s) with perf stat and
summarizes L2I MPKI as L2I_CODE_RD_MISS / instructions * 1000.

Options:
  --spec-root <path>       SPEC CPU2026 root (default: benchmarks/cpu2026)
  --config <name>          SPEC config name without .cfg (default: prefetchit-gcc-profile)
  --size <test|train|ref>  Workload size (default: train)
  --tune <base|peak>       SPEC tune (default: base)
  --build-ncpus <N>        Parallel build jobs passed to runcpu (default: nproc)
  --iterations <N>         perf/specinvoke repetitions per benchmark (default: 1)
  --profile-core <N>       CPU core for taskset pinning (default: 0)
  --use-taskset <0|1>      Pin specinvoke to --profile-core (default: 1)
  --benchmarks <list>      Comma/space separated benchmark list (default: all *_s)
  --results-base <path>    Results base directory
  --run-id <name>          Result subdirectory name (default: timestamp)
  --perf-bin <path>        perf binary (default: perf)
  --l2-event <spec>        perf event for L2 misses
  -h, --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec-root)
      SPEC_ROOT="${2:-}"
      shift 2
      ;;
    --config)
      SPEC_CONFIG="${2:-}"
      shift 2
      ;;
    --size)
      SPEC_SIZE="${2:-}"
      shift 2
      ;;
    --tune)
      SPEC_TUNE="${2:-}"
      shift 2
      ;;
    --build-ncpus)
      BUILD_NCPUS="${2:-}"
      shift 2
      ;;
    --iterations)
      ITERATIONS="${2:-}"
      shift 2
      ;;
    --profile-core)
      PROFILE_CORE="${2:-}"
      shift 2
      ;;
    --use-taskset)
      USE_TASKSET="${2:-}"
      shift 2
      ;;
    --benchmarks)
      BENCHMARKS="${2:-}"
      shift 2
      ;;
    --results-base)
      RESULTS_BASE="${2:-}"
      shift 2
      ;;
    --run-id)
      RUN_ID="${2:-}"
      shift 2
      ;;
    --perf-bin)
      PERF_BIN="${2:-}"
      shift 2
      ;;
    --l2-event)
      L2_EVENT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[err] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "${SPEC_ROOT}" || ! -x "${SPEC_ROOT}/bin/runcpu" || ! -x "${SPEC_ROOT}/bin/specinvoke" ]]; then
  echo "[err] SPEC CPU root is not installed or is incomplete: ${SPEC_ROOT}" >&2
  exit 1
fi
SPEC_ROOT="$(cd "${SPEC_ROOT}" && pwd)"
if [[ ! -f "${SPEC_ROOT}/config/${SPEC_CONFIG}.cfg" ]]; then
  echo "[err] SPEC config not found: ${SPEC_ROOT}/config/${SPEC_CONFIG}.cfg" >&2
  exit 1
fi
if ! [[ "${ITERATIONS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --iterations must be a positive integer" >&2
  exit 1
fi
if ! [[ "${BUILD_NCPUS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --build-ncpus must be a positive integer" >&2
  exit 1
fi
if ! [[ "${PROFILE_CORE}" =~ ^[0-9]+$ ]]; then
  echo "[err] --profile-core must be a non-negative integer" >&2
  exit 1
fi
if [[ "${USE_TASKSET}" != "0" && "${USE_TASKSET}" != "1" ]]; then
  echo "[err] --use-taskset must be 0 or 1" >&2
  exit 1
fi

if [[ -n "${BENCHMARKS}" ]]; then
  read -r -a BENCH_ARRAY <<<"$(printf '%s\n' "${BENCHMARKS}" | tr ',' ' ')"
else
  mapfile -t BENCH_ARRAY < <(find "${SPEC_ROOT}/benchspec/CPU" -maxdepth 1 -mindepth 1 -type d -name '*_s' -printf '%f\n' | sort)
fi
if [[ "${#BENCH_ARRAY[@]}" -eq 0 ]]; then
  echo "[err] no SPEC speed benchmarks found. Use --benchmarks to override." >&2
  exit 1
fi

mkdir -p "${RESULTS_BASE}"
RESULTS_BASE="$(cd "${RESULTS_BASE}" && pwd)"
RUN_DIR="${RESULTS_BASE}/${RUN_ID}"
LOG_DIR="${RUN_DIR}/logs"
PERF_DIR="${RUN_DIR}/perf"
mkdir -p "${LOG_DIR}" "${PERF_DIR}"

MANIFEST="${RUN_DIR}/runs.csv"
SUMMARY_CSV="${RUN_DIR}/summary.csv"
SUMMARY_MD="${RUN_DIR}/summary.md"

cat >"${RUN_DIR}/metadata.txt" <<EOF
spec_root=${SPEC_ROOT}
spec_config=${SPEC_CONFIG}
spec_size=${SPEC_SIZE}
spec_tune=${SPEC_TUNE}
build_ncpus=${BUILD_NCPUS}
iterations=${ITERATIONS}
profile_core=${PROFILE_CORE}
use_taskset=${USE_TASKSET}
l2_event=${L2_EVENT}
benchmarks=${BENCH_ARRAY[*]}
EOF

echo "benchmark,iteration,status,rc,run_dir,perf_raw,log,start_ns,end_ns" >"${MANIFEST}"

find_latest_run_dir() {
  local bench="$1"
  local marker="$2"
  local bench_run_root="${SPEC_ROOT}/benchspec/CPU/${bench}/run"
  local found=""
  if [[ -d "${bench_run_root}" ]]; then
    found="$(find "${bench_run_root}" -type f -name speccmds.cmd -newer "${marker}" -printf '%T@ %h\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2- || true)"
    if [[ -z "${found}" ]]; then
      found="$(find "${bench_run_root}" -type f -name speccmds.cmd -printf '%T@ %h\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2- || true)"
    fi
  fi
  printf '%s\n' "${found}"
}

csv_escape() {
  local value="${1//\"/\"\"}"
  printf '"%s"' "${value}"
}

append_manifest_row() {
  local bench="$1"
  local iteration="$2"
  local status="$3"
  local rc="$4"
  local spec_run_dir="$5"
  local perf_raw="$6"
  local log_file="$7"
  local start_ns="$8"
  local end_ns="$9"

  {
    csv_escape "${bench}"
    printf ',%s,' "${iteration}"
    csv_escape "${status}"
    printf ',%s,' "${rc}"
    csv_escape "${spec_run_dir}"
    printf ','
    csv_escape "${perf_raw}"
    printf ','
    csv_escape "${log_file}"
    printf ',%s,%s\n' "${start_ns}" "${end_ns}"
  } >>"${MANIFEST}"
}

cd "${SPEC_ROOT}"
source shrc >/dev/null

echo "[info] results: ${RUN_DIR}"
echo "[info] benchmarks (${#BENCH_ARRAY[@]}): ${BENCH_ARRAY[*]}"

for bench in "${BENCH_ARRAY[@]}"; do
  echo "[info] setting up ${bench}"
  marker="${RUN_DIR}/${bench}.marker"
  : >"${marker}"
  setup_log="${LOG_DIR}/${bench}.runsetup.log"

  set +e
  runcpu \
    --config="${SPEC_CONFIG}" \
    --define "build_ncpus=${BUILD_NCPUS}" \
    --copies=1 \
    --threads=1 \
    --iterations=1 \
    --tune="${SPEC_TUNE}" \
    --size="${SPEC_SIZE}" \
    --noreportable \
    --action=runsetup \
    "${bench}" >"${setup_log}" 2>&1
  setup_rc=$?
  set -e

  if [[ "${setup_rc}" -ne 0 ]]; then
    echo "[warn] runsetup failed for ${bench}; see ${setup_log}" >&2
    append_manifest_row "${bench}" 0 "runsetup_failed" "${setup_rc}" "" "" "${setup_log}" "$(date +%s%N)" "$(date +%s%N)"
    continue
  fi

  spec_run_dir="$(find_latest_run_dir "${bench}" "${marker}")"
  if [[ -z "${spec_run_dir}" || ! -f "${spec_run_dir}/speccmds.cmd" ]]; then
    echo "[warn] speccmds.cmd not found for ${bench}" >&2
    append_manifest_row "${bench}" 0 "speccmds_missing" 1 "${spec_run_dir}" "" "${setup_log}" "$(date +%s%N)" "$(date +%s%N)"
    continue
  fi

  for iter in $(seq 1 "${ITERATIONS}"); do
    perf_raw="${PERF_DIR}/${bench}.iter${iter}.perf.csv"
    run_log="${LOG_DIR}/${bench}.iter${iter}.log"
    echo "[info] perf ${bench} iteration ${iter}/${ITERATIONS}"
    start_ns="$(date +%s%N)"
    set +e
    if [[ "${USE_TASKSET}" == "1" ]]; then
      (
        cd "${spec_run_dir}" &&
        "${PERF_BIN}" stat --no-big-num -x, --all-user -o "${perf_raw}" \
          -e "${L2_EVENT},instructions" -- \
          taskset -c "${PROFILE_CORE}" "${SPEC_ROOT}/bin/specinvoke" -E -f speccmds.cmd
      ) >"${run_log}" 2>&1
    else
      (
        cd "${spec_run_dir}" &&
        "${PERF_BIN}" stat --no-big-num -x, --all-user -o "${perf_raw}" \
          -e "${L2_EVENT},instructions" -- \
          "${SPEC_ROOT}/bin/specinvoke" -E -f speccmds.cmd
      ) >"${run_log}" 2>&1
    fi
    rc=$?
    set -e
    end_ns="$(date +%s%N)"
    status="ok"
    if [[ "${rc}" -ne 0 ]]; then
      status="run_failed"
      echo "[warn] perf/specinvoke failed for ${bench} iter ${iter}; see ${run_log}" >&2
    fi
    append_manifest_row "${bench}" "${iter}" "${status}" "${rc}" "${spec_run_dir}" "${perf_raw}" "${run_log}" "${start_ns}" "${end_ns}"
  done
done

python3 - "${MANIFEST}" "${SUMMARY_CSV}" "${SUMMARY_MD}" <<'PY'
import csv
import math
import statistics
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
summary_csv = Path(sys.argv[2])
summary_md = Path(sys.argv[3])

def parse_perf(path):
    l2 = None
    inst = None
    if not path:
        return None, None
    p = Path(path)
    if not p.exists():
        return None, None
    with p.open(newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            value = row[0].strip()
            event = row[2].strip() if len(row) > 2 else ""
            if not value or value.startswith("<"):
                continue
            try:
                number = float(value)
            except ValueError:
                continue
            event_l = event.lower()
            if event == "L2I_CODE_RD_MISS" or "l2" in event_l and "miss" in event_l:
                l2 = number
            elif event == "instructions":
                inst = number
    return l2, inst

rows = list(csv.DictReader(manifest.open(newline="")))
by_bench = {}
for row in rows:
    by_bench.setdefault(row["benchmark"], []).append(row)

out_rows = []
for bench in sorted(by_bench):
    bench_rows = by_bench[bench]
    ok = []
    statuses = []
    for row in bench_rows:
        statuses.append(row["status"])
        if row["status"] != "ok":
            continue
        l2, inst = parse_perf(row["perf_raw"])
        if l2 is None or inst is None or inst <= 0:
            row["status"] = "parse_failed"
            statuses.append("parse_failed")
            continue
        start_ns = int(row["start_ns"]) if row["start_ns"] else 0
        end_ns = int(row["end_ns"]) if row["end_ns"] else 0
        elapsed_s = (end_ns - start_ns) / 1e9 if end_ns >= start_ns else math.nan
        ok.append({
            "l2": l2,
            "instructions": inst,
            "mpki": 1000.0 * l2 / inst,
            "elapsed_s": elapsed_s,
            "run_dir": row["run_dir"],
        })
    status = "ok" if ok and all(r["status"] == "ok" for r in bench_rows if r["iteration"] != "0") else ";".join(sorted(set(statuses)))
    if ok:
        mpkis = [x["mpki"] for x in ok]
        l2s = [x["l2"] for x in ok]
        insts = [x["instructions"] for x in ok]
        elapsed = [x["elapsed_s"] for x in ok if not math.isnan(x["elapsed_s"])]
        run_dir = ok[-1]["run_dir"]
        out_rows.append({
            "benchmark": bench,
            "status": status,
            "iterations_ok": len(ok),
            "elapsed_mean_s": statistics.fmean(elapsed) if elapsed else "",
            "instructions_mean": statistics.fmean(insts),
            "l2i_misses_mean": statistics.fmean(l2s),
            "l2i_mpki_mean": statistics.fmean(mpkis),
            "l2i_mpki_stdev": statistics.stdev(mpkis) if len(mpkis) > 1 else 0.0,
            "run_dir": run_dir,
        })
    else:
        last = bench_rows[-1]
        out_rows.append({
            "benchmark": bench,
            "status": status,
            "iterations_ok": 0,
            "elapsed_mean_s": "",
            "instructions_mean": "",
            "l2i_misses_mean": "",
            "l2i_mpki_mean": "",
            "l2i_mpki_stdev": "",
            "run_dir": last.get("run_dir", ""),
        })

fieldnames = [
    "benchmark",
    "status",
    "iterations_ok",
    "elapsed_mean_s",
    "instructions_mean",
    "l2i_misses_mean",
    "l2i_mpki_mean",
    "l2i_mpki_stdev",
    "run_dir",
]
with summary_csv.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)

def fmt_float(v, digits=3):
    if v == "":
        return ""
    return f"{float(v):.{digits}f}"

def fmt_int(v):
    if v == "":
        return ""
    return str(int(round(float(v))))

with summary_md.open("w") as f:
    f.write("| benchmark | status | ok iters | elapsed s | instructions | L2I misses | L2I MPKI |\n")
    f.write("|---|---:|---:|---:|---:|---:|---:|\n")
    for row in out_rows:
        f.write(
            "| {benchmark} | {status} | {iterations_ok} | {elapsed} | {inst} | {l2} | {mpki} |\n".format(
                benchmark=row["benchmark"],
                status=row["status"],
                iterations_ok=row["iterations_ok"],
                elapsed=fmt_float(row["elapsed_mean_s"]),
                inst=fmt_int(row["instructions_mean"]),
                l2=fmt_int(row["l2i_misses_mean"]),
                mpki=fmt_float(row["l2i_mpki_mean"]),
            )
        )

print(f"[info] wrote {summary_csv}")
print(f"[info] wrote {summary_md}")
PY

cat "${SUMMARY_MD}"
