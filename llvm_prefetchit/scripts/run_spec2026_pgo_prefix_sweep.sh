#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_DIR}/.." && pwd)"
SPEC_ROOT="${SPEC_ROOT:-${REPO_ROOT}/benchmarks/cpu2026}"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-spec2026_pgo_prefix_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_DIR}/results/spec2026_pgo_prefix/${RUN_ID}}"
LOG_DIR="${OUT_DIR}/logs"
TRACE_DIR="${OUT_DIR}/traces"
PLAN_DIR="${OUT_DIR}/plans"
PROFILE_DIR="${OUT_DIR}/profiles"
mkdir -p "${OUT_DIR}" "${LOG_DIR}" "${TRACE_DIR}" "${PLAN_DIR}" "${PROFILE_DIR}"

BENCHMARKS="${BENCHMARKS:-821.gcc_s 823.llvm_s 853.ns3_s 809.cactus_s}"
COVERAGES="${COVERAGES:-10 25 50 75 100}"
BASE_CONFIG="${BASE_CONFIG:-prefetchit-clang-base}"
PREFETCH_CONFIG="${PREFETCH_CONFIG:-prefetchit-clang-prefetch}"
BASE_LABEL="${BASE_LABEL:-spgobase}"
BUILD_NCPUS="${BUILD_NCPUS:-16}"
PROFILE_CORE="${PROFILE_CORE:-0}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-300}"
TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD:-100000}"
L2_EVENT="${L2_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/}"
TRACE_EVENT="${TRACE_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0,64}"
TOP_K="${TOP_K:-999999}"
DEPTH_MIN="${DEPTH_MIN:-4}"
DEPTH="${DEPTH:-24}"
SITE_BUDGET="${SITE_BUDGET:-8}"
CANDIDATE_POOL="${CANDIDATE_POOL:-0}"
SELECTION_MODE="${SELECTION_MODE:-top-sites}"
SITES_PER_DEPTH="${SITES_PER_DEPTH:-1}"
TARGET_IP_SOURCE="${TARGET_IP_SOURCE:-lbr-to}"
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS:-1}"
PLUGIN="${PLUGIN:-${LLVM_DIR}/build/PrefetchITPass.so}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}"
OBJDUMP_BIN="${OBJDUMP_BIN:-llvm-objdump-19}"
KEEP_PERF_DATA="${KEEP_PERF_DATA:-0}"
CLEAN_SPEC_BUILD="${CLEAN_SPEC_BUILD:-1}"
RESUME="${RESUME:-0}"

RUNS_CSV="${OUT_DIR}/runs.csv"
PLANS_CSV="${OUT_DIR}/plans.csv"
BUILD_CSV="${OUT_DIR}/builds.csv"
SUMMARY_CSV="${OUT_DIR}/summary.csv"
SUMMARY_MD="${OUT_DIR}/summary.md"
LOG="${OUT_DIR}/run.log"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "[err] missing directory: ${path}" >&2
    exit 1
  fi
}

bench_short() {
  printf '%s' "$1" | cut -d. -f1
}

csv_quote() {
  python3 - "$@" <<'PY'
import csv
import sys
writer = csv.writer(sys.stdout)
writer.writerow(sys.argv[1:])
PY
}

append_csv() {
  local file="$1"
  shift
  csv_quote "$@" >> "${file}"
}

run_runcpu() {
  local log_file="$1"
  shift
  (
    cd "${SPEC_ROOT}"
    # shellcheck disable=SC1091
    source ./shrc >/dev/null 2>&1
    "$@"
  ) > "${log_file}" 2>&1
}

build_bench() {
  local config="$1" label="$2" bench="$3" plan="${4:-}"
  local log_file="${LOG_DIR}/build_${bench}_${label}.log"
  log "build ${bench} label=${label} config=${config}"
  local args=(
    runcpu
    --config="${config}"
    --label="${label}"
    --define "build_ncpus=${BUILD_NCPUS}"
    --size=ref
    --tune=base
    --noreportable
    --action=build
    --rebuild
  )
  if [[ -n "${plan}" ]]; then
    args+=(--define "prefetchit_plugin=${PLUGIN}" --define "prefetchit_plan=${plan}")
  fi

  set +e
  run_runcpu "${log_file}" "${args[@]}" "${bench}"
  local rc=$?
  set -e
  if grep -q -E "\\*\\*\\* Error building|Build errors .*\\(.*CE\\)" "${log_file}"; then
    rc=1
  fi
  append_csv "${BUILD_CSV}" "${bench}" "${label}" "${config}" "${plan}" "${rc}" "${log_file}"
  if [[ "${rc}" -ne 0 ]]; then
    log "build failed ${bench} label=${label}; log=${log_file}"
    return "${rc}"
  fi
}

