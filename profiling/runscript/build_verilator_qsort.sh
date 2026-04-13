#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

setup_verilator_env

ROCKET_EMU_DIR="${BENCH_ROOT}/verilator-rocket-qsort/src/rocket-chip/emulator"
VERILATOR_BIN="${TOOLS_ROOT}/verilator/usr/bin/verilator"

require_file "${VERILATOR_BIN}"
require_file "${ROCKET_EMU_DIR}/Makefile"
require_file "${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv"

pushd "${ROCKET_EMU_DIR}" >/dev/null
make -j"${JOBS:-64}" \
  PROJECT=freechips.rocketchip.system \
  CONFIG=freechips.rocketchip.system.DefaultConfig \
  INSTALLED_VERILATOR="${VERILATOR_BIN}"
popd >/dev/null
