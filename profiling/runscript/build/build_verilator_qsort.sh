#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/../bench/bench_common.sh"

setup_verilator_env

CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
JOBS="${JOBS:-64}"

if [[ -z "${CHIPYARD_CONFIG}" ]]; then
  echo "[err] CHIPYARD_CONFIG is required." >&2
  echo "[err] Set it to a Chipyard large multi-core BOOM config class (>=2 BOOM cores)." >&2
  echo "[err] Example: CHIPYARD_CONFIG=<your multicore large BOOM config> ./runscript/build/build_verilator_qsort.sh" >&2
  exit 1
fi

require_chipyard_tree

if [[ "${SKIP_BOOM_CONFIG_CHECK:-0}" != "1" ]]; then
  validate_boom_multicore_config "${CHIPYARD_CONFIG}"
fi

pushd "${CHIPYARD_SIM_DIR}" >/dev/null
make -j"${JOBS}" \
  CONFIG="${CHIPYARD_CONFIG}" \
  CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE}"
popd >/dev/null

EMU="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
if [[ -z "${EMU}" ]]; then
  echo "[err] build finished but simulator binary not found for config=${CHIPYARD_CONFIG}" >&2
  echo "[err] looked under ${CHIPYARD_SIM_DIR}/simulator-*-${CHIPYARD_CONFIG}" >&2
  exit 1
fi
echo "[ok] built simulator: ${EMU}"
