#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-aggressive_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/${RUN_ID}}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
AUTOTUNE_HOURS="${AUTOTUNE_HOURS:-18}"
TARGET_RUNTIME_DELTA_PCT="${TARGET_RUNTIME_DELTA_PCT:--15}"
MIN_PREFETCHT_SPEEDUP_PCT="${MIN_PREFETCHT_SPEEDUP_PCT:-15}"
REQUIRE_PREFETCHT_SPEEDUP="${REQUIRE_PREFETCHT_SPEEDUP:-1}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/aggressive_20260601_122543/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
RUN_BASELINE_FINAL="${RUN_BASELINE_FINAL:-0}"
TRACE_INPUT="${TRACE_INPUT:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/trace_l2i_code_rd_miss_precise/baseline_qsort_${MAX_CYCLES}/l2_miss}"
TRACE_INPUTS="${TRACE_INPUTS:-${TRACE_INPUT}}"
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS:-1}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
OBJDUMP_BIN="${OBJDUMP_BIN:-llvm-objdump-19}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}"

AUTOTUNE_DIR="${OUT_DIR}/prefetcht1_screen"
COMPARE_DIR="${OUT_DIR}/final_compare"
VARIANTS_FILE="${OUT_DIR}/aggressive_variants.txt"
VARIANTS_SOURCE_FILE="${VARIANTS_SOURCE_FILE:-}"
LOG="${OUT_DIR}/aggressive_experiment.log"

mkdir -p "${OUT_DIR}" "${COMPARE_DIR}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "[err] missing directory: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

metric_from_summary() {
  local csv="$1"
  local metric="$2"
  awk -F, -v m="${metric}" 'NR>1 && $1==m {print $2; exit}' "${csv}"
}

write_variants() {
  if [[ -n "${VARIANTS_SOURCE_FILE}" ]]; then
    require_file "${VARIANTS_SOURCE_FILE}"
    cp -f "${VARIANTS_SOURCE_FILE}" "${VARIANTS_FILE}"
    return
  fi
  cat > "${VARIANTS_FILE}" <<'EOF'
# name|top_k|depth_min|depth|site_budget|selection_mode|sites_per_depth|candidate_pool|target_coverage_pct|prefetch_byte_offsets
# Coverage-based target selection. all-paths emits every resolved LBR path site per selected target.
# Offset spans compensate for sampled-PC/source-line ambiguity by prefetching nearby cachelines from the LLVM target block label.
cov50_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|50|0,64,128,192
cov75_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|75|0,64,128,192
cov50_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|50|0,64,128,192
cov75_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|75|0,64,128,192
cov50_allpaths_d4_16_o8|999999|4|16|0|all-paths|1|0|50|0,64,128,192,256,320,384,448
cov75_allpaths_d4_16_o8|999999|4|16|0|all-paths|1|0|75|0,64,128,192,256,320,384,448
cov100_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|100|0,64,128,192
cov100_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|100|0,64,128,192
# Lower-footprint all-path variants. These test whether the o4/o8 spans add too
# much instruction footprint or decode pressure.
cov50_allpaths_d4_8_o1|999999|4|8|0|all-paths|1|0|50|0
cov50_allpaths_d4_8_o2|999999|4|8|0|all-paths|1|0|50|0,64
cov50_allpaths_d8_16_o2|999999|8|16|0|all-paths|1|0|50|0,64
cov50_allpaths_d16_32_o2|999999|16|32|0|all-paths|1|0|50|0,64
cov50_allpaths_d4_16_shift4|999999|4|16|0|all-paths|1|0|50|64,128,192,256
# Bounded variants. If all-path is too intrusive, these keep only the hottest
# site candidates per target while still using coverage-selected targets.
cov50_tops_d4_16_b1_o2|999999|4|16|1|top-sites|1|0|50|0,64
cov50_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|50|0,64
cov50_tops_d4_16_b4_o2|999999|4|16|4|top-sites|1|0|50|0,64
cov75_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|75|0,64
cov50_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|50|0,64
cov75_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|75|0,64
cov50_perdepth_d4_16_b16_o2|999999|4|16|16|per-depth|1|0|50|0,64
cov50_perdepth_d1_32_b32_o2|999999|1|32|32|per-depth|1|0|50|0,64
EOF
}

