#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

RUN_ID="${RUN_ID:-adaptive_prefetch_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_adaptive/${RUN_ID}}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
MIN_PREFETCHT_SPEEDUP_PCT="${MIN_PREFETCHT_SPEEDUP_PCT:-15}"
AUTOTUNE_HOURS_PER_BATCH="${AUTOTUNE_HOURS_PER_BATCH:-10}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
START_BATCH="${START_BATCH:-1}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/aggressive_20260601_122543/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
LOG="${OUT_DIR}/adaptive_search.log"

mkdir -p "${OUT_DIR}/batches"

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

require_trace_inputs() {
  local trace_dir
  local found=0
  IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
  for trace_dir in "${trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    found=1
    if [[ ! -f "${trace_dir}/lbr_symbolic_dump.txt" ]]; then
      echo "[err] invalid trace input: ${trace_dir}" | tee -a "${LOG}" >&2
      exit 1
    fi
  done
  if [[ "${found}" -eq 0 ]]; then
    echo "[err] TRACE_INPUTS is required" | tee -a "${LOG}" >&2
    exit 1
  fi
}

write_batch_variants() {
  local batch="$1"
  local file="$2"
  case "${batch}" in
    1)
      cat > "${file}" <<'EOF'
# Broad all-path sweep: coverage, distance, and short/long target-block spans.
cov50_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|50|0,64,128,192
cov75_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|75|0,64,128,192
cov50_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|50|0,64,128,192
cov50_allpaths_d4_16_o8|999999|4|16|0|all-paths|1|0|50|0,64,128,192,256,320,384,448
EOF
      ;;
    2)
      cat > "${file}" <<'EOF'
# Lower-footprint variants: reduce span and restrict LBR distance windows.
cov50_allpaths_d4_8_o1|999999|4|8|0|all-paths|1|0|50|0
cov50_allpaths_d4_8_o2|999999|4|8|0|all-paths|1|0|50|0,64
cov50_allpaths_d8_16_o2|999999|8|16|0|all-paths|1|0|50|0,64
cov50_allpaths_d16_32_o2|999999|16|32|0|all-paths|1|0|50|0,64
cov50_allpaths_d4_16_shift4|999999|4|16|0|all-paths|1|0|50|64,128,192,256
EOF
      ;;
    3)
      cat > "${file}" <<'EOF'
# Bounded site-selection variants: reduce code size and front-end pollution.
cov50_tops_d4_16_b1_o2|999999|4|16|1|top-sites|1|0|50|0,64
cov50_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|50|0,64
cov50_tops_d4_16_b4_o2|999999|4|16|4|top-sites|1|0|50|0,64
cov75_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|75|0,64
cov50_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|50|0,64
cov75_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|75|0,64
cov50_perdepth_d4_16_b16_o2|999999|4|16|16|per-depth|1|0|50|0,64
cov50_perdepth_d1_32_b32_o2|999999|1|32|32|per-depth|1|0|50|0,64
EOF
      ;;
    4)
      cat > "${file}" <<'EOF'
# Coverage/offset stress variants when earlier batches are inconclusive.
cov35_allpaths_d4_16_o2|999999|4|16|0|all-paths|1|0|35|0,64
cov35_allpaths_d8_24_o2|999999|8|24|0|all-paths|1|0|35|0,64
cov50_tops_d8_24_b2_shift2|999999|8|24|2|top-sites|1|0|50|64,128
cov75_perdepth_d4_24_b32_o2|999999|4|24|32|per-depth|1|0|75|0,64
EOF
      ;;
    *)
      return 1
      ;;
  esac
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_PER_ITER}"
require_trace_inputs

cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
trace_inputs=${TRACE_INPUTS}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
min_prefetcht_speedup_pct=${MIN_PREFETCHT_SPEEDUP_PCT}
autotune_hours_per_batch=${AUTOTUNE_HOURS_PER_BATCH}
screen_iterations=${SCREEN_ITERATIONS}
final_iterations=${FINAL_ITERATIONS}
build_jobs=${BUILD_JOBS}
start_batch=${START_BATCH}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
baseline_per_iter=${BASELINE_PER_ITER}
source_work=${SOURCE_WORK}
EOF

log "adaptive prefetch search start: ${OUT_DIR}"
for batch in 1 2 3 4; do
  if (( batch < START_BATCH )); then
    continue
  fi
  batch_dir="${OUT_DIR}/batch${batch}"
  variants="${OUT_DIR}/batches/batch${batch}_variants.txt"
  write_batch_variants "${batch}" "${variants}" || break
  log "batch ${batch} start variants=${variants}"
  set +e
  RUN_ID="batch${batch}" \
  OUT_DIR="${batch_dir}" \
  VARIANTS_SOURCE_FILE="${variants}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  RUN_BASELINE_FINAL=0 \
  SCREEN_ITERATIONS="${SCREEN_ITERATIONS}" \
  FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
  AUTOTUNE_HOURS="${AUTOTUNE_HOURS_PER_BATCH}" \
  TARGET_RUNTIME_DELTA_PCT="$(awk -v s="${MIN_PREFETCHT_SPEEDUP_PCT}" 'BEGIN { printf "-%.6f", s }')" \
  MIN_PREFETCHT_SPEEDUP_PCT="${MIN_PREFETCHT_SPEEDUP_PCT}" \
  REQUIRE_PREFETCHT_SPEEDUP=1 \
  BUILD_JOBS="${BUILD_JOBS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
  BASELINE_PER_ITER="${BASELINE_PER_ITER}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  ALLOW_UNRESOLVED_TARGETS=1 \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_aggressive_prefetch_experiment.sh"
  rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    log "batch ${batch} reached speedup threshold; final report=${batch_dir}/final_report.md"
    ln -sfn "${batch_dir}" "${OUT_DIR}/best_batch"
    exit 0
  fi
  log "batch ${batch} did not reach threshold rc=${rc}; continuing"
done

log "adaptive prefetch search exhausted all batches without reaching threshold"
exit 2