setup_bench() {
  local config="$1" label="$2" bench="$3" plan="${4:-}"
  local log_file="${LOG_DIR}/setup_${bench}_${label}.log"
  log "setup ref run dir ${bench} label=${label}"
  local args=(
    runcpu
    --config="${config}"
    --label="${label}"
    --define "build_ncpus=${BUILD_NCPUS}"
    --size=ref
    --tune=base
    --noreportable
    --action=setup
  )
  if [[ -n "${plan}" ]]; then
    args+=(--define "prefetchit_plugin=${PLUGIN}" --define "prefetchit_plan=${plan}")
  fi

  set +e
  run_runcpu "${log_file}" "${args[@]}" "${bench}"
  local rc=$?
  set -e
  if grep -q -E "\\*\\*\\* Error building|NOTICE: Nothing to run|Build errors .*\\(.*CE\\)" "${log_file}"; then
    rc=1
  fi
  if [[ "${rc}" -ne 0 ]]; then
    log "setup failed ${bench} label=${label}; log=${log_file}"
    return "${rc}"
  fi
}

latest_run_dir() {
  local bench="$1" label="$2"
  find "${SPEC_ROOT}/benchspec/CPU/${bench}/run" \
    -maxdepth 1 -type d -name "run_base_refspeed_${label}.*" \
    -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-
}

find_run_exe() {
  local run_dir="$1" label="$2"
  find "${run_dir}" -maxdepth 1 -type f -perm -111 -name "*_base.${label}" | sort | head -1
}

clean_build_dir() {
  local bench="$1" label="$2"
  if [[ "${CLEAN_SPEC_BUILD}" != "1" ]]; then
    return 0
  fi
  find "${SPEC_ROOT}/benchspec/CPU/${bench}/build" \
    -maxdepth 1 -type d -name "build_base_${label}.*" -print -exec rm -rf {} +
}

lookup_run_row() {
  local bench="$1" kind="$2" coverage="$3"
  if [[ ! -f "${RUNS_CSV}" ]]; then
    return 1
  fi
  python3 - "${RUNS_CSV}" "${bench}" "${kind}" "${coverage}" <<'PY'
import csv
import sys

path, bench, kind, coverage = sys.argv[1:5]
for row in csv.DictReader(open(path, newline="", encoding="utf-8")):
    if row.get("benchmark") == bench and row.get("kind") == kind and row.get("coverage_pct", "") == coverage:
        print(row.get("label", "") + "\t" + row.get("run_dir", ""))
        raise SystemExit(0)
raise SystemExit(1)
PY
}

lookup_plan_path() {
  local bench="$1" coverage="$2"
  if [[ ! -f "${PLANS_CSV}" ]]; then
    return 1
  fi
  python3 - "${PLANS_CSV}" "${bench}" "${coverage}" <<'PY'
import csv
import sys

path, bench, coverage = sys.argv[1:4]
for row in csv.DictReader(open(path, newline="", encoding="utf-8")):
    if row.get("benchmark") == bench and row.get("coverage_pct") == coverage:
        plan = row.get("plan", "")
        if plan:
            print(plan)
            raise SystemExit(0)
raise SystemExit(1)
PY
}

parse_perf_csv() {
  local perf_file="$1"
  python3 - "${perf_file}" <<'PY'
import csv
import re
import sys

path = sys.argv[1]
wanted = {
    "instructions": "instructions",
    "cycles": "cycles",
    "L2I_CODE_RD_MISS": "l2i_misses",
}
out = {"instructions": "", "cycles": "", "l2i_misses": ""}
with open(path, newline="", encoding="utf-8", errors="replace") as f:
    for row in csv.reader(f):
        if len(row) < 3:
            continue
        val = row[0].strip()
        ev = row[2].strip()
        if not val or val.startswith("<"):
            continue
        try:
            num = int(float(val))
        except ValueError:
            continue
        for needle, key in wanted.items():
            if needle in ev:
                out[key] = str(num)
print(",".join(out[k] for k in ("instructions", "cycles", "l2i_misses")))
PY
}

