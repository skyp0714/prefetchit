#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLATEAU_DIR="${PLATEAU_DIR:-}"
if [[ -z "${PLATEAU_DIR}" ]]; then
  PLATEAU_DIR="$(find "${LLVM_PREFETCH_DIR}/results/prefetch_plateau" -maxdepth 1 -type d -name 'plateau*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
fi
if [[ -z "${PLATEAU_DIR}" || ! -d "${PLATEAU_DIR}" ]]; then
  echo "[err] PLATEAU_DIR is required or no plateau dir was found" >&2
  exit 1
fi

EXACT_DIR="${EXACT_DIR:-${PLATEAU_DIR}/exact_best_compare}"
CHECK_INTERVAL_SEC="${CHECK_INTERVAL_SEC:-3600}"
LOG="${PLATEAU_DIR}/final_audit_waiter.log"
STATUS_LOG="${PLATEAU_DIR}/overnight_status.md"
AUDIT_REPORT="${PLATEAU_DIR}/final_prefetch_compare_audit.md"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

append_status() {
  {
    echo
    echo "## $(date '+%F %T') final audit waiter"
    echo
    echo "- compare.done: $([[ -f "${EXACT_DIR}/compare.done" ]] && echo yes || echo no)"
    echo "- finalize.done: $([[ -f "${PLATEAU_DIR}/finalize.done" ]] && echo yes || echo no)"
    echo "- audit report: $([[ -f "${AUDIT_REPORT}" ]] && echo yes || echo no)"
    echo "- exact dir: \`${EXACT_DIR}\`"
  } >> "${STATUS_LOG}"
}

main() {
  log "audit waiter start: exact=${EXACT_DIR} interval=${CHECK_INTERVAL_SEC}s"
  while true; do
    append_status
    if [[ -f "${EXACT_DIR}/compare.done" ]]; then
      log "compare.done found; running final audit"
      if python3 "${LLVM_PREFETCH_DIR}/tools/audit_final_prefetch_compare.py" \
          --exact-dir "${EXACT_DIR}" \
          --out "${AUDIT_REPORT}" \
          | tee -a "${LOG}"; then
        rm -f "${PLATEAU_DIR}/final_prefetch_compare_audit.failed"
        log "audit complete: ${AUDIT_REPORT}"
        exit 0
      fi
      touch "${PLATEAU_DIR}/final_prefetch_compare_audit.failed"
      log "audit failed; will retry after ${CHECK_INTERVAL_SEC}s"
    fi
    sleep "${CHECK_INTERVAL_SEC}"
  done
}

main "$@"
