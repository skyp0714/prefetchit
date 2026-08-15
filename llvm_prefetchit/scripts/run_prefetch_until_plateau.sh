#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-plateau_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/${RUN_ID}}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
AUTOTUNE_HOURS_PER_BATCH="${AUTOTUNE_HOURS_PER_BATCH:-12}"
MIN_IMPROVEMENT_ABS_PCT="${MIN_IMPROVEMENT_ABS_PCT:-1.0}"
PATIENCE_BATCHES="${PATIENCE_BATCHES:-2}"
MAX_BATCHES="${MAX_BATCHES:-5}"
WAIT_FOR_SESSION="${WAIT_FOR_SESSION:-}"
WAIT_POLL_SEC="${WAIT_POLL_SEC:-60}"
RUN_FINAL_COMPARE="${RUN_FINAL_COMPARE:-1}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
RESIDUAL_TRACE_DURATION_SEC="${RESIDUAL_TRACE_DURATION_SEC:-20}"
RESIDUAL_TRACE_SAMPLE_PERIOD="${RESIDUAL_TRACE_SAMPLE_PERIOD:-100000}"

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/aggressive_20260601_122543/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
SEED_AGGREGATE="${SEED_AGGREGATE:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/adaptive_spanagg_cached_20260603_154303/prefetcht1_screen/aggregate.csv}"
SEED_BEST_FILE="${SEED_BEST_FILE:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/adaptive_spanagg_cached_20260603_154303/prefetcht1_screen/best_variant.txt}"
LOG="${OUT_DIR}/plateau_search.log"

mkdir -p "${OUT_DIR}/batches" "${OUT_DIR}/final_compare"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
require_file() { [[ -f "$1" ]] || { echo "[err] missing file: $1" | tee -a "${LOG}" >&2; exit 1; }; }
require_dir() { [[ -d "$1" ]] || { echo "[err] missing dir: $1" | tee -a "${LOG}" >&2; exit 1; }; }

require_trace_inputs() {
  local trace_dir found=0
  IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
  for trace_dir in "${trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    found=1
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
  done
  if [[ "${found}" -eq 0 ]]; then
    echo "[err] TRACE_INPUTS is required" | tee -a "${LOG}" >&2
    exit 1
  fi
}

wait_for_session_if_needed() {
  if [[ -z "${WAIT_FOR_SESSION}" ]]; then
    return
  fi
  while tmux has-session -t "${WAIT_FOR_SESSION}" 2>/dev/null; do
    log "waiting for tmux session ${WAIT_FOR_SESSION} to finish before launching new builds"
    sleep "${WAIT_POLL_SEC}"
  done
  log "wait session finished: ${WAIT_FOR_SESSION}"
}

write_batch_variants() {
  local batch="$1"
  local file="$2"
  case "${batch}" in
    1)
      cat > "${file}" <<'EOFVAR'
# Stronger bounded variants around the current best d4-16,b4,o2 point.
cov50_tops_d4_16_b8_o2|999999|4|16|8|top-sites|1|0|50|0,64|
cov50_tops_d4_16_b16_o2|999999|4|16|16|top-sites|1|0|50|0,64|
cov75_tops_d4_16_b8_o2|999999|4|16|8|top-sites|1|0|75|0,64|
cov50_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|50|0,64|
EOFVAR
      ;;
    2)
      cat > "${file}" <<'EOFVAR'
# Branch-type timing policy: calls closer, returns farther, cond/uncond in the original window.
cov50_bp_tops_d1_32_b8_o2|999999|1|32|8|top-sites|1|0|50|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov50_bp_tops_d1_32_b16_o2|999999|1|32|16|top-sites|1|0|50|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov75_bp_tops_d1_32_b8_o2|999999|1|32|8|top-sites|1|0|75|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov50_bp_perdepth_d1_32_b32_o2|999999|1|32|32|per-depth|1|0|50|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOFVAR
      ;;
    3)
      cat > "${file}" <<'EOFVAR'