measure_prefix() {
  local bench="$1" label="$2" kind="$3" coverage="$4" run_dir="$5"
  local perf_file="${PROFILE_DIR}/${bench}_${label}.perf.csv"
  local run_log="${PROFILE_DIR}/${bench}_${label}.run.log"
  log "profile ${bench} label=${label} kind=${kind} coverage=${coverage} timeout=${TIMEOUT_SECONDS}s"

  local start_ns end_ns elapsed rc status metrics instructions cycles l2i mpki ipc ips
  start_ns="$(date +%s%N)"
  set +e
  (
    cd "${run_dir}"
    perf stat --no-big-num -x, --all-user -o "${perf_file}" \
      -e "${L2_EVENT},instructions,cycles" -- \
      taskset -c "${PROFILE_CORE}" timeout --kill-after=10s "${TIMEOUT_SECONDS}s" \
      "${SPEC_ROOT}/bin/specinvoke" -E -f speccmds.cmd
  ) > "${run_log}" 2>&1
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  elapsed="$(awk "BEGIN { printf \"%.9f\", (${end_ns} - ${start_ns}) / 1000000000 }")"
  status="ok"
  if [[ "${rc}" -eq 124 ]]; then
    status="timeout_ok"
  elif [[ "${rc}" -ne 0 ]]; then
    status="fail"
  fi

  metrics="$(parse_perf_csv "${perf_file}")"
  IFS=',' read -r instructions cycles l2i <<< "${metrics}"
  mpki=""
  ipc=""
  ips=""
  if [[ -n "${instructions}" && -n "${l2i}" && "${instructions}" != "0" ]]; then
    mpki="$(awk -v m="${l2i}" -v i="${instructions}" 'BEGIN { printf "%.9f", 1000.0*m/i }')"
  fi
  if [[ -n "${instructions}" && -n "${cycles}" && "${cycles}" != "0" ]]; then
    ipc="$(awk -v i="${instructions}" -v c="${cycles}" 'BEGIN { printf "%.9f", i/c }')"
  fi
  if [[ -n "${instructions}" ]]; then
    ips="$(awk -v i="${instructions}" -v e="${elapsed}" 'BEGIN { printf "%.6f", i/e }')"
  fi

  append_csv "${RUNS_CSV}" "${bench}" "${kind}" "${coverage}" "${label}" "${status}" "${rc}" \
    "${elapsed}" "${instructions}" "${cycles}" "${l2i}" "${mpki}" "${ipc}" "${ips}" \
    "${run_dir}" "${perf_file}" "${run_log}"

  if [[ "${status}" == "fail" ]]; then
    log "profile failed ${bench} label=${label}; log=${run_log}"
    return 1
  fi
}

record_trace() {
  local bench="$1" label="$2" run_dir="$3" exe="$4"
  local out_dir="${TRACE_DIR}/${bench}/l2_miss"
  local data_file="${out_dir}/l2miss_profile.data"
  local record_log="${out_dir}/record.log"
  mkdir -p "${out_dir}"
  log "trace ${bench} label=${label} duration=${TRACE_DURATION_SEC}s period=${TRACE_SAMPLE_PERIOD}"
  rm -f "${data_file}"
  set +e
  (
    cd "${run_dir}"
    perf record -e "${TRACE_EVENT}" -b -c "${TRACE_SAMPLE_PERIOD}" -o "${data_file}" -- \
      taskset -c "${PROFILE_CORE}" timeout --kill-after=10s "${TRACE_DURATION_SEC}s" \
      "${SPEC_ROOT}/bin/specinvoke" -E -f speccmds.cmd
  ) > "${record_log}" 2>&1
  local rc=$?
  set -e
  if [[ ! -s "${data_file}" ]]; then
    log "trace failed: missing perf.data for ${bench}; log=${record_log}"
    return 1
  fi
  if [[ "${rc}" -ne 0 && "${rc}" -ne 124 ]]; then
    if ! grep -Eq "Captured and wrote|\\(timeout\\)" "${record_log}"; then
      log "trace failed ${bench} rc=${rc}; log=${record_log}"
      return "${rc}"
    fi
  fi

  PERF_BIN=perf "${PROFILING_DIR}/analyze_pebs_trace.sh" \
    --data "${data_file}" \
    --out-dir "${out_dir}" \
    --event-label "${TRACE_EVENT}" \
    --binary "${exe}" \
    --addr2line-bin "${ADDR2LINE_BIN}" \
    > "${out_dir}/analyze.log" 2>&1

  if [[ "${KEEP_PERF_DATA}" != "1" ]]; then
    rm -f "${data_file}"
  fi
}