extract_plan_options() {
  local plan="$1"
  python3 - "$plan" <<'PY'
import json, shlex, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
o = p.get("options", {})
items = {
    "TOP_K": o.get("top_k", 2000),
    "TARGET_COVERAGE_PCT": o.get("target_coverage_pct", 0),
    "DEPTH_MIN": o.get("depth_min", 4),
    "DEPTH": o.get("depth", 16),
    "SITE_BUDGET": o.get("site_budget_per_target", 1),
    "SELECTION_MODE": o.get("selection_mode", "top-sites"),
    "SITES_PER_DEPTH": o.get("sites_per_depth", 1),
    "CANDIDATE_POOL": o.get("candidate_pool", 0),
    "PREFETCH_BYTE_OFFSETS": ",".join(str(x) for x in o.get("prefetch_byte_offsets", [0])),
    "BRANCH_DEPTH_POLICY": ",".join(
        f"{k}:{v[0]}-{v[1]}"
        for k, v in sorted((o.get("branch_depth_policy") or {}).items())
        if isinstance(v, list) and len(v) == 2
    ),
}
for k, v in items.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
}

run_final_profile() {
  local label="$1"
  local bin="$2"
  log "final profile ${label}: iterations=${FINAL_ITERATIONS} core=${PROFILE_CORE}"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "${label}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${FINAL_ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --results-base "${COMPARE_DIR}/profiles" \
    > "${COMPARE_DIR}/${label}_profile.log" 2>&1
}

stage_baseline_profile() {
  local dst="${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}"
  mkdir -p "${dst}"
  if [[ "${RUN_BASELINE_FINAL}" == "1" ]]; then
    run_final_profile baseline "${BASELINE_BINARY}"
    return
  fi
  require_file "${BASELINE_PER_ITER}"
  require_file "${BASELINE_SUMMARY}"
  cp -f "${BASELINE_PER_ITER}" "${dst}/per_iteration.csv"
  cp -f "${BASELINE_SUMMARY}" "${dst}/summary.csv"
  log "reuse baseline profile: ${BASELINE_PER_ITER}"
}

