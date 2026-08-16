#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"
BENCH_COMMON="${PROFILING_DIR}/runscript/bench/bench_common.sh"

RESULT_BASE="${RESULT_BASE:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${RESULT_BASE}/${RUN_ID}"
TRACE_INPUT="${TRACE_INPUT:-${PROFILING_DIR}/results/trace/verilator-qsort-highrate/l2_miss}"
TRACE_INPUTS="${TRACE_INPUTS:-${TRACE_INPUT}}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
TOP_K="${TOP_K:-10}"
TARGET_COVERAGE_PCT="${TARGET_COVERAGE_PCT:-0}"
DEPTH="${DEPTH:-16}"
DEPTH_MIN="${DEPTH_MIN:-1}"
SITE_BUDGET="${SITE_BUDGET:-10}"
CANDIDATE_POOL="${CANDIDATE_POOL:-1000}"
SELECTION_MODE="${SELECTION_MODE:-greedy}"
SITES_PER_DEPTH="${SITES_PER_DEPTH:-1}"
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS:-0}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0}"
BRANCH_DEPTH_POLICY="${BRANCH_DEPTH_POLICY:-}"
BRANCH_TYPE_FILTER="${BRANCH_TYPE_FILTER:-}"
SAMPLE_BRANCH_TYPE_FILTER="${SAMPLE_BRANCH_TYPE_FILTER:-}"
TARGET_IP_SOURCE="${TARGET_IP_SOURCE:-lbr-to}"
EXTERNAL_PLAN="${EXTERNAL_PLAN:-}"
PREFETCH_LABEL="${PREFETCH_LABEL:-${PREFETCH_MNEMONIC}}"
PREFETCH_LABEL="$(printf '%s' "${PREFETCH_LABEL}" | tr -c 'A-Za-z0-9_-' '_')"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PROFILE_CORE="${PROFILE_CORE:-0}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-60}"
# FRONTEND_RETIRED.L2_MISS is listed by ocperf on Granite Rapids, but this
# kernel/perf combination reports it as unsupported for stat/record. Use the
# validated L2 instruction-miss event for LBR trace collection by default.
TRACE_EVENT_L2="${TRACE_EVENT_L2:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp}"
TRACE_USE_OCPERF="${TRACE_USE_OCPERF:-0}"
TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD:-100000}"
TRACE_PERF_SCOPE="${TRACE_PERF_SCOPE:-cpu}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
CLANG_CXX="${CLANG_CXX:-clang++-19}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}"
OBJDUMP_BIN="${OBJDUMP_BIN:-objdump}"
RUN_BASELINE="${RUN_BASELINE:-1}"
RUN_TRACE="${RUN_TRACE:-1}"
RUN_PROFILE="${RUN_PROFILE:-1}"
CLEAN_WORKDIR="${CLEAN_WORKDIR:-0}"

PLUGIN="${LLVM_PREFETCH_DIR}/build/PrefetchITPass.so"
PLAN="${OUT_DIR}/plan/${PREFETCH_LABEL}.plan.json"
PLAN_SUMMARY="${OUT_DIR}/plan"
WORK_DIR="${OUT_DIR}/work/verilator_${PREFETCH_LABEL}"
MODEL_DIR="${WORK_DIR}/generated-src/chipyard.harness.TestHarness.${CONFIG}/chipyard.harness.TestHarness.${CONFIG}"
SIM_OUT="${WORK_DIR}/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
FINAL_SIM="${OUT_DIR}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
BUILD_LOG="${OUT_DIR}/build/build_${PREFETCH_LABEL}.log"
ASM_DIR="${OUT_DIR}/assembly_validation"
DETAIL_BASE="${OUT_DIR}/detailed_profile"
TRACE_BASE="${OUT_DIR}/trace_l2i_code_rd_miss_precise"
SUMMARY_MD="${OUT_DIR}/final_summary.md"

