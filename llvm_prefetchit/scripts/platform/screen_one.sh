#!/usr/bin/env bash
# screen_one.sh NAME WORKDIR CMD [TIMEOUT_SECONDS]
# One-line L2I-MPKI screen of any command (appends to one CSV/summary in
# results/broad_screen_<date>/), using screen_l2i_mpki.sh's custom mode.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NAME="${1:?name}"; WORKDIR="${2:?workdir}"; CMD="${3:?cmd}"; TO="${4:-${TIMEOUT_SECONDS:-120}}"
export OUT_DIR="${OUT_DIR:-${LLVM_DIR}/results/broad_screen_$(date +%Y%m%d)}"
mkdir -p "${OUT_DIR}"
APPEND=1 BENCHMARKS=custom CUSTOM_NAME="${NAME}" CUSTOM_WORKDIR="${WORKDIR}" CUSTOM_CMD="${CMD}" \
  TIMEOUT_SECONDS="${TO}" RUN_TO_COMPLETION="${RUN_TO_COMPLETION:-0}" CORE="${CORE:-40}" PIN_THREADS="${PIN_THREADS:-0}" \
  bash "${SCRIPT_DIR}/screen_l2i_mpki.sh" > "${OUT_DIR}/${NAME}.screen.log" 2>&1 || true
python3 - "${OUT_DIR}/runs.csv" "${NAME}" <<'PY'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["benchmark"] == sys.argv[2]]
if not rows: print(f"{sys.argv[2]}: no row"); sys.exit()
r = rows[-1]
ins = float(r["instructions"] or 0)
print(f"{sys.argv[2]:28s} status={r['status']:8s} rc={r['rc']:>3s} {float(r['elapsed_s'] or 0):7.1f}s  instr={ins/1e9:8.2f}G  L2I MPKI={float(r['l2i_mpki'] or 0):7.3f}  IPC={float(r['ipc'] or 0):.3f}")
PY
