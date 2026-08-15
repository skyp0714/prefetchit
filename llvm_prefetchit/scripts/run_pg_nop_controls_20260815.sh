#!/usr/bin/env bash
# Layout-controlled PostgreSQL follow-ups for paper_goal_20260815:
#  1. Re-run July's exact PGO cov25 prefetch-vs-NOP same-layout experiment in
#     the current machine state (July result: 1.0609x).
#  2. Same-layout NOP control for the static pg_body_top32 variant.
set -uo pipefail

ROOT=/home/hnpark2/prefetchit
LLVM="${ROOT}/llvm_prefetchit"
OUT="${LLVM}/results/paper_goal_20260815"
LOG="${OUT}/campaign.log"
log() { printf '[%(%F %T)T] %s\n' -1 "$*" | tee -a "${LOG}"; }

# wait for any verilator run to finish first (one measurement at a time)
for _ in $(seq 1 120); do
  pgrep -f run_verilator_crosspayload_transfer >/dev/null || break
  sleep 60
done
log "nopctl: verilator idle, starting"

PGO_BIN="${LLVM}/work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/installs/cov25_d8_32_b1_o0/bin/postgres"
PGO_NOP="${PGO_BIN}.nop_control"
STATIC_BIN="${OUT}/postgresql_static/bins_v2/installs/pg_body_top32_b336_d8_o0/bin/postgres"
STATIC_NOP="${STATIC_BIN}.nop_control"

if [[ ! -x "${STATIC_NOP}" ]]; then
  python3 "${LLVM}/tools/make_nop_control_binary.py" \
    --input "${STATIC_BIN}" --output "${STATIC_NOP}" | tee -a "${LOG}"
  chmod +x "${STATIC_NOP}"
fi

run_paired() {
  local base="$1" prefetch="$2" label="$3"
  POSTGRES_BASE="${base}" DURATION=30 WARMUP_DURATION=20 QUERY_MODE=simple \
    CLIENTS=8 REPS=5 \
    bash "${LLVM}/scripts/run_final_postgresql_paired.sh" \
      "${prefetch}" "${OUT}/postgresql_static/paired/${label}" "${label}" \
      >> "${LOG}" 2>&1
  log "nopctl: ${label} rc=$? $(jq -c '.speedup' "${OUT}/postgresql_static/paired/${label}/paired_summary.json" 2>/dev/null)"
}

run_paired "${PGO_NOP}" "${PGO_BIN}" "pgo_cov25_vs_nop_rerun"
run_paired "${STATIC_NOP}" "${STATIC_BIN}" "static_top32_vs_nop"

log "nopctl: complete"
