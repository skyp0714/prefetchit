#!/usr/bin/env bash
# Stage-2 reference reproduction on Verilator qsort (Chipyard DualMegaBoomAndSingleRocketConfig):
#   traces (3× PEBS+LBR) → PGO RET plan + profile-free static RET plan → pass-injected
#   binaries → same-layout NOP twins → interleaved fixed-work measurement at 3.8 GHz.
#
# Steps are idempotent (each checks its outputs); rerun after a failure. Requires:
#   - baseline simulator built with clang-19 -g (chipyard sims/verilator, see docs/SETUP.md)
#   - benchmarks/chipyard/env.sh sourced (RISCV toolchain, firtool) or RISCV set
#   - sudo MODE=3.8ghz scripts/platform/freeze_platform.sh before STEP=measure
#
#   STEP=all|traces|plans|build|nop|measure  RUN_ID=... REPS=3 MAX_CYCLES=100000 CORE=40
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ROOT="$(cd "${LLVM_DIR}/.." && pwd)"
STATIC_DIR="${ROOT}/static_prefetch"
PROFILING_DIR="${ROOT}/profiling"

STEP="${STEP:-all}"
RUN_ID="${RUN_ID:-verilator_repro_$(date +%Y%m%d)}"
OUT="${OUT:-${LLVM_DIR}/results/${RUN_ID}}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
SOURCE_WORK="${SOURCE_WORK:-${ROOT}/benchmarks/chipyard/sims/verilator}"
RISCV_ROOT="${RISCV:-${ROOT}/benchmarks/chipyard/.conda-env/riscv-tools}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"
TRACE_CORE="${TRACE_CORE:-40}"
TRACE_MAX_CYCLES="${TRACE_MAX_CYCLES:-538240}"
TRACE_RUNS="${TRACE_RUNS:-3}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-60}"
PGO_RET_COV="${PGO_RET_COV:-90}"
STATIC_TOP_K="${STATIC_TOP_K:-1000}"
STATIC_SITE_STRATEGY="${STATIC_SITE_STRATEGY:-callsite}"
STATIC_SITE_BUDGET="${STATIC_SITE_BUDGET:-1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0,64}"
BUILD_JOBS="${BUILD_JOBS:-8}"
MAX_CYCLES="${MAX_CYCLES:-100000}"
REPS="${REPS:-3}"
CORE="${CORE:-40}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
PLUGIN="${LLVM_DIR}/build/PrefetchITPass.so"

TRACES="${OUT}/traces"; PLANS="${OUT}/plans"; RUNS="${OUT}/runs"; BINS="${OUT}/bin"; MEAS="${OUT}/measure"
mkdir -p "${OUT}" "${TRACES}" "${PLANS}" "${RUNS}" "${BINS}" "${MEAS}"
LOG="${OUT}/run.log"
log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
want() { [[ "${STEP}" == all || "${STEP}" == "$1" ]]; }

[[ -x "${BASELINE_BINARY}" ]] || { echo "[err] baseline simulator missing: ${BASELINE_BINARY}" >&2; exit 1; }
[[ -f "${QBIN}" ]] || { echo "[err] qsort.riscv missing: ${QBIN}" >&2; exit 1; }
[[ -f "${PLUGIN}" ]] || { echo "[err] build the pass first: ${PLUGIN}" >&2; exit 1; }

# ---------------------------------------------------------------- traces
trace_dirs=()
for idx in $(seq 1 "${TRACE_RUNS}"); do
  trace_dirs+=("${TRACES}/baseline_qsort_${TRACE_MAX_CYCLES}_trace$(printf '%02d' "${idx}")/l2_miss")
done
if want traces; then
  for td in "${trace_dirs[@]}"; do
    if [[ -s "${td}/lbr_symbolic_dump.txt" ]]; then log "trace reuse ${td}"; continue; fi
    mkdir -p "${td}"
    log "perf record L2I_CODE_RD_MISS+LBR ${TRACE_DURATION_SEC}s core ${TRACE_CORE}: ${td}"
    set +e
    perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 100000 \
      -o "${td}/l2miss_profile.data" -C "${TRACE_CORE}" -- \
      timeout -k 5s "${TRACE_DURATION_SEC}s" taskset -c "${TRACE_CORE}" \
      "${BASELINE_BINARY}" "${QBIN}" "+max-cycles=${TRACE_MAX_CYCLES}" > "${td}/record.log" 2>&1
    set -e
    [[ -s "${td}/l2miss_profile.data" ]] || { echo "[err] no perf data in ${td}" >&2; exit 1; }
    bash "${PROFILING_DIR}/analyze_pebs_trace.sh" --data "${td}/l2miss_profile.data" --out-dir "${td}" \
      --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary "${BASELINE_BINARY}" >> "${LOG}" 2>&1
    [[ -s "${td}/lbr_symbolic_dump.txt" ]] || { echo "[err] trace symbolisation failed: ${td}" >&2; exit 1; }
    log "trace samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' "${td}/trace_summary.md")"
  done
