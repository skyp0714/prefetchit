#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

RUN_ID="${RUN_ID:-prefetchit_large_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetchit_large_sweep/${RUN_ID}}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-1}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-4}"
BUILD_JOBS="${BUILD_JOBS:-8}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BEST_PLAN="${BEST_PLAN:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/plateau_fixed_20260604_013311/batch_repair/runs/v02_cov50_tops_d4_24_b8_o2/plan/prefetcht1.plan.json}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
EARLY_STOP_WORSE_STREAK="${EARLY_STOP_WORSE_STREAK:-4}"
EARLY_STOP_WORSE_MARGIN_PCT="${EARLY_STOP_WORSE_MARGIN_PCT:-0.75}"
PROFILE_VARIANT_LIMIT="${PROFILE_VARIANT_LIMIT:-0}"

mkdir -p "${OUT_DIR}"
LOG="${OUT_DIR}/prefetchit_large_sweep.log"
VARIANTS_TSV="${OUT_DIR}/prefetchit_variants_small_to_large.tsv"

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

trace_inputs_from_plan() {
  python3 - "$1" <<'PY'
import json
import sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
trace_dirs = plan.get("trace_dirs") or plan.get("trace_inputs") or []
if isinstance(trace_dirs, str):
    trace_dirs = [item for item in trace_dirs.split(":") if item]
print(":".join(trace_dirs))
PY
}

require_file "${BEST_PLAN}"
require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_BINARY}"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_fixed_coverage_parallel_sweep.sh"
require_file "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py"

TRACE_INPUTS="${TRACE_INPUTS:-$(trace_inputs_from_plan "${BEST_PLAN}")}"
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] could not derive TRACE_INPUTS from ${BEST_PLAN}" | tee -a "${LOG}" >&2
  exit 1
fi

cat > "${VARIANTS_TSV}" <<'EOF'
# axis	value	name	top_k	depth_min	depth	site_budget	selection_mode	sites_per_depth	candidate_pool	target_coverage_pct	prefetch_byte_offsets	branch_depth_policy
coverage	5	cov05_tops_d4_8_b1_o1	999999	4	8	1	top-sites	1	0	5	0	
coverage	5	cov05_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	5	0	
coverage	10	cov10_tops_d4_8_b1_o1	999999	4	8	1	top-sites	1	0	10	0	
coverage	10	cov10_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	10	0	
coverage	15	cov15_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	15	0	
coverage	20	cov20_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	20	0	
coverage	25	cov25_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	25	0	
coverage	30	cov30_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	30	0	
coverage	40	cov40_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	40	0	
coverage	50	cov50_tops_d4_16_b1_o1	999999	4	16	1	top-sites	1	0	50	0	
offsets	10_o2	cov10_tops_d4_16_b1_o2	999999	4	16	1	top-sites	1	0	10	0,64	
offsets	20_o2	cov20_tops_d4_16_b1_o2	999999	4	16	1	top-sites	1	0	20	0,64	
offsets	30_o2	cov30_tops_d4_16_b1_o2	999999	4	16	1	top-sites	1	0	30	0,64	
offsets	40_o2	cov40_tops_d4_16_b1_o2	999999	4	16	1	top-sites	1	0	40	0,64	
offsets	50_o2	cov50_tops_d4_16_b1_o2	999999	4	16	1	top-sites	1	0	50	0,64	
budget	25_b2	cov25_tops_d4_16_b2_o1	999999	4	16	2	top-sites	1	0	25	0	
budget	40_b2	cov40_tops_d4_16_b2_o1	999999	4	16	2	top-sites	1	0	40	0	
budget	50_b2	cov50_tops_d4_16_b2_o1	999999	4	16	2	top-sites	1	0	50	0	
budget	30_b4	cov30_tops_d4_16_b4_o1	999999	4	16	4	top-sites	1	0	30	0	
budget	50_b4	cov50_tops_d4_16_b4_o1	999999	4	16	4	top-sites	1	0	50	0	
depth	50_d4_24_b1	cov50_tops_d4_24_b1_o1	999999	4	24	1	top-sites	1	0	50	0	
depth	50_d4_24_b2	cov50_tops_d4_24_b2_o1	999999	4	24	2	top-sites	1	0	50	0	
selection	branch_policy	cov50_bp_tops_d1_24_b2_o1	999999	1	24	2	top-sites	1	0	50	0	CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-24,IND:4-24
selection	greedy	cov50_greedy_d4_16_b4_o1	999999	4	16	4	greedy	1	10000	50	0	
EOF

cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
variant_file=${VARIANTS_TSV}
best_plan=${BEST_PLAN}
trace_inputs=${TRACE_INPUTS}
baseline_summary=${BASELINE_SUMMARY}
baseline_binary=${BASELINE_BINARY}
source_work=${SOURCE_WORK}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
profile_iterations=${PROFILE_ITERATIONS}
parallel_builds=${PARALLEL_BUILDS}
build_jobs=${BUILD_JOBS}
early_stop_worse_streak=${EARLY_STOP_WORSE_STREAK}
early_stop_worse_margin_pct=${EARLY_STOP_WORSE_MARGIN_PCT}
profile_variant_limit=${PROFILE_VARIANT_LIMIT}
prefetch_mnemonic=prefetchit1
prefetch_label=prefetchit1
summary_rank_by=runtime
EOF

log "prefetchit large parallel sweep start: ${OUT_DIR}"
log "builds parallel=${PARALLEL_BUILDS} x jobs=${BUILD_JOBS}; profiles sequential core=${PROFILE_CORE}"
log "variants ordered from lower expected injection to higher expected injection"
log "early-stop during profiling: last ${EARLY_STOP_WORSE_STREAK} successful variants worse than best runtime by >=${EARLY_STOP_WORSE_MARGIN_PCT}%"

RUN_ID="parallel" \
OUT_DIR="${OUT_DIR}/parallel" \
VARIANTS_TSV_INPUT="${VARIANTS_TSV}" \
TRACE_INPUTS="${TRACE_INPUTS}" \
TRACE_INPUT="${TRACE_INPUTS%%:*}" \
BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
BASELINE_BINARY="${BASELINE_BINARY}" \
SOURCE_WORK="${SOURCE_WORK}" \
MAX_CYCLES="${MAX_CYCLES}" \
PROFILE_CORE="${PROFILE_CORE}" \
PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
PARALLEL_BUILDS="${PARALLEL_BUILDS}" \
BUILD_JOBS="${BUILD_JOBS}" \
ALLOW_UNRESOLVED_TARGETS=1 \
PREFETCH_MNEMONIC=prefetchit1 \
PREFETCH_LABEL=prefetchit1 \
SUMMARY_RANK_BY=runtime \
EARLY_STOP_WORSE_STREAK="${EARLY_STOP_WORSE_STREAK}" \
EARLY_STOP_WORSE_MARGIN_PCT="${EARLY_STOP_WORSE_MARGIN_PCT}" \
PROFILE_VARIANT_LIMIT="${PROFILE_VARIANT_LIMIT}" \
bash "${LLVM_PREFETCH_DIR}/scripts/run_fixed_coverage_parallel_sweep.sh" 2>&1 | tee -a "${LOG}"

PLOT_OUT="${OUT_DIR}/plots/injection_effects_line_$(date +%Y%m%d_%H%M%S)"
python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py" \
  --results-root "${LLVM_PREFETCH_DIR}/results" \
  --baseline-summary "${BASELINE_SUMMARY}" \
  --out-dir "${PLOT_OUT}" 2>&1 | tee -a "${LOG}"

log "plot output: ${PLOT_OUT}"
log "prefetchit large parallel sweep done"
