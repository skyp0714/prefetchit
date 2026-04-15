#!/usr/bin/env bash
set -euo pipefail

LOOP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${LOOP_ROOT}"

source "${LOOP_ROOT}/runscript/bench_common.sh"

CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-QuadMegaBoomConfig}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc --all)}"
SLEEP_SECS="${SLEEP_SECS:-60}"

# Keep defaults conservative: run SPEC workloads but do not rebuild unless requested.
RUN_SPEC_BUILD="${RUN_SPEC_BUILD:-0}"
SYNC_VENV="${SYNC_VENV:-0}"
CTX_CORE_SMALL="${CTX_CORE_SMALL:-1}"
CTX_CORE_LARGE="${CTX_CORE_LARGE:-86}"
THREAD_CORE_COUNTS="${THREAD_CORE_COUNTS:-1 2 4 8 16 32 64 86}"
RESUME_CSV="${RESUME_CSV:-1}"
RESUME_RESULTS="${RESUME_RESULTS:-1}"
CLEAN_RESULTS="${CLEAN_RESULTS:-0}"

AUTO_LOG_DIR="${RESULTS_ROOT}/auto_loop_logs"
mkdir -p "${AUTO_LOG_DIR}"

ts() {
  date '+%F %T'
}

log() {
  echo "[$(ts)] $*"
}

sudo_cmd() {
  if [[ -n "${SUDO_PASSWORD:-}" ]]; then
    printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' "$@"
  else
    sudo "$@"
  fi
}

run_stage_with_retry() {
  local stage="$1"
  local use_sudo="$2"
  local cmd="$3"
  local attempt=0
  local rc=0

  while true; do
    attempt=$((attempt + 1))
    local stage_log="${AUTO_LOG_DIR}/${stage}_attempt${attempt}_$(date +%Y%m%d_%H%M%S).log"
    log "stage=${stage} attempt=${attempt} start"
    log "stage=${stage} cmd=${cmd}"

    set +e
    if [[ "${use_sudo}" == "1" ]]; then
      sudo_cmd bash -lc "cd '${LOOP_ROOT}' && ${cmd}" 2>&1 | tee "${stage_log}"
      rc=${PIPESTATUS[0]}
    else
      bash -lc "cd '${LOOP_ROOT}' && ${cmd}" 2>&1 | tee "${stage_log}"
      rc=${PIPESTATUS[0]}
    fi
    set -e

    if [[ "${rc}" -eq 0 ]]; then
      log "stage=${stage} attempt=${attempt} done"
      return 0
    fi

    log "stage=${stage} attempt=${attempt} failed rc=${rc} (log=${stage_log})"
    log "stage=${stage} retrying after ${SLEEP_SECS}s"
    sleep "${SLEEP_SECS}"
  done
}

ensure_verilator_simulator_ready() {
  local attempt=0
  local emu=""
  local rc=0

  while true; do
    emu="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
    if [[ -n "${emu}" && -x "${emu}" ]]; then
      log "simulator ready: ${emu}"
      return 0
    fi

    if pgrep -af "make .*CONFIG=${CHIPYARD_CONFIG}" >/dev/null 2>&1; then
      log "detected active verilator build for ${CHIPYARD_CONFIG}; waiting ${SLEEP_SECS}s"
      sleep "${SLEEP_SECS}"
      continue
    fi

    attempt=$((attempt + 1))
    local build_log="${AUTO_LOG_DIR}/build_${CHIPYARD_CONFIG}_attempt${attempt}_$(date +%Y%m%d_%H%M%S).log"
    local make_cmd="make -j${BUILD_JOBS} VM_MAKE_JOBS='${BUILD_JOBS}' VM_PARALLEL_BUILDS='${BUILD_JOBS}' CONFIG='${CHIPYARD_CONFIG}' CONFIG_PACKAGE='${CHIPYARD_CONFIG_PACKAGE}'"
    if [[ -n "${VERILATOR_OPT_FLAGS:-}" ]]; then
      make_cmd="${make_cmd} VERILATOR_OPT_FLAGS='${VERILATOR_OPT_FLAGS}'"
    fi

    log "simulator missing; build attempt=${attempt}"
    set +e
    bash -lc "source '${LOOP_ROOT}/runscript/bench_common.sh' && \
      setup_verilator_env && \
      cd '${CHIPYARD_SIM_DIR}' && \
      ${make_cmd}" \
      2>&1 | tee "${build_log}"
    rc=${PIPESTATUS[0]}
    set -e

    if [[ "${rc}" -ne 0 ]]; then
      log "build attempt=${attempt} failed rc=${rc} (log=${build_log}); retrying in ${SLEEP_SECS}s"
      sleep "${SLEEP_SECS}"
      continue
    fi

    log "build attempt=${attempt} returned rc=0; re-checking simulator path"
  done
}

fix_output_ownership_if_needed() {
  if [[ -n "${SUDO_PASSWORD:-}" ]]; then
    sudo_cmd chown -R "$(id -u):$(id -g)" "${LOOP_ROOT}/results" || true
  fi
}

main() {
  log "auto loop start: config=${CHIPYARD_CONFIG} package=${CHIPYARD_CONFIG_PACKAGE}"
  ensure_verilator_simulator_ready

  run_stage_with_retry \
    "ctxswitch_thread_scaling" \
    "0" \
    "CORE_COUNTS='${THREAD_CORE_COUNTS}' RESUME_CSV='${RESUME_CSV}' ./runscript/run_ctxswitch_thread_scaling.sh"

  run_stage_with_retry \
    "ctxswitch_core0_mpki_plot" \
    "0" \
    "CORE_SMALL='${CTX_CORE_SMALL}' CORE_LARGE='${CTX_CORE_LARGE}' ./runscript/run_ctxswitch_core0_mpki.sh"

  run_stage_with_retry \
    "basic_profile_all" \
    "1" \
    "CHIPYARD_CONFIG='${CHIPYARD_CONFIG}' CHIPYARD_CONFIG_PACKAGE='${CHIPYARD_CONFIG_PACKAGE}' RUN_SPEC_BUILD='${RUN_SPEC_BUILD}' SYNC_VENV='${SYNC_VENV}' CTX_CORE_SMALL='${CTX_CORE_SMALL}' CTX_CORE_LARGE='${CTX_CORE_LARGE}' CLEAN_RESULTS='${CLEAN_RESULTS}' RESUME_RESULTS='${RESUME_RESULTS}' ./run_profile_all.sh"

  fix_output_ownership_if_needed
  log "auto loop done"
}

main "$@"