fi
trace_args=(); for td in "${trace_dirs[@]}"; do trace_args+=(--trace-dir "${td}"); done

# ---------------------------------------------------------------- plans
PGO_LABEL="pgo_ret_cov${PGO_RET_COV}"
STATIC_LABEL="static_top${STATIC_TOP_K}_${STATIC_SITE_STRATEGY}_b${STATIC_SITE_BUDGET}"
PGO_PLAN="${PLANS}/${PGO_LABEL}.plan.json"
STATIC_PLAN="${PLANS}/${STATIC_LABEL}.plan.json"
if want plans; then
  for td in "${trace_dirs[@]}"; do [[ -s "${td}/lbr_symbolic_dump.txt" ]] || { echo "[err] missing trace ${td}" >&2; exit 1; }; done
  if [[ -s "${PGO_PLAN}" ]]; then log "plan reuse ${PGO_PLAN}"; else
    log "PGO RET plan cov${PGO_RET_COV} (trace → plan, the profile-guided reference)"
    python3 "${LLVM_DIR}/tools/prefetchit_trace_to_plan.py" "${trace_args[@]}" --binary "${BASELINE_BINARY}" \
      --top-k 999999 --target-coverage-pct "${PGO_RET_COV}" --depth 24 --depth-min 4 \
      --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 \
      --sample-branch-type-filter RET --allow-unresolved-targets \
      --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
      --summary-dir "${PLANS}/${PGO_LABEL}" --output "${PGO_PLAN}" > "${PLANS}/${PGO_LABEL}.log" 2>&1
  fi
  if [[ -s "${STATIC_PLAN}" ]]; then log "plan reuse ${STATIC_PLAN}"; else
    log "static RET plan top${STATIC_TOP_K} ${STATIC_SITE_STRATEGY} b${STATIC_SITE_BUDGET} (profile-free; traces only score it)"
    python3 "${STATIC_DIR}/tools/static_plan.py" --binary "${BASELINE_BINARY}" --kinds ret \
      --ret-top-k "${STATIC_TOP_K}" --ret-site-strategy "${STATIC_SITE_STRATEGY}" --ret-site-budget "${STATIC_SITE_BUDGET}" \
      --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" "${trace_args[@]}" \
      --out-dir "${PLANS}/${STATIC_LABEL}" --output "${STATIC_PLAN}" --label "${STATIC_LABEL}" > "${PLANS}/${STATIC_LABEL}.log" 2>&1
  fi
  for p in "${PGO_PLAN}" "${STATIC_PLAN}"; do
    log "$(basename "${p}"): $(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d.get('injections',[])), 'injections')" "${p}")"
  done
fi

# ---------------------------------------------------------------- build
variant_bin() { echo "${BINS}/simulator-${CONFIG}-$1"; }
if want build; then
  # BUILD_LABELS="pgo static" (default both) lets two driver instances build in parallel.
  BUILD_LABELS="${BUILD_LABELS:-pgo static}"
  for spec in "pgo:${PGO_LABEL}:${PGO_PLAN}" "static:${STATIC_LABEL}:${STATIC_PLAN}"; do
    kind="${spec%%:*}"; rest="${spec#*:}"; label="${rest%%:*}"; plan="${rest#*:}"
    [[ " ${BUILD_LABELS} " == *" ${kind} "* ]] || continue
    if [[ -x "$(variant_bin "${label}")" ]]; then log "build reuse ${label}"; continue; fi
    [[ -s "${plan}" ]] || { echo "[err] missing plan ${plan}" >&2; exit 1; }
    log "build ${label} through the pass (single-TU clang-19 -O3, VM_PARALLEL_BUILDS=0)"
    RESULT_BASE="${RUNS}" RUN_ID="${label}" BASELINE_BINARY="${BASELINE_BINARY}" SOURCE_WORK="${SOURCE_WORK}" \
    CONFIG="${CONFIG}" EXTERNAL_PLAN="${plan}" PREFETCH_MNEMONIC=prefetcht1 PREFETCH_LABEL="${label}" \
    PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS}" MAX_CYCLES="${MAX_CYCLES}" PROFILE_CORE="${CORE}" \
    BUILD_JOBS="${BUILD_JOBS}" RUN_BASELINE=0 RUN_PROFILE=0 RUN_TRACE=0 CLEAN_WORKDIR=1 \
    OBJDUMP_BIN=llvm-objdump-19 ADDR2LINE_BIN=llvm-addr2line-19 \
      bash "${SCRIPT_DIR}/run_prefetcht1_l2_eval.sh" > "${RUNS}/${label}.build.log" 2>&1 || { echo "[err] build failed: ${RUNS}/${label}.build.log" >&2; exit 1; }
    built="${RUNS}/${label}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${label}"
    # Re-anchor every target on call order in the final binary: symbol+offset
    # targets drift with the codegen changes the injection itself causes.
    resolved="${RUNS}/${label}/plan/${label}.plan.resolved.json"
    [[ -s "${resolved}" ]] || python3 "${LLVM_DIR}/tools/resolve_plan_layout_shift.py" \
      --plan "${RUNS}/${label}/plan/${label}.plan.json" --output "${resolved}" >> "${LOG}" 2>&1
    python3 "${LLVM_DIR}/tools/reanchor_prefetch_targets.py" --baseline "${BASELINE_BINARY}" \
      --binary "${built}" --plan "${resolved}" --output "$(variant_bin "${label}")" 2>&1 | tail -2 | tee -a "${LOG}"
    log "${label}: $(llvm-objdump-19 -d "$(variant_bin "${label}")" | grep -cE 'prefetcht[012]|prefetchnta|prefetchit') prefetch instructions in binary"
    # drift gate: callsite/RET prefetches must land within a cacheline of the real continuation
    # (the next-call heuristic is exact for callsite/RET plans; informative only for LBR-site PGO plans)
    python3 "${LLVM_DIR}/tools/check_prefetch_drift.py" --binary "$(variant_bin "${label}")" --max-pairs 2000 2>&1 | head -1 | tee -a "${LOG}" || true
  done