mkdir -p "${OUT_DIR}" "${OUT_DIR}/build" "${OUT_DIR}/bin" "${PLAN_SUMMARY}" "${ASM_DIR}" "${DETAIL_BASE}" "${TRACE_BASE}"

log() {
  echo "[$(date '+%F %T')] $*"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "[err] missing directory: ${path}" >&2
    exit 1
  fi
}

build_trace_args() {
  TRACE_ARGS=()
  IFS=':' read -r -a _trace_dirs <<< "${TRACE_INPUTS}"
  for trace_dir in "${_trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    require_dir "${trace_dir}"
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
    TRACE_ARGS+=(--trace-dir "${trace_dir}")
  done
  if [[ "${#TRACE_ARGS[@]}" -eq 0 ]]; then
    echo "[err] TRACE_INPUTS did not contain any trace directories" >&2
    exit 1
  fi
}

parse_summary_metric() {
  local csv="$1"
  local metric="$2"
  awk -F, -v m="${metric}" 'NR>1 && $1==m {print $2; exit}' "${csv}"
}

trace_samples_from_summary() {
  local md="$1"
  awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' "${md}" 2>/dev/null || true
}

trace_top_from_summary() {
  local md="$1"
  awk -F'`' '/Top miss target function/ {print $2; exit}' "${md}" 2>/dev/null || true
}

build_final_summary() {
  local baseline_summary="${DETAIL_BASE}/baseline_qsort_${MAX_CYCLES}/summary.csv"
  local opt_summary="${DETAIL_BASE}/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/summary.csv"
  local baseline_trace="${TRACE_BASE}/baseline_qsort_${MAX_CYCLES}/l2_miss/trace_summary.md"
  local opt_trace="${TRACE_BASE}/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/l2_miss/trace_summary.md"
  local asm_md="${ASM_DIR}/prefetch_asm_validation.md"

  {
    echo "# ${PREFETCH_LABEL} LLVM Pass L2 Evaluation"
    echo
    echo "- Run dir: \`${OUT_DIR}\`"
    echo "- Baseline binary: \`${BASELINE_BINARY}\`"
    echo "- Optimized binary: \`${FINAL_SIM}\`"
    echo "- Plan: \`${PLAN}\`"
    echo "- Prefetch byte offsets: \`${PREFETCH_BYTE_OFFSETS}\`"
    echo "- Max cycles: ${MAX_CYCLES}"
    echo "- Profile iterations: ${PROFILE_ITERATIONS}"
    echo "- Profile core: ${PROFILE_CORE}"
    echo
    echo "## Assembly Validation"
    echo
    if [[ -f "${asm_md}" ]]; then
      sed -n '1,32p' "${asm_md}"
    else
      echo "- Missing assembly validation."
    fi
    echo
    echo "## L2 MPKI"
    echo
    echo "| Binary | Runtime mean (s) | L2I MPKI mean | Instructions mean |"
    echo "|---|---:|---:|---:|"
    if [[ -f "${baseline_summary}" ]]; then
      echo "| baseline | $(parse_summary_metric "${baseline_summary}" elapsed_sec) | $(parse_summary_metric "${baseline_summary}" l2i_mpki) | $(parse_summary_metric "${baseline_summary}" instructions) |"
    fi
    if [[ -f "${opt_summary}" ]]; then
      echo "| ${PREFETCH_LABEL} | $(parse_summary_metric "${opt_summary}" elapsed_sec) | $(parse_summary_metric "${opt_summary}" l2i_mpki) | $(parse_summary_metric "${opt_summary}" instructions) |"
    fi
    if [[ -f "${baseline_summary}" && -f "${opt_summary}" ]]; then
      python3 - <<'PY' "${baseline_summary}" "${opt_summary}"
import csv, sys
def rd(path):
    return {r["metric"]: float(r["mean"]) for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}
b, o = rd(sys.argv[1]), rd(sys.argv[2])
for metric in ("elapsed_sec", "l2i_mpki", "instructions"):
    bv, ov = b[metric], o[metric]
    pct = 100.0 * (ov - bv) / bv if bv else 0.0
    print(f"- {metric} delta: {ov-bv:.6f} ({pct:+.4f}%)")
PY
    fi
    echo
    echo "## L2 Trace"
    echo
    echo "| Binary | LBR samples | Top target |"
    echo "|---|---:|---|"
    if [[ -f "${baseline_trace}" ]]; then
      echo "| baseline | $(trace_samples_from_summary "${baseline_trace}") | \`$(trace_top_from_summary "${baseline_trace}")\` |"
    fi
    if [[ -f "${opt_trace}" ]]; then
      echo "| ${PREFETCH_LABEL} | $(trace_samples_from_summary "${opt_trace}") | \`$(trace_top_from_summary "${opt_trace}")\` |"
    fi
    echo
    echo "## Important Artifacts"
    echo
    echo "- Assembly validation CSV: \`${ASM_DIR}/prefetch_asm_validation.csv\`"
    echo "- Assembly objdump: \`${ASM_DIR}/prefetch_objdump.txt\`"
    echo "- Baseline profile: \`${DETAIL_BASE}/baseline_qsort_${MAX_CYCLES}\`"
    echo "- Optimized profile: \`${DETAIL_BASE}/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}\`"
    echo "- Baseline trace: \`${TRACE_BASE}/baseline_qsort_${MAX_CYCLES}/l2_miss\`"
    echo "- Optimized trace: \`${TRACE_BASE}/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/l2_miss\`"
  } > "${SUMMARY_MD}"
}