generate_plan() {
  local bench="$1" coverage="$2" exe="$3"
  local out_dir="${PLAN_DIR}/${bench}/cov${coverage}"
  local plan="${out_dir}/${PREFETCH_MNEMONIC}.plan.json"
  mkdir -p "${out_dir}"
  echo "[$(date '+%F %T')] plan ${bench} coverage=${coverage}%" | tee -a "${LOG}" >&2
  local extra_args=()
  if [[ "${ALLOW_UNRESOLVED_TARGETS}" == "1" ]]; then
    extra_args+=(--allow-unresolved-targets)
  fi
  python3 "${LLVM_DIR}/tools/prefetchit_trace_to_plan.py" \
    --trace-dir "${TRACE_DIR}/${bench}/l2_miss" \
    --binary "${exe}" \
    --output "${plan}" \
    --summary-dir "${out_dir}" \
    --top-k "${TOP_K}" \
    --target-coverage-pct "${coverage}" \
    --depth-min "${DEPTH_MIN}" \
    --depth "${DEPTH}" \
    --site-budget-per-target "${SITE_BUDGET}" \
    --candidate-pool "${CANDIDATE_POOL}" \
    --selection-mode "${SELECTION_MODE}" \
    --sites-per-depth "${SITES_PER_DEPTH}" \
    --prefetch-mnemonic "${PREFETCH_MNEMONIC}" \
    --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
    --target-ip-source "${TARGET_IP_SOURCE}" \
    "${extra_args[@]}" \
    > "${out_dir}/plan.log" 2>&1
  local injections targets samples
  read -r injections targets samples < <(python3 - "${plan}" <<'PY'
import json
import sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(p.get("injections", [])), p.get("selected_targets", ""), p.get("samples", ""))
PY
)
  append_csv "${PLANS_CSV}" "${bench}" "${coverage}" "${plan}" "${injections}" "${targets}" "${samples}" \
    "${out_dir}/selected_top_targets.csv" "${out_dir}/selected_injection_sites.csv"
  printf '%s\n' "${plan}"
}

objdump_prefetch_count() {
  local exe="$1"
  if ! command -v "${OBJDUMP_BIN}" >/dev/null 2>&1; then
    printf ''
    return 0
  fi
  "${OBJDUMP_BIN}" -d "${exe}" 2>/dev/null | grep -c -E "\\b${PREFETCH_MNEMONIC}\\b" || true
}

