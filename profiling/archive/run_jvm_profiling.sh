#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/runscript/bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

CORE_SMALL="${CORE_SMALL:-1}"
CORE_LARGE="${CORE_LARGE:-86}"
MAIN_CSV="${MAIN_CSV:-${PROFILING_DIR}/results/benchmark_profiling/csv/main_frontend_all.csv}"
LEGACY_CSV="${LEGACY_CSV:-${PROFILING_DIR}/results/jvm_context_switch/csv/contextswitch_core0_mpki.csv}"
OUT_PNG="${OUT_PNG:-${PROFILING_DIR}/results/jvm_context_switch/png/contextswitch_core0_mpki.png}"

mkdir -p "$(dirname "${OUT_PNG}")"

INPUT_CSV="${MAIN_CSV}"
if [[ ! -s "${INPUT_CSV}" ]]; then
  if [[ -s "${LEGACY_CSV}" ]]; then
    INPUT_CSV="${LEGACY_CSV}"
    echo "[warn] main CSV missing; using legacy CSV ${LEGACY_CSV}"
  else
    echo "[err] no input CSV found. expected ${MAIN_CSV} (or legacy ${LEGACY_CSV})" >&2
    exit 1
  fi
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/runscript/plot/plot_ctxswitch_core0_mpki.py" \
  --input "${INPUT_CSV}" \
  --core-small "${CORE_SMALL}" \
  --core-large "${CORE_LARGE}" \
  --output "${OUT_PNG}"

echo "[ok] saved ${OUT_PNG}"
