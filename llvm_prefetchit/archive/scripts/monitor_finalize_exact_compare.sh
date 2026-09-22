#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

PLATEAU_DIR="${PLATEAU_DIR:-}"
if [[ -z "${PLATEAU_DIR}" ]]; then
  PLATEAU_DIR="$(find "${LLVM_PREFETCH_DIR}/results/prefetch_plateau" -maxdepth 1 -type d -name 'plateau*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
fi
if [[ -z "${PLATEAU_DIR}" || ! -d "${PLATEAU_DIR}" ]]; then
  echo "[err] PLATEAU_DIR is required or no plateau dir was found" >&2
  exit 1
fi

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-86}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
CHECK_INTERVAL_SEC="${CHECK_INTERVAL_SEC:-3600}"
FINALIZE_SESSION="${FINALIZE_SESSION:-prefetch_finalize_exact}"
LOG="${PLATEAU_DIR}/finalize_guard.log"
STATUS_LOG="${PLATEAU_DIR}/overnight_status.md"

TRACE_INPUTS="${TRACE_INPUTS:-}"
if [[ -z "${TRACE_INPUTS}" && -f "${PLATEAU_DIR}/manifest.txt" ]]; then
  TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${PLATEAU_DIR}/manifest.txt")"
fi
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] TRACE_INPUTS is required or must be present in plateau manifest" | tee -a "${LOG}" >&2
  exit 1
fi

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

append_status() {
  {
    echo
    echo "## $(date '+%F %T') finalize guard"
    echo
    echo "- finalize.done: $([[ -f "${PLATEAU_DIR}/finalize.done" ]] && echo yes || echo no)"
    echo "- repair.done: $([[ -f "${PLATEAU_DIR}/batch_repair/repair.done" ]] && echo yes || echo no)"
    echo "- compare.done: $([[ -f "${PLATEAU_DIR}/exact_best_compare/compare.done" ]] && echo yes || echo no)"
    echo "- disk: $(df -h "${REPO_ROOT}" | awk 'NR==2 {print $4 " free / " $5 " used"}')"
    echo "- tmux ${FINALIZE_SESSION}: $(tmux has-session -t "${FINALIZE_SESSION}" 2>/dev/null && echo alive || echo missing)"
    local proc
    proc="$(ps -eo pid,stat,psr,pcpu,pmem,etime,cmd | grep -E 'run_prefetcht1|run_prefetch_scheme|run_detailed_profile|perf stat|simulator-chipyard|clang\\+\\+-19|make -f VTestDriver' | grep -v grep | head -8 || true)"
    if [[ -n "${proc}" ]]; then
      echo
      echo '```'
      echo "${proc}"
      echo '```'
    fi
  } >> "${STATUS_LOG}"
}

start_finalize_session() {
  log "starting ${FINALIZE_SESSION}"
  tmux new-session -d -s "${FINALIZE_SESSION}" \
    "cd '${REPO_ROOT}' && PLATEAU_DIR='${PLATEAU_DIR}' TRACE_INPUTS='${TRACE_INPUTS}' CONFIG='${CONFIG}' MAX_CYCLES='${MAX_CYCLES}' PROFILE_CORE='${PROFILE_CORE}' SCREEN_ITERATIONS='${SCREEN_ITERATIONS}' FINAL_ITERATIONS='${FINAL_ITERATIONS}' BUILD_JOBS='${BUILD_JOBS}' RUN_RESIDUAL_TRACE='${RUN_RESIDUAL_TRACE}' '${SCRIPT_DIR}/finalize_plateau_exact_compare.sh'"
}

latest_errors() {
  find "${PLATEAU_DIR}" -maxdepth 4 -type f \( -name '*.log' -o -name '*.driver.log' \) -mmin -180 -print0 2>/dev/null \
    | xargs -0 grep -nE '(^|[^[:alpha:]])(ERROR|Error|error:|failed|FAILED|Traceback|Segmentation fault|Killed)([^[:alpha:]]|$)' 2>/dev/null \
    | tail -40 || true
}

main() {
  log "guard start: plateau=${PLATEAU_DIR} interval=${CHECK_INTERVAL_SEC}s"
  while true; do
    append_status
    if [[ -f "${PLATEAU_DIR}/finalize.done" ]]; then
      log "finalize.done found; guard exiting"
      exit 0
    fi

    if ! tmux has-session -t "${FINALIZE_SESSION}" 2>/dev/null; then
      log "${FINALIZE_SESSION} missing before finalize.done"
      local errs
      errs="$(latest_errors)"
      if [[ -n "${errs}" ]]; then
        log "recent error snippets before restart:"
        echo "${errs}" >> "${LOG}"
      fi
      start_finalize_session
    else
      log "${FINALIZE_SESSION} alive"
    fi

    sleep "${CHECK_INTERVAL_SEC}"
  done
}

main "$@"