summarize() {
  python3 - "${RUNS_CSV}" "${PLANS_CSV}" "${BUILD_CSV}" "${SUMMARY_CSV}" "${SUMMARY_MD}" "${OUT_DIR}" <<'PY'
import csv
import math
import sys
from pathlib import Path

runs_csv, plans_csv, builds_csv, summary_csv, summary_md, out_dir = sys.argv[1:]

def f(x):
    try:
        return float(x)
    except Exception:
        return math.nan

runs = list(csv.DictReader(open(runs_csv, newline="", encoding="utf-8")))
plans = {(r["benchmark"], r["coverage_pct"]): r for r in csv.DictReader(open(plans_csv, newline="", encoding="utf-8"))}
baseline = {r["benchmark"]: r for r in runs if r["kind"] == "baseline"}

rows = []
for r in runs:
    if r["kind"] == "baseline":
        rows.append({
            **r,
            "plan_injections": "",
            "objdump_prefetches": "",
            "runtime_speedup": "",
            "prefix_ips_ratio": "",
            "ipc_ratio": "",
            "l2i_mpki_delta_pct": "",
        })
        continue
    b = baseline.get(r["benchmark"], {})
    bp = plans.get((r["benchmark"], r["coverage_pct"]), {})
    runtime_speedup = ""
    if b.get("status") == "ok" and r.get("status") == "ok":
        be, oe = f(b.get("elapsed_s")), f(r.get("elapsed_s"))
        if be > 0 and oe > 0:
            runtime_speedup = f"{be / oe:.6f}"
    ips_ratio = ""
    bi, oi = f(b.get("insn_per_s")), f(r.get("insn_per_s"))
    if bi > 0 and oi > 0:
        ips_ratio = f"{oi / bi:.6f}"
    ipc_ratio = ""
    bipc, oipc = f(b.get("ipc")), f(r.get("ipc"))
    if bipc > 0 and oipc > 0:
        ipc_ratio = f"{oipc / bipc:.6f}"
    mpki_delta = ""
    bmpki, ompki = f(b.get("l2i_mpki")), f(r.get("l2i_mpki"))
    if bmpki > 0 and not math.isnan(ompki):
        mpki_delta = f"{100.0 * (ompki - bmpki) / bmpki:.6f}"
    rows.append({
        **r,
        "plan_injections": bp.get("injections", ""),
        "runtime_speedup": runtime_speedup,
        "prefix_ips_ratio": ips_ratio,
        "ipc_ratio": ipc_ratio,
        "l2i_mpki_delta_pct": mpki_delta,
    })

fieldnames = [
    "benchmark", "kind", "coverage_pct", "label", "status", "elapsed_s",
    "runtime_speedup", "prefix_ips_ratio", "ipc_ratio",
    "instructions", "cycles", "l2i_misses", "l2i_mpki", "l2i_mpki_delta_pct",
    "plan_injections", "run_dir", "perf_raw", "log",
]
with open(summary_csv, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)

def fmt(x, digits=6):
    y = f(x)
    if math.isnan(y):
        return ""
    return f"{y:.{digits}f}"

lines = []
lines.append("# SPEC2026 PGO Prefetch Prefix Sweep")
lines.append("")
lines.append(f"- Run dir: `{out_dir}`")
lines.append("- Runtime speedup is only filled when both baseline and optimized runs finish before the timeout.")
lines.append("- For timeout-limited rows, use `prefix_ips_ratio`, `ipc_ratio`, and L2I MPKI as fixed-window indicators.")
lines.append("")
for bench in sorted({r["benchmark"] for r in rows}):
    lines.append(f"## {bench}")
    lines.append("")
    lines.append("| coverage | status | elapsed s | runtime speedup | prefix IPS ratio | IPC ratio | L2I MPKI | L2I MPKI delta % | plan injections |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in [x for x in rows if x["benchmark"] == bench]:
        cov = "baseline" if r["kind"] == "baseline" else r["coverage_pct"]
        lines.append(
            "| {cov} | {status} | {elapsed} | {speedup} | {ips} | {ipc} | {mpki} | {delta} | {inj} |".format(
                cov=cov,
                status=r["status"],
                elapsed=fmt(r["elapsed_s"], 3),
                speedup=r.get("runtime_speedup", ""),
                ips=r.get("prefix_ips_ratio", ""),
                ipc=r.get("ipc_ratio", ""),
                mpki=fmt(r["l2i_mpki"], 6),
                delta=r.get("l2i_mpki_delta_pct", ""),
                inj=r.get("plan_injections", ""),
            )
        )
    lines.append("")
Path(summary_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

main() {
  require_dir "${SPEC_ROOT}"
  require_file "${SPEC_ROOT}/shrc"
  require_file "${SPEC_ROOT}/config/${BASE_CONFIG}.cfg"
  require_file "${SPEC_ROOT}/config/${PREFETCH_CONFIG}.cfg"
  require_file "${PLUGIN}"

  if [[ "${RESUME}" == "1" ]]; then
    [[ -f "${RUNS_CSV}" ]] || echo "benchmark,kind,coverage_pct,label,status,rc,elapsed_s,instructions,cycles,l2i_misses,l2i_mpki,ipc,insn_per_s,run_dir,perf_raw,log" > "${RUNS_CSV}"
    [[ -f "${PLANS_CSV}" ]] || echo "benchmark,coverage_pct,plan,injections,targets,samples,targets_csv,sites_csv" > "${PLANS_CSV}"
    [[ -f "${BUILD_CSV}" ]] || echo "benchmark,label,config,plan,rc,log" > "${BUILD_CSV}"
  else
    echo "benchmark,kind,coverage_pct,label,status,rc,elapsed_s,instructions,cycles,l2i_misses,l2i_mpki,ipc,insn_per_s,run_dir,perf_raw,log" > "${RUNS_CSV}"
    echo "benchmark,coverage_pct,plan,injections,targets,samples,targets_csv,sites_csv" > "${PLANS_CSV}"
    echo "benchmark,label,config,plan,rc,log" > "${BUILD_CSV}"
  fi

  log "start ${OUT_DIR}"
  log "benchmarks=${BENCHMARKS}"
  log "coverages=${COVERAGES}"
  log "prefix timeout=${TIMEOUT_SECONDS}s core=${PROFILE_CORE}"
  log "plan params coverage sweep, d=${DEPTH_MIN}-${DEPTH}, budget=${SITE_BUDGET}, mode=${SELECTION_MODE}, offsets=${PREFETCH_BYTE_OFFSETS}, target_ip_source=${TARGET_IP_SOURCE}"

  declare -A baseline_run_dirs
  declare -A baseline_exes

  for bench in ${BENCHMARKS}; do
    local existing row_label row_run_dir row_exe
    if [[ "${RESUME}" == "1" ]] && existing="$(lookup_run_row "${bench}" "baseline" "")"; then
      IFS=$'\t' read -r row_label row_run_dir <<< "${existing}"
      row_exe="$(find_run_exe "${row_run_dir}" "${row_label}" || true)"
      if [[ -n "${row_run_dir}" && -d "${row_run_dir}" && -n "${row_exe}" && -f "${TRACE_DIR}/${bench}/l2_miss/lbr_symbolic_dump.txt" ]]; then
        log "resume baseline ${bench}: ${row_run_dir}"
        baseline_run_dirs["${bench}"]="${row_run_dir}"
        baseline_exes["${bench}"]="${row_exe}"
        continue
      fi
    fi
    build_bench "${BASE_CONFIG}" "${BASE_LABEL}" "${bench}"
    setup_bench "${BASE_CONFIG}" "${BASE_LABEL}" "${bench}"
    local run_dir exe
    run_dir="$(latest_run_dir "${bench}" "${BASE_LABEL}")"
    if [[ -z "${run_dir}" ]]; then
      echo "[err] could not find run dir for ${bench} label=${BASE_LABEL}" >&2
      exit 1
    fi
    exe="$(find_run_exe "${run_dir}" "${BASE_LABEL}")"
    if [[ -z "${exe}" ]]; then
      echo "[err] could not find executable in ${run_dir}" >&2
      exit 1
    fi
    baseline_run_dirs["${bench}"]="${run_dir}"
    baseline_exes["${bench}"]="${exe}"
    measure_prefix "${bench}" "${BASE_LABEL}" "baseline" "" "${run_dir}"
    record_trace "${bench}" "${BASE_LABEL}" "${run_dir}" "${exe}"
    clean_build_dir "${bench}" "${BASE_LABEL}"
  done

  for bench in ${BENCHMARKS}; do
    local short exe
    short="$(bench_short "${bench}")"
    exe="${baseline_exes[${bench}]}"
    for coverage in ${COVERAGES}; do
      local plan label opt_run_dir opt_exe pf_count
      if [[ "${RESUME}" == "1" ]] && plan="$(lookup_plan_path "${bench}" "${coverage}")" && [[ -f "${plan}" ]]; then
        log "resume plan ${bench} coverage=${coverage}: ${plan}"
      else
        plan="$(generate_plan "${bench}" "${coverage}" "${exe}")"
      fi
      label="spgo${short}c${coverage}"
      if [[ "${RESUME}" == "1" ]] && existing="$(lookup_run_row "${bench}" "pgo" "${coverage}")"; then
        IFS=$'\t' read -r row_label row_run_dir <<< "${existing}"
        if [[ -n "${row_run_dir}" && -d "${row_run_dir}" ]]; then
          log "resume profile ${bench} coverage=${coverage}: ${row_run_dir}"
          summarize
          continue
        fi
      fi
      build_bench "${PREFETCH_CONFIG}" "${label}" "${bench}" "${plan}"
      setup_bench "${PREFETCH_CONFIG}" "${label}" "${bench}" "${plan}"
      opt_run_dir="$(latest_run_dir "${bench}" "${label}")"
      if [[ -z "${opt_run_dir}" ]]; then
        echo "[err] could not find optimized run dir for ${bench} label=${label}" >&2
        exit 1
      fi
      opt_exe="$(find_run_exe "${opt_run_dir}" "${label}")"
      if [[ -z "${opt_exe}" ]]; then
        echo "[err] could not find optimized executable in ${opt_run_dir}" >&2
        exit 1
      fi
      pf_count="$(objdump_prefetch_count "${opt_exe}")"
      log "objdump ${bench} label=${label} ${PREFETCH_MNEMONIC}_count=${pf_count}"
      measure_prefix "${bench}" "${label}" "pgo" "${coverage}" "${opt_run_dir}"
      clean_build_dir "${bench}" "${label}"
      summarize
    done
  done

  summarize
  ln -sfn "${OUT_DIR}" "${LLVM_DIR}/results/spec2026_pgo_prefix/latest"
  log "done ${SUMMARY_MD}"
}

main "$@"
