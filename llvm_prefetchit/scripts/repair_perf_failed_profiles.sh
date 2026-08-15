#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

OUT_DIR="${OUT_DIR:?OUT_DIR is required}"
BATCH_DIR="${BATCH_DIR:-${OUT_DIR}/batch_aggressive}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-32}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
SOCKET="${SOCKET:-${LLVM_PREFETCH_DIR}/results/prefetch_watchdog/tmux/prefetch.sock}"
WAIT_SESSION="${WAIT_SESSION:-prefetch_resume8h}"
SUDO_PASSWORD="${SUDO_PASSWORD:-}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
LOG="${OUT_DIR}/repair_perf_failed_profiles.log"

mkdir -p "${OUT_DIR}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

wait_for_main_session() {
  while tmux -S "${SOCKET}" has-session -t "${WAIT_SESSION}" 2>/dev/null; do
    log "waiting for ${WAIT_SESSION} to finish before repair"
    sleep 300
  done
}

ensure_perf_access() {
  local cur
  cur="$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo unknown)"
  if [[ "${cur}" == "-1" ]]; then
    log "perf_event_paranoid already -1"
    return
  fi
  if [[ -z "${SUDO_PASSWORD}" ]]; then
    log "sudo password not provided; cannot lower perf_event_paranoid"
    return
  fi
  log "setting perf_event_paranoid=-1"
  printf '%s\n' "${SUDO_PASSWORD}" | sudo -S sysctl -w kernel.perf_event_paranoid=-1
}

load_trace_inputs() {
  if [[ -n "${TRACE_INPUTS}" ]]; then
    return
  fi
  if [[ -f "${OUT_DIR}/manifest.txt" ]]; then
    TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${OUT_DIR}/manifest.txt")"
  fi
}

repair_failed_rows() {
  local aggregate="${BATCH_DIR}/aggregate.csv"
  if [[ ! -f "${aggregate}" ]]; then
    log "no aggregate found: ${aggregate}"
    return
  fi

  python3 - "${aggregate}" <<'PY' > "${OUT_DIR}/repair_candidates.tsv"
import csv
import sys
from pathlib import Path

aggregate = Path(sys.argv[1])
for row in csv.DictReader(aggregate.open(newline="", encoding="utf-8")):
    if row.get("status") != "fail":
        continue
    run_dir = Path(row.get("run_dir", ""))
    binary = Path(row.get("binary", ""))
    if not binary.is_file():
        continue
    log = Path(str(run_dir) + ".driver.log")
    if not log.is_file() or "perf_event_paranoid setting is 4" not in log.read_text(errors="replace"):
        continue
    print("\t".join([row.get("variant", ""), str(run_dir), str(binary)]))
PY

  if [[ ! -s "${OUT_DIR}/repair_candidates.tsv" ]]; then
    log "no perf-permission failed rows to repair"
    return
  fi

  while IFS=$'\t' read -r variant run_dir binary; do
    [[ -n "${variant}" ]] || continue
    log "repair profile: ${variant}"
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "prefetcht1_qsort_${MAX_CYCLES}" \
      --sim-binary "${binary}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${SCREEN_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" \
      > "${run_dir}/repair_profile.log" 2>&1 || {
        log "repair profile failed: ${variant}; see ${run_dir}/repair_profile.log"
        continue
      }
    python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
      --autotune-dir "${BATCH_DIR}" \
      --variant "${variant}" \
      --run-dir "${run_dir}" \
      --baseline-summary "${BASELINE_SUMMARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --status ok
  done < "${OUT_DIR}/repair_candidates.tsv"
}

rerun_final_compare() {
  load_trace_inputs
  log "rerun final compare after repair"
  PLATEAU_DIR="${OUT_DIR}" \
  OUT_DIR="${OUT_DIR}/exact_best_compare" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh" \
    > "${OUT_DIR}/exact_best_compare.post_repair.driver.log" 2>&1 || {
      log "post-repair final compare failed"
      tail -100 "${OUT_DIR}/exact_best_compare.post_repair.driver.log" | tee -a "${LOG}" || true
      return 1
    }
  python3 "${LLVM_PREFETCH_DIR}/tools/audit_final_prefetch_compare.py" \
    --exact-dir "${OUT_DIR}/exact_best_compare" \
    --out "${OUT_DIR}/final_prefetch_compare_audit.post_repair.md" || true
}

main() {
  log "repair hook start: out=${OUT_DIR}"
  wait_for_main_session
  ensure_perf_access
  repair_failed_rows
  rerun_final_compare || true
  touch "${OUT_DIR}/repair_perf_failed_profiles.done"
  log "repair hook done"
}

main "$@"