require_file "${BENCH_COMMON}"
source "${BENCH_COMMON}"
setup_verilator_env
require_chipyard_tree

require_file "${BASELINE_BINARY}"
require_dir "${SOURCE_WORK}"
# Traces are only consumed by plan generation; an external plan needs none
# (and the June qsort LBR dumps have since been pruned from disk).
if [[ -z "${EXTERNAL_PLAN}" ]]; then
  build_trace_args
fi

log "build LLVM pass"
cmake --build "${LLVM_PREFETCH_DIR}/build"
"${LLVM_PREFETCH_DIR}/tests/smoke/run_smoke.sh" "${LLVM_PREFETCH_DIR}/build"
require_file "${PLUGIN}"

log "generate ${PREFETCH_LABEL} plan (${PREFETCH_MNEMONIC})"
PLAN_EXTRA_ARGS=()
if [[ -n "${BRANCH_DEPTH_POLICY}" ]]; then
  PLAN_EXTRA_ARGS+=(--branch-depth-policy "${BRANCH_DEPTH_POLICY}")
fi
if [[ -n "${BRANCH_TYPE_FILTER}" ]]; then
  PLAN_EXTRA_ARGS+=(--branch-type-filter "${BRANCH_TYPE_FILTER}")
fi
if [[ -n "${SAMPLE_BRANCH_TYPE_FILTER}" ]]; then
  PLAN_EXTRA_ARGS+=(--sample-branch-type-filter "${SAMPLE_BRANCH_TYPE_FILTER}")
fi
if [[ "${ALLOW_UNRESOLVED_TARGETS}" == "1" ]]; then
  PLAN_EXTRA_ARGS+=(--allow-unresolved-targets)
fi
if [[ -n "${EXTERNAL_PLAN}" ]]; then
  require_file "${EXTERNAL_PLAN}"
  cp -f "${EXTERNAL_PLAN}" "${PLAN}"
  echo "[ok] copied external plan ${EXTERNAL_PLAN} -> ${PLAN}"
