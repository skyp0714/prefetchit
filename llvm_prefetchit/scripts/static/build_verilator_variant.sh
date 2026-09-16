#!/usr/bin/env bash
# Build ONE Verilator variant through the PrefetchIT pass, post-process it and
# make its same-layout NOP twin, so that run_verilator_repro.sh STEP=measure can
# measure it (binaries land in ${OUT}/bin/simulator-${CONFIG}-${LABEL}[_nop]).
#
#   build_verilator_variant.sh LABEL
#     PLAN=/path/plan.json            plan-driven injection (RET/callsite/PGO plans):
#                                     resolve → re-anchor (k-th call) → drift gate
#     SEQ_DISTANCE=1024 SEQ_STRIDE=20 SEQ_LINES=1
#     SEQ_FUNCS='regex' SEQ_EXCLUDE='regex'
#                                     plan-free sequential lookahead (pass -prefetchit-seq-*);
#                                     validated here by operand form + spacing stats
#     both may be combined (plan sites + seq stream); OUT, CONFIG, CORE, BUILD_JOBS as in
#     run_verilator_repro.sh.  Idempotent: skips when ${OUT}/bin/...-${LABEL} exists.
set -euo pipefail
LABEL="${1:?label}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ROOT="$(cd "${LLVM_DIR}/.." && pwd)"
OUT="${OUT:-${LLVM_DIR}/results/static_overhaul_$(date +%Y%m%d)}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
SOURCE_WORK="${SOURCE_WORK:-${ROOT}/benchmarks/chipyard/sims/verilator}"
CORE="${CORE:-40}"
BUILD_JOBS="${BUILD_JOBS:-8}"
PLAN="${PLAN:-}"
RUNS="${OUT}/runs"; BINS="${OUT}/bin"
mkdir -p "${RUNS}" "${BINS}"
LOG="${OUT}/run.log"
log() { echo "[$(date '+%F %T')] [${LABEL}] $*" | tee -a "${LOG}"; }
final="${BINS}/simulator-${CONFIG}-${LABEL}"
twin="${final}_nop"

if [[ -x "${final}" && -x "${twin}" ]]; then log "reuse ${final}"; exit 0; fi

seq_on=0
if [[ -n "${SEQ_DISTANCE:-}" && "${SEQ_DISTANCE}" != 0 ]]; then
  seq_on=1
  export PREFETCHIT_SEQ_DISTANCE="${SEQ_DISTANCE}"
  export PREFETCHIT_SEQ_STRIDE_INSNS="${SEQ_STRIDE:-20}"
  export PREFETCHIT_SEQ_LINES="${SEQ_LINES:-1}"
  export PREFETCHIT_SEQ_FUNCTIONS="${SEQ_FUNCS:-___eval_nba|nba_sequent|nba_comb}"
  export PREFETCHIT_SEQ_EXCLUDE="${SEQ_EXCLUDE:-eval_initial|eval_static|eval_final|_settle|__Vdpi|_debug}"
  [[ -n "${SEQ_MIN_INSNS:-}" ]] && export PREFETCHIT_SEQ_MIN_INSNS="${SEQ_MIN_INSNS}"
fi
if [[ -z "${PLAN}" ]]; then
  ((seq_on)) || { echo "[err] give PLAN= and/or SEQ_DISTANCE=" >&2; exit 1; }
  PLAN="${RUNS}/${LABEL}.empty.plan.json"
  printf '{"schema":"prefetchit.plan.v1","prefetch":{"mnemonic":"prefetcht1","operand":"pc-relative-symbol-offset","byte_offsets":[0]},"injections":[]}\n' > "${PLAN}"
  plan_based=0
else
  [[ -s "${PLAN}" ]] || { echo "[err] missing plan ${PLAN}" >&2; exit 1; }
  plan_based=1
fi