runtime_delta_for_variant() {
  local variant="$1"
  python3 - "${AUTOTUNE_DIR}/aggregate.csv" "${variant}" <<'PY'
import csv
import sys

aggregate, variant = sys.argv[1:3]
with open(aggregate, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row.get("variant") == variant:
            print(row.get("elapsed_delta_pct", ""))
            raise SystemExit(0)
raise SystemExit(1)
PY
}

write_final_report() {
  local best_name="$1"
  local best_dir="$2"
  local best_bin="$3"
  local prefetchit_dir="$4"
  local prefetchit_bin="$5"
  local summary_md="${COMPARE_DIR}/prefetch_compare_summary.md"
  local report="${OUT_DIR}/final_report.md"
  {
    echo "# Aggressive Prefetch Experiment"
    echo
    echo "- Run id: \`${RUN_ID}\`"
    echo "- Max cycles: ${MAX_CYCLES}"
    echo "- Profile core: ${PROFILE_CORE}"
    echo "- Screening iterations: ${SCREEN_ITERATIONS}"
    echo "- Final iterations: ${FINAL_ITERATIONS}"
    echo "- Target runtime delta for screening: ${TARGET_RUNTIME_DELTA_PCT}%"
    echo "- Minimum required prefetcht speedup before prefetchit compare: ${MIN_PREFETCHT_SPEEDUP_PCT}%"
    echo "- Baseline final profile rerun: ${RUN_BASELINE_FINAL}"
    echo "- Best prefetcht1 variant: \`${best_name}\`"
    echo "- Best prefetcht1 binary: \`${best_bin}\`"
    echo "- Same-position prefetchit1 binary: \`${prefetchit_bin}\`"
    echo
    echo "## Final Compare"
    echo
    if [[ -f "${summary_md}" ]]; then
      sed -n '1,80p' "${summary_md}"
    else
      echo "Final summary is missing."
    fi
    echo
    echo "## Validation"
    echo
    echo "- prefetcht1 validation: \`${best_dir}/assembly_validation/prefetch_asm_validation.md\`"
    echo "- prefetchit1 validation: \`${prefetchit_dir}/assembly_validation/prefetch_asm_validation.md\`"
    echo
    echo "## Plots"
    echo
    echo "- boxplot: \`${COMPARE_DIR}/prefetch_compare_boxplot.png\`"
    echo "- iterations CSV: \`${COMPARE_DIR}/prefetch_compare_iterations.csv\`"
    echo "- summary CSV: \`${COMPARE_DIR}/prefetch_compare_summary.csv\`"
    echo
    echo "## Autotune"
    echo
    echo "- leaderboard: \`${AUTOTUNE_DIR}/leaderboard.md\`"
    echo "- aggregate: \`${AUTOTUNE_DIR}/aggregate.csv\`"
  } > "${report}"
  log "final report: ${report}"
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
if [[ "${RUN_BASELINE_FINAL}" != "1" ]]; then
  require_file "${BASELINE_PER_ITER}"
fi
require_dir "${SOURCE_WORK}"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh"
require_file "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_compare.py"

write_variants
cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
screen_iterations=${SCREEN_ITERATIONS}
final_iterations=${FINAL_ITERATIONS}
autotune_hours=${AUTOTUNE_HOURS}
target_runtime_delta_pct=${TARGET_RUNTIME_DELTA_PCT}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
baseline_per_iter=${BASELINE_PER_ITER}
run_baseline_final=${RUN_BASELINE_FINAL}
trace_input=${TRACE_INPUT}
trace_inputs=${TRACE_INPUTS}
source_work=${SOURCE_WORK}
build_jobs=${BUILD_JOBS}
objdump_bin=${OBJDUMP_BIN}
addr2line_bin=${ADDR2LINE_BIN}
min_prefetcht_speedup_pct=${MIN_PREFETCHT_SPEEDUP_PCT}
require_prefetcht_speedup=${REQUIRE_PREFETCHT_SPEEDUP}
EOF

log "aggressive prefetcht1 screening start: ${AUTOTUNE_DIR}"
RUN_ID="$(basename "${AUTOTUNE_DIR}")" \
OUT_DIR="${AUTOTUNE_DIR}" \
VARIANTS_FILE="${VARIANTS_FILE}" \
AUTOTUNE_HOURS="${AUTOTUNE_HOURS}" \
MAX_CYCLES="${MAX_CYCLES}" \
PROFILE_CORE="${PROFILE_CORE}" \
SCREEN_ITERATIONS="${SCREEN_ITERATIONS}" \
SCREEN_RUN_TRACE=0 \
RUN_CONFIRMATION=0 \
STOP_RUNTIME_DELTA_PCT="${TARGET_RUNTIME_DELTA_PCT}" \
PREFETCH_MNEMONIC=prefetcht1 \
PREFETCH_LABEL=prefetcht1 \
BUILD_JOBS="${BUILD_JOBS}" \
BASELINE_BINARY="${BASELINE_BINARY}" \
BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
TRACE_INPUT="${TRACE_INPUT}" \
TRACE_INPUTS="${TRACE_INPUTS}" \
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS}" \
SOURCE_WORK="${SOURCE_WORK}" \
OBJDUMP_BIN="${OBJDUMP_BIN}" \
bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh" 2>&1 | tee -a "${LOG}"

if [[ ! -f "${AUTOTUNE_DIR}/best_variant.txt" ]]; then
  echo "[err] no successful prefetcht1 variant" | tee -a "${LOG}" >&2
  exit 1
fi
mapfile -t best_lines < "${AUTOTUNE_DIR}/best_variant.txt"
best_name="${best_lines[0]:-}"
best_dir="${best_lines[1]:-}"
best_bin="${best_lines[2]:-}"
require_file "${best_bin}"
require_file "${best_dir}/plan/prefetcht1.plan.json"
log "best prefetcht1: ${best_name} bin=${best_bin}"
best_runtime_delta="$(runtime_delta_for_variant "${best_name}")"
required_runtime_delta="$(awk -v s="${MIN_PREFETCHT_SPEEDUP_PCT}" 'BEGIN { printf "%.6f", -s }')"
log "best prefetcht1 runtime delta=${best_runtime_delta}% required<=${required_runtime_delta}%"
if [[ "${REQUIRE_PREFETCHT_SPEEDUP}" == "1" ]]; then
  if ! awk -v got="${best_runtime_delta}" -v req="${required_runtime_delta}" 'BEGIN { exit ((got+0) <= (req+0)) ? 0 : 1 }'; then
    {
      echo "# Prefetch Screening Stopped Before Final Compare"
      echo
      echo "- Best variant: \`${best_name}\`"
      echo "- Best runtime delta: ${best_runtime_delta}%"
      echo "- Required runtime delta: <= ${required_runtime_delta}%"
      echo "- Autotune leaderboard: \`${AUTOTUNE_DIR}/leaderboard.md\`"
      echo
      echo "The prefetchit same-position comparison was intentionally skipped because prefetcht1 did not reach the requested speedup threshold."
    } > "${OUT_DIR}/prefetcht_threshold_not_met.md"
    echo "[err] prefetcht1 speedup threshold not met; see ${OUT_DIR}/prefetcht_threshold_not_met.md" | tee -a "${LOG}" >&2
    exit 2
  fi
fi

log "build same-position prefetchit1 using best prefetcht1 plan options"
eval "$(extract_plan_options "${best_dir}/plan/prefetcht1.plan.json")"
prefetchit_run_id="same_${best_name}_prefetchit1"
prefetchit_base="${OUT_DIR}/prefetchit_same_positions"
RESULT_BASE="${prefetchit_base}" \
RUN_ID="${prefetchit_run_id}" \
TRACE_INPUT="${TRACE_INPUT}" \
TRACE_INPUTS="${TRACE_INPUTS}" \
BASELINE_BINARY="${BASELINE_BINARY}" \
SOURCE_WORK="${SOURCE_WORK}" \
CONFIG="${CONFIG}" \
TOP_K="${TOP_K}" \
TARGET_COVERAGE_PCT="${TARGET_COVERAGE_PCT}" \
DEPTH_MIN="${DEPTH_MIN}" \
DEPTH="${DEPTH}" \
SITE_BUDGET="${SITE_BUDGET}" \
CANDIDATE_POOL="${CANDIDATE_POOL}" \
SELECTION_MODE="${SELECTION_MODE}" \
SITES_PER_DEPTH="${SITES_PER_DEPTH}" \
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS}" \
  PREFETCH_MNEMONIC=prefetchit1 \
  PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS}" \
  BRANCH_DEPTH_POLICY="${BRANCH_DEPTH_POLICY}" \
  PREFETCH_LABEL=prefetchit1 \