# Wider target-block cacheline spans. Useful if sampled PC -> LLVM block label is still offset by a line or two.
cov50_tops_d4_16_b8_o4|999999|4|16|8|top-sites|1|0|50|0,64,128,192|
cov50_bp_tops_d1_32_b8_o4|999999|1|32|8|top-sites|1|0|50|0,64,128,192|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov75_bp_tops_d1_32_b8_o4|999999|1|32|8|top-sites|1|0|75|0,64,128,192|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov50_bp_perdepth_d1_32_b48_o4|999999|1|32|48|per-depth|1|0|50|0,64,128,192|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOFVAR
      ;;
    4)
      cat > "${file}" <<'EOFVAR'
# More target coverage and longer windows. These can become footprint-heavy, so run after bounded variants.
cov75_tops_d1_32_b16_o2|999999|1|32|16|top-sites|1|0|75|0,64|
cov100_tops_d4_16_b8_o2|999999|4|16|8|top-sites|1|0|100|0,64|
cov75_perdepth_d1_32_b64_o2|999999|1|32|64|per-depth|1|0|75|0,64|
cov100_bp_tops_d1_32_b16_o2|999999|1|32|16|top-sites|1|0|100|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOFVAR
      ;;
    5)
      cat > "${file}" <<'EOFVAR'
# Last-resort all-path variants with lower target coverage. Expensive, but tests whether top-sites missed divergent paths.
cov25_allpaths_d4_16_o2|999999|4|16|0|all-paths|1|0|25|0,64|
cov35_allpaths_d4_16_o2|999999|4|16|0|all-paths|1|0|35|0,64|
cov25_bp_allpaths_d1_32_o2|999999|1|32|0|all-paths|1|0|25|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov35_bp_allpaths_d1_32_o2|999999|1|32|0|all-paths|1|0|35|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOFVAR
      ;;
    *) return 1 ;;
  esac
}

best_from_aggregate() {
  local aggregate="$1"
  python3 - "$aggregate" <<'PY'
import csv, math, sys
path = sys.argv[1]
best = None
with open(path, newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row.get('status') != 'ok':
            continue
        try:
            delta = float(row.get('elapsed_delta_pct', 'nan'))
        except ValueError:
            continue
        if not math.isfinite(delta):
            continue
        if best is None or delta < best[0]:
            best = (delta, row.get('variant',''), row.get('run_dir',''), row.get('binary',''))
if best is None:
    raise SystemExit(1)
print('\t'.join(str(x) for x in best))
PY
}

seed_best() {
  BEST_DELTA="999999"
  BEST_NAME=""
  BEST_DIR=""
  BEST_BIN=""
  BEST_NEW_DELTA="999999"
  BEST_NEW_NAME=""
  BEST_NEW_DIR=""
  BEST_NEW_BIN=""
  if [[ -f "${SEED_AGGREGATE}" ]]; then
    local line
    line="$(best_from_aggregate "${SEED_AGGREGATE}" || true)"
    if [[ -n "${line}" ]]; then
      IFS=$'\t' read -r BEST_DELTA BEST_NAME BEST_DIR BEST_BIN <<< "${line}"
    fi
  fi
  if [[ -f "${SEED_BEST_FILE}" ]]; then
    mapfile -t seed_lines < "${SEED_BEST_FILE}"
    BEST_NAME="${BEST_NAME:-${seed_lines[0]:-}}"
    BEST_DIR="${BEST_DIR:-${seed_lines[1]:-}}"
    BEST_BIN="${BEST_BIN:-${seed_lines[2]:-}}"
  fi
  if [[ -n "${BEST_BIN}" ]]; then
    require_file "${BEST_BIN}"
  fi
  log "seed best: name=${BEST_NAME:-none} delta=${BEST_DELTA}% bin=${BEST_BIN:-none}"
}

maybe_update_best() {
  local batch="$1"
  local aggregate="$2"
  local line new_delta new_name new_dir new_bin improved
  line="$(best_from_aggregate "${aggregate}" || true)"
  if [[ -z "${line}" ]]; then
    log "batch ${batch}: no successful variant in aggregate"
    return 1
  fi
  IFS=$'\t' read -r new_delta new_name new_dir new_bin <<< "${line}"
  if python3 - "${BEST_NEW_DELTA}" "${new_delta}" <<'PY'
import math
import sys
old = float(sys.argv[1])
new = float(sys.argv[2])
sys.exit(0 if math.isfinite(new) and new < old else 1)
PY
  then
    BEST_NEW_DELTA="${new_delta}"
    BEST_NEW_NAME="${new_name}"
    BEST_NEW_DIR="${new_dir}"
    BEST_NEW_BIN="${new_bin}"
    printf '%s\n%s\n%s\n%s\n' "${BEST_NEW_NAME}" "${BEST_NEW_DIR}" "${BEST_NEW_BIN}" "${BEST_NEW_DELTA}" > "${OUT_DIR}/best_new_variant.txt"
  fi
  improved="$(python3 - "${BEST_DELTA}" "${new_delta}" "${MIN_IMPROVEMENT_ABS_PCT}" <<'PY'
import math, sys
old = float(sys.argv[1])
new = float(sys.argv[2])
min_abs = float(sys.argv[3])
print('1' if math.isfinite(new) and new <= old - min_abs else '0')
PY
)"
  log "batch ${batch}: best=${new_name} delta=${new_delta}% previous=${BEST_DELTA}% improved=${improved}"
  if [[ "${improved}" == "1" ]]; then
    BEST_DELTA="${new_delta}"
    BEST_NAME="${new_name}"
    BEST_DIR="${new_dir}"
    BEST_BIN="${new_bin}"
    NO_IMPROVE_BATCHES=0
    printf '%s\n%s\n%s\n%s\n' "${BEST_NAME}" "${BEST_DIR}" "${BEST_BIN}" "${BEST_DELTA}" > "${OUT_DIR}/best_variant.txt"
    return 0
  fi
  NO_IMPROVE_BATCHES=$((NO_IMPROVE_BATCHES + 1))
  return 1
}