built="${RUNS}/${LABEL}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${LABEL}"
if [[ ! -x "${built}" ]]; then
  log "build (plan=$([[ ${plan_based} == 1 ]] && basename "${PLAN}" || echo none) seq=${seq_on}${seq_on:+ D=${PREFETCHIT_SEQ_DISTANCE:-} K=${PREFETCHIT_SEQ_STRIDE_INSNS:-} L=${PREFETCHIT_SEQ_LINES:-}})"
  RESULT_BASE="${RUNS}" RUN_ID="${LABEL}" BASELINE_BINARY="${BASELINE_BINARY}" SOURCE_WORK="${SOURCE_WORK}" \
  CONFIG="${CONFIG}" EXTERNAL_PLAN="${PLAN}" PREFETCH_MNEMONIC=prefetcht1 PREFETCH_LABEL="${LABEL}" \
  PREFETCH_BYTE_OFFSETS="0,64" MAX_CYCLES=100000 PROFILE_CORE="${CORE}" BUILD_JOBS="${BUILD_JOBS}" \
  RUN_BASELINE=0 RUN_PROFILE=0 RUN_TRACE=0 CLEAN_WORKDIR=1 SKIP_ASM_VALIDATION="$((1 - plan_based))" \
  OBJDUMP_BIN=llvm-objdump-19 ADDR2LINE_BIN=llvm-addr2line-19 \
    bash "${SCRIPT_DIR}/run_prefetcht1_l2_eval.sh" > "${RUNS}/${LABEL}.build.log" 2>&1 || {
      [[ -x "${built}" ]] || { log "BUILD FAILED: ${RUNS}/${LABEL}.build.log"; exit 1; }
      log "build script exited non-zero after producing the binary (see ${RUNS}/${LABEL}.build.log); continuing"; }
  grep -h "prefetchit-inject: injected=\|prefetchit-seq:" "${RUNS}/${LABEL}/build/build_${LABEL}.log" | tail -2 | tee -a "${LOG}"
fi

if ((plan_based)); then
  resolved="${RUNS}/${LABEL}/plan/${LABEL}.plan.resolved.json"
  [[ -s "${resolved}" ]] || python3 "${LLVM_DIR}/tools/resolve_plan_layout_shift.py" \
      --plan "${RUNS}/${LABEL}/plan/${LABEL}.plan.json" --shifts "${RUNS}/${LABEL}/plan/${LABEL}.plan.json.shifts.json" --output "${resolved}" >> "${LOG}" 2>&1
  python3 "${LLVM_DIR}/tools/reanchor_prefetch_targets.py" --baseline "${BASELINE_BINARY}" \
    --binary "${built}" --plan "${resolved}" --output "${final}" 2>&1 | tail -2 | tee -a "${LOG}"
  python3 "${LLVM_DIR}/tools/check_prefetch_drift.py" --binary "${final}" --max-pairs 5000 2>&1 | head -1 | tee -a "${LOG}" || true
else
  cp -f "${built}" "${final}"
fi
log "$(llvm-objdump-19 -d "${final}" | grep -cE 'prefetcht[012]|prefetchnta|prefetchit') prefetch instructions in binary"
if ((seq_on)); then
  python3 - "${final}" "${PREFETCHIT_SEQ_DISTANCE}" <<'PY' 2>&1 | tee -a "${LOG}"
import re, subprocess, sys, statistics as st
binary, dist = sys.argv[1], int(sys.argv[2])
dis = subprocess.run(["llvm-objdump-19", "-d", "--no-show-raw-insn", binary], capture_output=True, text=True).stdout
gaps, last, const_ok, n = [], None, 0, 0
for l in dis.splitlines():
    if l.endswith(">:"):
        last = None; continue
    m = re.match(r"^\s*([0-9a-f]+):\s+(prefetch\w+)\s+(\S+)", l)
    if not m: continue
    a = int(m.group(1), 16); n += 1
    d = re.match(r"^(-?0x[0-9a-f]+|\d+)\(%rip\)$", m.group(3))
    if d and int(d.group(1), 0) == dist: const_ok += 1
    if last is not None and 0 < a - last < 4096: gaps.append(a - last)
    last = a
print(f"seq validation: {n} prefetches, {const_ok} with constant rip+{dist} operand; spacing median={st.median(gaps):.0f} B "
      f"p10={sorted(gaps)[len(gaps)//10]} p90={sorted(gaps)[9*len(gaps)//10]} (n={len(gaps)})")
PY
fi
python3 "${LLVM_DIR}/tools/make_nop_control_binary.py" --input "${final}" --output "${twin}" >> "${LOG}" 2>&1
log "nop twin: $(llvm-objdump-19 -d "${twin}" | grep -cE 'prefetcht[012]|prefetchnta') prefetches left (expect 0)"
log "done ${final}"