fi

# ---------------------------------------------------------------- nop twins
if want nop; then
  for label in "${PGO_LABEL}" "${STATIC_LABEL}"; do
    twin="$(variant_bin "${label}_nop")"
    [[ -x "${twin}" ]] && { log "nop reuse ${twin}"; continue; }
    python3 "${LLVM_DIR}/tools/make_nop_control_binary.py" --input "$(variant_bin "${label}")" --output "${twin}" >> "${LOG}" 2>&1
    log "${label}_nop: $(llvm-objdump-19 -d "${twin}" | grep -cE 'prefetcht[012]|prefetchnta') prefetches left (expect 0)"
  done
fi

# ---------------------------------------------------------------- measure
if want measure; then
  "${LLVM_DIR}/scripts/platform/freeze_platform.sh" show || { echo "[err] platform not frozen; run sudo MODE=3.8ghz scripts/platform/freeze_platform.sh" >&2; exit 1; }
  CSV="${MEAS}/runs.csv"
  [[ -s "${CSV}" ]] || printf 'variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,ghz,status\n' > "${CSV}"
  run_one() {
    local variant="$1" rep="$2" bin="$3" dir="${MEAS}/${1}_rep${2}"
    grep -q "^${variant},${rep}," "${CSV}" && return 0
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
    python3 - "${CSV}" "${variant}" "${rep}" "${elapsed}" "${dir}/perf.csv" "${status}" <<'PY'
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
    log "measure ${variant} rep${rep}: ${elapsed}s ${status}"
  }
  # VARIANTS: space-separated labels present in ${BINS} (default: every variant + its NOP twin found there)
  if [[ -z "${VARIANTS:-}" ]]; then
    VARIANTS="$(ls "${BINS}" | sed -n "s/^simulator-${CONFIG}-//p" | grep -v '_unanchored$' | sort | tr '\n' ' ')"
  fi
  log "measuring: base ${VARIANTS}"
  for rep in $(seq 1 "${REPS}"); do
    run_one base "${rep}" "${BASELINE_BINARY}"
    for v in ${VARIANTS}; do
      run_one "${v}" "${rep}" "$(variant_bin "${v}")"
    done
  done
  python3 - "${CSV}" "${MEAS}/summary.md" <<'PY'
import csv, statistics as st, sys
from collections import defaultdict
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["status"] == "ok"]
g = defaultdict(list)
for r in rows: g[r["variant"]].append(r)
med = {v: st.median(float(r["elapsed_sec"]) for r in rs) for v, rs in g.items()}
mpki = {v: st.mean(float(r["l2i_mpki"]) for r in rs) for v, rs in g.items()}
ghz = {v: st.mean(float(r["ghz"]) for r in rs) for v, rs in g.items()}
lines = ["| variant | n | median s | vs base | vs own NOP twin | L2I MPKI | GHz |", "|---|---:|---:|---:|---:|---:|---:|"]
for v in sorted(g, key=lambda x: med[x]):
    twin = v + "_nop"
    vs_twin = f"{med[twin]/med[v]:.4f}x" if twin in med else "-"
    lines.append(f"| {v} | {len(g[v])} | {med[v]:.2f} | {med['base']/med[v]:.4f}x | {vs_twin} | {mpki[v]:.2f} | {ghz[v]:.3f} |")
open(sys.argv[2], "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
PY
fi
log "done: ${OUT}"