extract_plan_options() {
  local plan="$1"
  python3 - "$plan" <<'PY'
import json, shlex, sys
p = json.load(open(sys.argv[1], encoding='utf-8'))
o = p.get('options', {})
policy = o.get('branch_depth_policy') or {}
policy_s = ','.join(
    f'{k}:{v[0]}-{v[1]}' for k, v in sorted(policy.items())
    if isinstance(v, list) and len(v) == 2
)
items = {
    'TOP_K': o.get('top_k', 999999),
    'TARGET_COVERAGE_PCT': o.get('target_coverage_pct', 0),
    'DEPTH_MIN': o.get('depth_min', 4),
    'DEPTH': o.get('depth', 16),
    'SITE_BUDGET': o.get('site_budget_per_target', 1),
    'SELECTION_MODE': o.get('selection_mode', 'top-sites'),
    'SITES_PER_DEPTH': o.get('sites_per_depth', 1),
    'CANDIDATE_POOL': o.get('candidate_pool', 0),
    'PREFETCH_BYTE_OFFSETS': ','.join(str(x) for x in o.get('prefetch_byte_offsets', [0])),
    'BRANCH_DEPTH_POLICY': policy_s,
}
for k, v in items.items():
    print(f'{k}={shlex.quote(str(v))}')
PY
}

run_profile() {
  local label="$1" bin="$2" compare_dir="$3"
  log "final profile ${label}: iterations=${FINAL_ITERATIONS} core=${PROFILE_CORE}"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "${label}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${FINAL_ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --results-base "${compare_dir}/profiles" \
    > "${compare_dir}/${label}_profile.log" 2>&1
}

run_residual_trace() {
  local label="$1" bin="$2" trace_base="$3"
  log "residual L2 trace ${label}: duration=${RESIDUAL_TRACE_DURATION_SEC}s period=${RESIDUAL_TRACE_SAMPLE_PERIOD}"
  "${PROFILING_DIR}/run_pebs_sampling.sh" \
    --workload verilator-qsort \
    --workload-name "${label}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --duration-sec "${RESIDUAL_TRACE_DURATION_SEC}" \
    --sample-period "${RESIDUAL_TRACE_SAMPLE_PERIOD}" \
    --trace-mode split \
    --trace-select l2 \
    --run-analyze 1 \
    --results-base "${trace_base}" \
    --use-ocperf 0 \
    --event-l2 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' \
    > "${trace_base}/${label}_trace.log" 2>&1 || {
      log "residual trace failed for ${label}; see ${trace_base}/${label}_trace.log"
      return 0
    }
}