MAX_CYCLES="${MAX_CYCLES}" \
PROFILE_ITERATIONS=1 \
PROFILE_CORE="${PROFILE_CORE}" \
BUILD_JOBS="${BUILD_JOBS}" \
RUN_BASELINE=0 \
RUN_TRACE=0 \
CLEAN_WORKDIR=1 \
OBJDUMP_BIN="${OBJDUMP_BIN}" \
ADDR2LINE_BIN="${ADDR2LINE_BIN}" \
bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${OUT_DIR}/prefetchit1_build_eval.log" 2>&1
prefetchit_dir="${prefetchit_base}/${prefetchit_run_id}"
prefetchit_bin="${prefetchit_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-prefetchit1"
require_file "${prefetchit_bin}"

log "final fair comparison start"
stage_baseline_profile
run_final_profile prefetcht1 "${best_bin}"
run_final_profile prefetchit1 "${prefetchit_bin}"

python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_compare.py" \
  --input "baseline=${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv" \
  --input "prefetcht1=${COMPARE_DIR}/profiles/prefetcht1_qsort_${MAX_CYCLES}/per_iteration.csv" \
  --input "prefetchit1=${COMPARE_DIR}/profiles/prefetchit1_qsort_${MAX_CYCLES}/per_iteration.csv" \
  --out-dir "${COMPARE_DIR}" \
  2>&1 | tee -a "${LOG}"

write_final_report "${best_name}" "${best_dir}" "${best_bin}" "${prefetchit_dir}" "${prefetchit_bin}"
log "aggressive experiment complete"