else
  python3 "${LLVM_PREFETCH_DIR}/tools/prefetchit_trace_to_plan.py" \
    "${TRACE_ARGS[@]}" \
    --binary "${BASELINE_BINARY}" \
    --top-k "${TOP_K}" \
    --target-coverage-pct "${TARGET_COVERAGE_PCT}" \
    --depth "${DEPTH}" \
    --depth-min "${DEPTH_MIN}" \
    --site-budget-per-target "${SITE_BUDGET}" \
    --candidate-pool "${CANDIDATE_POOL}" \
    --selection-mode "${SELECTION_MODE}" \
    --sites-per-depth "${SITES_PER_DEPTH}" \
    --prefetch-mnemonic "${PREFETCH_MNEMONIC}" \
    --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
    --target-ip-source "${TARGET_IP_SOURCE}" \
    --summary-dir "${PLAN_SUMMARY}" \
    --output "${PLAN}" \
    "${PLAN_EXTRA_ARGS[@]}"
fi

log "copy Verilator generated model workdir"
rm -rf "${WORK_DIR}"
mkdir -p "$(dirname "${WORK_DIR}")"
cp -a "${SOURCE_WORK}" "${WORK_DIR}"
require_file "${MODEL_DIR}/VTestDriver.mk"

python3 - <<'PY' "${MODEL_DIR}/VTestDriver.mk" "${SOURCE_WORK}" "${WORK_DIR}" "${CONFIG}" "${SIM_OUT}"
from pathlib import Path
import re
import sys

mk = Path(sys.argv[1])
source_work = sys.argv[2]
work_dir = sys.argv[3]
config = sys.argv[4]
sim_out = sys.argv[5]

text = mk.read_text()
before = text

# The copied Verilator makefile may still contain absolute paths pointing at
# the source object directory. Rewrite those first, then normalize any
# simulator target name to the variant-specific output path.
text = text.replace(source_work, work_dir)
target_re = re.compile(
    r"\S*simulator-chipyard\.harness-" + re.escape(config) + r"(?:-llvm-[^\s:]+)?"
)
text, target_rewrites = target_re.subn(sim_out, text)

mk.write_text(text)
print(
    f"[inf] VTestDriver.mk rewrites: path_changed={before != text} "
    f"simulator_target_rewrites={target_rewrites}"
)
if sim_out not in text:
    print("[warn] SIM_OUT target not found after VTestDriver.mk rewrite; candidate lines:")
    for line in text.splitlines():
        if "default:" in line or "simulator-chipyard" in line or "llvm-prefetch" in line:
            print(line[:240])
PY

log "compile and link optimized binary with LLVM pass"
{
  echo "[run] $(date)"
  echo "[inf] OUT_DIR=${OUT_DIR}"
  echo "[inf] MODEL_DIR=${MODEL_DIR}"
  echo "[inf] SIM_OUT=${SIM_OUT}"
  echo "[inf] PLAN=${PLAN}"
  echo "[inf] PLUGIN=${PLUGIN}"
  echo "[inf] CLANG_CXX=${CLANG_CXX}"
} > "${BUILD_LOG}"

rm -f \
  "${MODEL_DIR}/VTestDriver__ALL.o" \
  "${MODEL_DIR}/VTestDriver__ALL.a" \
  "${MODEL_DIR}/VTestDriver__ALL.d" \
  "${MODEL_DIR}/VTestDriver__ALL.verilator_deplist.tmp" \
  "${SIM_OUT}"

(
  cd "${MODEL_DIR}"
  PREFETCHIT_PLAN="${PLAN}" \
  make -f VTestDriver.mk "${SIM_OUT}" \
    -j"${BUILD_JOBS}" \
    VM_PARALLEL_BUILDS=0 \
    CXX="${CLANG_CXX}" \
    LINK="${CLANG_CXX}" \
    OPT_FAST="-O3 -fpass-plugin=${PLUGIN}" \
    2>&1 | tee -a "${BUILD_LOG}"
)
require_file "${SIM_OUT}"
cp -f "${SIM_OUT}" "${FINAL_SIM}"
require_file "${FINAL_SIM}"
ln -sfn "${FINAL_SIM}" "${OUT_DIR}/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"