run_final_compare_if_requested() {
  if [[ "${RUN_FINAL_COMPARE}" != "1" ]]; then
    return
  fi
  local compare_name="${BEST_NAME}"
  local compare_delta="${BEST_DELTA}"
  local compare_dir_src="${BEST_DIR}"
  local compare_bin="${BEST_BIN}"
  if [[ -n "${BEST_NEW_BIN}" && -f "${BEST_NEW_BIN}" ]]; then
    compare_name="${BEST_NEW_NAME}"
    compare_delta="${BEST_NEW_DELTA}"
    compare_dir_src="${BEST_NEW_DIR}"
    compare_bin="${BEST_NEW_BIN}"
    log "final compare will use best successful exact-target variant from this run: ${compare_name} delta=${compare_delta}%"
  else
    log "final compare will fall back to seed best: ${compare_name} delta=${compare_delta}%"
  fi
  require_file "${compare_bin}"
  require_file "${compare_dir_src}/plan/prefetcht1.plan.json"
  local compare_dir="${OUT_DIR}/final_compare"
  mkdir -p "${compare_dir}/profiles"
  cp -f "${BASELINE_PER_ITER}" "${compare_dir}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv" 2>/dev/null || {
    mkdir -p "${compare_dir}/profiles/baseline_qsort_${MAX_CYCLES}"
    cp -f "${BASELINE_PER_ITER}" "${compare_dir}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv"
  }
  cp -f "${BASELINE_SUMMARY}" "${compare_dir}/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv"

  eval "$(extract_plan_options "${compare_dir_src}/plan/prefetcht1.plan.json")"
  local prefetchit_base="${OUT_DIR}/prefetchit_same_positions"
  local prefetchit_run_id="same_${compare_name}_prefetchit1"
  local prefetchit_dir="${prefetchit_base}/${prefetchit_run_id}"
  local prefetchit_bin="${prefetchit_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-prefetchit1"
  if [[ ! -x "${prefetchit_bin}" ]]; then
    log "build same-position prefetchit1 for plateau best"
    RESULT_BASE="${prefetchit_base}" \
    RUN_ID="${prefetchit_run_id}" \
    TRACE_INPUTS="${TRACE_INPUTS}" \
    TRACE_INPUT="${TRACE_INPUTS%%:*}" \
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
    ALLOW_UNRESOLVED_TARGETS=1 \
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
    OBJDUMP_BIN=llvm-objdump-19 \
    ADDR2LINE_BIN=llvm-addr2line-19 \
    bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${OUT_DIR}/prefetchit1_best_build_eval.log" 2>&1
  fi
  require_file "${prefetchit_bin}"

  run_profile prefetcht1 "${compare_bin}" "${compare_dir}"
  run_profile prefetchit1 "${prefetchit_bin}" "${compare_dir}"

  python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_compare.py" \
    --input "baseline=${compare_dir}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --input "prefetcht1=${compare_dir}/profiles/prefetcht1_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --input "prefetchit1=${compare_dir}/profiles/prefetchit1_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --out-dir "${compare_dir}"

  if [[ "${RUN_RESIDUAL_TRACE}" == "1" ]]; then
    local trace_base="${OUT_DIR}/residual_trace"
    mkdir -p "${trace_base}"
    run_residual_trace prefetcht1 "${compare_bin}" "${trace_base}"
    run_residual_trace prefetchit1 "${prefetchit_bin}" "${trace_base}"
  fi

  {
    echo "# Prefetch Until Plateau"
    echo
    echo "- Best variant used for final compare: \`${compare_name}\`"
    echo "- Best runtime delta used for final compare: ${compare_delta}%"
    echo "- Best binary used for final compare: \`${compare_bin}\`"
    echo "- Seed/batch plateau best: \`${BEST_NAME}\` (${BEST_DELTA}%)"
    echo "- Best successful exact-target variant in this run: \`${BEST_NEW_NAME:-none}\` (${BEST_NEW_DELTA}%)"
    echo "- Final compare: \`${compare_dir}\`"
    echo "- Residual trace: \`${OUT_DIR}/residual_trace\`"
    echo
    if [[ -f "${compare_dir}/prefetch_compare_summary.md" ]]; then
      cat "${compare_dir}/prefetch_compare_summary.md"
    fi
  } > "${OUT_DIR}/plateau_final_report.md"
  log "final report: ${OUT_DIR}/plateau_final_report.md"
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_PER_ITER}"
require_dir "${SOURCE_WORK}"
require_trace_inputs

