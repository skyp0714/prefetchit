#!/usr/bin/env bash
# Interleaved fixed-work measurement of Verilator variant binaries (any payload).
#   BINS=…/bin PAYLOAD=qsort VARIANTS="a a_nop b b_nop" REPS=3 MAX_CYCLES=100000 CORE=40 OUT_CSV=…/runs.csv
#     measure_verilator_variants.sh
# Same columns/summary as run_verilator_repro.sh STEP=measure; the baseline
# simulator is always measured as `base`. Requires the frozen platform.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"; ROOT="$(cd "${LLVM_DIR}/.." && pwd)"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
RISCV_ROOT="${RISCV:-${ROOT}/benchmarks/chipyard/.conda-env/riscv-tools}"
PAYLOAD="${PAYLOAD:-qsort}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/${PAYLOAD}.riscv}"
BINS="${BINS:?bin dir}"; VARIANTS="${VARIANTS:?variant labels}"; REPS="${REPS:-3}"; MAX_CYCLES="${MAX_CYCLES:-100000}"; CORE="${CORE:-40}"
OUT_CSV="${OUT_CSV:-$(dirname "${BINS}")/measure_${PAYLOAD}/runs.csv}"
MEAS="$(dirname "${OUT_CSV}")"; mkdir -p "${MEAS}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
log() { echo "[$(date '+%F %T')] $*" | tee -a "${MEAS}/measure.log"; }
"${LLVM_DIR}/scripts/platform/freeze_platform.sh" show || { echo "[err] platform not frozen" >&2; exit 1; }
[[ -f "${QBIN}" ]] || { echo "[err] payload missing ${QBIN}" >&2; exit 1; }
[[ -s "${OUT_CSV}" ]] || printf 'variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,ghz,status\n' > "${OUT_CSV}"
run_one() {
  local variant="$1" rep="$2" bin="$3" dir="${MEAS}/${1}_rep${2}"
  grep -q "^${variant},${rep}," "${OUT_CSV}" && return 0
  [[ -x "${bin}" ]] || { log "missing ${bin}"; return 0; }
  mkdir -p "${dir}"
  local start end elapsed status=ok rc
  start="$(date +%s.%N)"
  set +e
  taskset -c "${CORE}" perf stat -x, -o "${dir}/perf.csv" -e instructions,cycles,"${EVENT}" -- \
    "${bin}" "${QBIN}" "+max-cycles=${MAX_CYCLES}" > "${dir}/sim.log" 2>&1
  rc=$?
  set -e
  end="$(date +%s.%N)"
  elapsed="$(python3 -c "print(f'{${end}-${start}:.3f}')")"
  ((rc != 0)) && ! grep -q timeout "${dir}/sim.log" && status="error_rc${rc}"
  python3 - "${OUT_CSV}" "${variant}" "${rep}" "${elapsed}" "${dir}/perf.csv" "${status}" <<'PY'
import csv, sys
out, variant, rep, elapsed, perf_path, status = sys.argv[1:]
ev = {}
for row in csv.reader(open(perf_path)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins, cyc, miss, el = ev.get("instructions", 0.0), ev.get("cycles", 0.0), ev.get("L2I_CODE_RD_MISS", 0.0), float(elapsed)
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([variant, rep, elapsed, int(ins), int(cyc), int(miss),
        f"{1000*miss/ins if ins else 0:.4f}", f"{ins/cyc if cyc else 0:.4f}", f"{cyc/el/1e9 if el else 0:.4f}", status])
PY
  log "${PAYLOAD} ${variant} rep${rep}: ${elapsed}s ${status}"
}
log "payload=${PAYLOAD} max_cycles=${MAX_CYCLES} reps=${REPS} variants: base ${VARIANTS}"
for rep in $(seq 1 "${REPS}"); do
  run_one base "${rep}" "${BASELINE_BINARY}"
  for v in ${VARIANTS}; do run_one "${v}" "${rep}" "${BINS}/simulator-${CONFIG}-${v}"; done
done
python3 - "${OUT_CSV}" "${MEAS}/summary.md" <<'PY'
import csv, statistics as st, sys
from collections import defaultdict
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["status"] == "ok"]
g = defaultdict(list)
for r in rows: g[r["variant"]].append(r)
med = {v: st.median(float(r["elapsed_sec"]) for r in rs) for v, rs in g.items()}
mpki = {v: st.mean(float(r["l2i_mpki"]) for r in rs) for v, rs in g.items()}
ins = {v: st.mean(float(r["instructions"]) for r in rs) for v, rs in g.items()}
ipc = {v: st.mean(float(r["ipc"]) for r in rs) for v, rs in g.items()}
lines = ["| variant | n | median s | vs base | vs own NOP twin | L2I MPKI | IPC | instr vs base |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
for v in sorted(g, key=lambda x: med[x]):
    twin = v + "_nop"
    vs_twin = f"{med[twin]/med[v]:.4f}x" if twin in med else "-"
    lines.append(f"| {v} | {len(g[v])} | {med[v]:.2f} | {med['base']/med[v]:.4f}x | {vs_twin} | {mpki[v]:.2f} | {ipc[v]:.3f} | {ins[v]/ins['base']:+.2%}".replace('+', '+') + " |")
open(sys.argv[2], "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
PY