log "assembly-level validation"
python3 "${LLVM_PREFETCH_DIR}/tools/validate_prefetch_asm.py" \
  --binary "${FINAL_SIM}" \
  --plan "${PLAN}" \
  --build-log "${BUILD_LOG}" \
  --out-dir "${ASM_DIR}" \
  --mnemonic "${PREFETCH_MNEMONIC}" \
  --objdump "${OBJDUMP_BIN}" \
  --addr2line "${ADDR2LINE_BIN}"

log "quick simulator smoke"
qbin="${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv"
require_file "${qbin}"
set +e
taskset -c "${PROFILE_CORE}" "${FINAL_SIM}" "${qbin}" +max-cycles=80000 > "${OUT_DIR}/build/smoke_qsort.log" 2>&1
smoke_rc=$?
set -e
if [[ "${smoke_rc}" -ne 0 ]]; then
  if grep -q "(timeout)" "${OUT_DIR}/build/smoke_qsort.log"; then
    log "smoke accepted: max-cycles timeout reached"
  else
    echo "[err] optimized simulator smoke failed rc=${smoke_rc}" >&2
    sed -n '1,120p' "${OUT_DIR}/build/smoke_qsort.log" >&2
    exit 1
  fi
fi

if [[ "${RUN_PROFILE}" == "1" ]]; then
  if [[ "${RUN_BASELINE}" == "1" ]]; then
    log "run baseline detailed L2 MPKI profile"
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "baseline_qsort_${MAX_CYCLES}" \
      --sim-binary "${BASELINE_BINARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --results-base "${DETAIL_BASE}"
  fi

  log "run ${PREFETCH_LABEL} detailed L2 MPKI profile"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
    --sim-binary "${FINAL_SIM}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${PROFILE_ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --results-base "${DETAIL_BASE}"
else
  log "skip detailed profile: RUN_PROFILE=${RUN_PROFILE}"
fi

if [[ "${RUN_TRACE}" == "1" ]]; then
  if [[ "${RUN_BASELINE}" == "1" ]]; then
    log "run baseline L2 PEBS/LBR trace"
    "${PROFILING_DIR}/run_pebs_sampling.sh" \
      --workload verilator-qsort \
      --workload-name "baseline_qsort_${MAX_CYCLES}" \
      --sim-binary "${BASELINE_BINARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope "${TRACE_PERF_SCOPE}" \
      --duration-sec "${TRACE_DURATION_SEC}" \
      --sample-period "${TRACE_SAMPLE_PERIOD}" \
      --use-ocperf "${TRACE_USE_OCPERF}" \
      --event-l2 "${TRACE_EVENT_L2}" \
      --trace-mode split \
      --trace-select l2 \
      --run-analyze 1 \
      --results-base "${TRACE_BASE}"
  fi

  log "run ${PREFETCH_LABEL} L2 PEBS/LBR trace"
  "${PROFILING_DIR}/run_pebs_sampling.sh" \
    --workload verilator-qsort \
    --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
    --sim-binary "${FINAL_SIM}" \
    --max-cycles "${MAX_CYCLES}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope "${TRACE_PERF_SCOPE}" \
    --duration-sec "${TRACE_DURATION_SEC}" \
    --sample-period "${TRACE_SAMPLE_PERIOD}" \
    --use-ocperf "${TRACE_USE_OCPERF}" \
    --event-l2 "${TRACE_EVENT_L2}" \
    --trace-mode split \
    --trace-select l2 \
    --run-analyze 1 \
    --results-base "${TRACE_BASE}"
fi

build_final_summary
if [[ "${CLEAN_WORKDIR}" == "1" ]]; then
  log "cleanup copied Verilator workdir; keeping final binary and artifacts"
  rm -rf "${WORK_DIR}"
fi
ln -sfn "${OUT_DIR}" "${RESULT_BASE}/latest"
log "done: ${SUMMARY_MD}"