cat > "${OUT_DIR}/manifest.txt" <<EOF_MANIFEST
run_id=${RUN_ID}
out_dir=${OUT_DIR}
trace_inputs=${TRACE_INPUTS}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
screen_iterations=${SCREEN_ITERATIONS}
final_iterations=${FINAL_ITERATIONS}
build_jobs=${BUILD_JOBS}
autotune_hours_per_batch=${AUTOTUNE_HOURS_PER_BATCH}
min_improvement_abs_pct=${MIN_IMPROVEMENT_ABS_PCT}
patience_batches=${PATIENCE_BATCHES}
max_batches=${MAX_BATCHES}
wait_for_session=${WAIT_FOR_SESSION}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
baseline_per_iter=${BASELINE_PER_ITER}
source_work=${SOURCE_WORK}
seed_aggregate=${SEED_AGGREGATE}
seed_best_file=${SEED_BEST_FILE}
run_final_compare=${RUN_FINAL_COMPARE}
run_residual_trace=${RUN_RESIDUAL_TRACE}
EOF_MANIFEST

log "prefetch plateau search scheduled: ${OUT_DIR}"
wait_for_session_if_needed
seed_best
NO_IMPROVE_BATCHES=0

for batch in $(seq 1 "${MAX_BATCHES}"); do
  variants="${OUT_DIR}/batches/batch${batch}_variants.txt"
  write_batch_variants "${batch}" "${variants}" || break
  batch_dir="${OUT_DIR}/batch${batch}"
  log "batch ${batch} start: variants=${variants}"
  set +e
  RUN_ID="batch${batch}" \
  OUT_DIR="${batch_dir}" \
  VARIANTS_FILE="${variants}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  AUTOTUNE_HOURS="${AUTOTUNE_HOURS_PER_BATCH}" \
  SCREEN_ITERATIONS="${SCREEN_ITERATIONS}" \
  SCREEN_RUN_TRACE=0 \
  RUN_CONFIRMATION=0 \
  PREFETCH_MNEMONIC=prefetcht1 \
  PREFETCH_LABEL=prefetcht1 \
  BUILD_JOBS="${BUILD_JOBS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  ALLOW_UNRESOLVED_TARGETS=1 \
  STOP_RUNTIME_DELTA_PCT= \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh" > "${batch_dir}.driver.log" 2>&1
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    log "batch ${batch} autotune exited rc=${rc}; continuing if aggregate exists"
  fi
  if [[ -f "${batch_dir}/aggregate.csv" ]]; then
    maybe_update_best "${batch}" "${batch_dir}/aggregate.csv" || true
  else
    log "batch ${batch}: missing aggregate.csv"
    NO_IMPROVE_BATCHES=$((NO_IMPROVE_BATCHES + 1))
  fi
  if (( NO_IMPROVE_BATCHES >= PATIENCE_BATCHES )); then
    log "plateau reached: ${NO_IMPROVE_BATCHES} consecutive non-improving batches"
    break
  fi
  log "batch ${batch} done; current best=${BEST_NAME:-none} delta=${BEST_DELTA}% no_improve=${NO_IMPROVE_BATCHES}"
done

run_final_compare_if_requested
log "prefetch plateau search complete"
