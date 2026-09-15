#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${STATIC_DIR}/.." && pwd)"
LLVM_DIR="${REPO_ROOT}/llvm_prefetchit"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-ret_cost_v2_static_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${STATIC_DIR}/results/ret_cost_v2_runtime/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
LOG_DIR="${OUT_DIR}/logs"
PLAN_ROOT="${OUT_DIR}/plans"
STATIC_ROOT="${OUT_DIR}/static_analysis"
PLOTS_DIR="${OUT_DIR}/plots"
LOG="${OUT_DIR}/run.log"

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-6}"
BUILD_JOBS="${BUILD_JOBS:-8}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetcht1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0,64}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_DIR}/work/verilator_llvm_prefetchit}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
REF_RET_DIR="${REF_RET_DIR:-${STATIC_DIR}/results/ret_static_vs_pgo_limit/ret_static_vs_pgo_20260626_090419}"
PGO_RET100_RUN_DIR="${PGO_RET100_RUN_DIR:-${REF_RET_DIR}/runs/pgo_ret_cov100}"
PGO_RET100_PLAN="${PGO_RET100_PLAN:-${PGO_RET100_RUN_DIR}/plan/${PREFETCH_LABEL}.plan.json}"
STATIC_TARGETS="${STATIC_TARGETS:-${STATIC_ROOT}/static_ret_nested_b1500_p32.csv}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
FORCE_BUILD="${FORCE_BUILD:-0}"
FORCE_PROFILE="${FORCE_PROFILE:-0}"
RUN_PROFILES="${RUN_PROFILES:-1}"
STATIC_VARIANTS="${STATIC_VARIANTS:-static_nested_top1500_callsite_b1 static_nested_top1500_mixed_b32 static_nested_top3000_callsite_b1 static_nested_top3000_mixed_b32 static_nested_top5000_callsite_b1 static_nested_top5000_mixed_b32}"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}" "${LOG_DIR}" "${PLAN_ROOT}" "${STATIC_ROOT}" "${PLOTS_DIR}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
require_file() { [[ -f "$1" ]] || { echo "[err] missing file: $1" | tee -a "${LOG}" >&2; exit 1; }; }
require_dir() { [[ -d "$1" ]] || { echo "[err] missing dir: $1" | tee -a "${LOG}" >&2; exit 1; }; }

if [[ -z "${TRACE_INPUTS}" ]]; then
  TRACE_INPUTS="${LLVM_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace01/l2_miss:${LLVM_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace02/l2_miss:${LLVM_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace03/l2_miss"
fi
IFS=':' read -r -a TRACE_DIRS <<< "${TRACE_INPUTS}"
TRACE_ARGS=()
for td in "${TRACE_DIRS[@]}"; do
  require_file "${td}/lbr_symbolic_dump.txt"
  TRACE_ARGS+=(--trace-dir "${td}")
done

require_file "${BASELINE_BINARY}"
require_dir "${SOURCE_WORK}"
require_file "${BASELINE_PER_ITER}"
require_file "${PGO_RET100_PLAN}"

METADATA="${OUT_DIR}/variant_metadata.csv"
BUILD_STATUS="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS="${OUT_DIR}/profile_status.tsv"
: > "${BUILD_STATUS}"
: > "${PROFILE_STATUS}"
echo "label,category,pgo_ret_coverage_pct,static_top_k,site_strategy,site_budget,target_weighted_recall,site_weighted_coverage,run_dir,plan_path,build_status,profile_status" > "${METADATA}"

append_status() {
  local file="$1"; shift
  { flock 9; local IFS=$'\t'; printf '%s\n' "$*"; } 9>"${file}.lock" >> "${file}"
}

metadata_add() {
  local label="$1" category="$2" cov="$3" topk="$4" strategy="$5" budget="$6" target_recall="$7" site_cov="$8" run_dir="$9" plan_path="${10}" build_status="${11}" profile_status="${12}"
  python3 - <<'PY' "${METADATA}" "$label" "$category" "$cov" "$topk" "$strategy" "$budget" "$target_recall" "$site_cov" "$run_dir" "$plan_path" "$build_status" "$profile_status"
import csv, sys
path=sys.argv[1]
row={
 'label':sys.argv[2], 'category':sys.argv[3], 'pgo_ret_coverage_pct':sys.argv[4], 'static_top_k':sys.argv[5],
 'site_strategy':sys.argv[6], 'site_budget':sys.argv[7], 'target_weighted_recall':sys.argv[8], 'site_weighted_coverage':sys.argv[9],
 'run_dir':sys.argv[10], 'plan_path':sys.argv[11], 'build_status':sys.argv[12], 'profile_status':sys.argv[13],
}
rows=[]
with open(path, newline='', encoding='utf-8') as f:
    reader=csv.DictReader(f)
    fields=reader.fieldnames
    for r in reader:
        if r['label'] != row['label']:
            rows.append(r)
rows.append(row)
with open(path, 'w', newline='', encoding='utf-8') as f:
    w=csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(rows)
PY
}

metadata_update_status() {
  local label="$1" build_status="$2" profile_status="$3"
  python3 - <<'PY' "${METADATA}" "$label" "$build_status" "$profile_status"
import csv,sys
path,label,build,profile=sys.argv[1:]
rows=list(csv.DictReader(open(path, newline='', encoding='utf-8')))
fields=rows[0].keys() if rows else []
for r in rows:
    if r['label']==label:
        r['build_status']=build
        r['profile_status']=profile
with open(path,'w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(rows)
PY
}

metric_lookup() {
  local csv="$1" topk="$2" strategy="$3" budget="$4" metric="$5"
  python3 - <<'PY' "$csv" "$topk" "$strategy" "$budget" "$metric"
import csv, sys
path, topk, strategy, budget, metric = sys.argv[1:]
value=''
with open(path, newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row.get('top_k') == topk and row.get('strategy') == strategy and row.get('site_budget') == budget:
            value=row.get(metric, '')
            break
print(value)
PY
}

build_with_external_plan() {
  local label="$1"
  local plan="$2"
  local run_dir="${RUNS_DIR}/${label}"
  local build_log="${LOG_DIR}/${label}.build.log"
  local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  local staged_plan="${PLAN_ROOT}/external/${label}.plan.json"
  if [[ "${FORCE_BUILD}" != "1" && -x "${bin}" ]]; then
    append_status "${BUILD_STATUS}" "${label}" "ok" "0" "${run_dir}" "reuse"
    return 0
  fi
  mkdir -p "$(dirname "${staged_plan}")"
  cp -f "${plan}" "${staged_plan}"
  log "build start ${label}"
  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${label}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_DIRS[0]}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  CONFIG="${CONFIG}" \
  EXTERNAL_PLAN="${staged_plan}" \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  PREFETCH_LABEL="${PREFETCH_LABEL}" \
  PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_BASELINE=0 \
  RUN_PROFILE=0 \
  RUN_TRACE=0 \
  CLEAN_WORKDIR=1 \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_DIR}/scripts/static/run_prefetcht1_l2_eval.sh" > "${build_log}" 2>&1
  local rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    append_status "${BUILD_STATUS}" "${label}" "ok" "0" "${run_dir}" "built"
    log "build ok ${label}"
  else
    append_status "${BUILD_STATUS}" "${label}" "fail" "${rc}" "${run_dir}" "${build_log}"
    log "build fail ${label}: rc=${rc}; log=${build_log}"
  fi
}

wait_for_slot() {
  while (( "$(jobs -rp | wc -l)" >= PARALLEL_BUILDS )); do sleep 20; done
}

profile_built_variants() {
  if [[ "${RUN_PROFILES}" != "1" ]]; then
    log "skip profiling: RUN_PROFILES=${RUN_PROFILES}"
    return 0
  fi
  mapfile -t labels < <(python3 - <<'PY' "${METADATA}"
import csv,sys
for r in csv.DictReader(open(sys.argv[1], newline='', encoding='utf-8')):
    if r['category'] == 'static_v2':
        print(r['label'])
PY
)
  for label in "${labels[@]}"; do
    local run_dir="${RUNS_DIR}/${label}"
    local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
    if ! grep -q -P "^${label}\tok\t" "${BUILD_STATUS}" 2>/dev/null; then
      append_status "${PROFILE_STATUS}" "${label}" "skip_build_fail" "1" "${run_dir}" ""
      metadata_update_status "${label}" "fail" "skip_build_fail"
      continue
    fi
    if [[ ! -x "${bin}" ]]; then
      append_status "${PROFILE_STATUS}" "${label}" "fail" "missing_binary" "${run_dir}" ""
      metadata_update_status "${label}" "ok" "fail"
      continue
    fi
    local per_iter="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/per_iteration.csv"
    if [[ "${FORCE_PROFILE}" != "1" && -f "${per_iter}" ]]; then
      append_status "${PROFILE_STATUS}" "${label}" "ok" "0" "${run_dir}" "reuse"
      metadata_update_status "${label}" "ok" "ok"
      log "profile reuse ${label}"
      continue
    fi
    log "profile start ${label}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
    set +e
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
      --sim-binary "${bin}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" > "${LOG_DIR}/${label}.profile.log" 2>&1
    local rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      append_status "${PROFILE_STATUS}" "${label}" "ok" "0" "${run_dir}" "profiled"
      metadata_update_status "${label}" "ok" "ok"
      log "profile ok ${label}"
    else
      append_status "${PROFILE_STATUS}" "${label}" "fail" "${rc}" "${run_dir}" "${LOG_DIR}/${label}.profile.log"
      metadata_update_status "${label}" "ok" "fail"
      log "profile fail ${label}: rc=${rc}"
    fi
  done
}

static_variant_to_plan() {
  local label="$1" topk strategy budget
  case "${label}" in
    static_nested_top1500_callsite_b1) topk=1500; strategy=callsite; budget=1 ;;
    static_nested_top1500_mixed_b32) topk=1500; strategy=mixed-call-ret-d1; budget=32 ;;
    static_nested_top3000_callsite_b1) topk=3000; strategy=callsite; budget=1 ;;
    static_nested_top3000_mixed_b32) topk=3000; strategy=mixed-call-ret-d1; budget=32 ;;
    static_nested_top5000_callsite_b1) topk=5000; strategy=callsite; budget=1 ;;
    static_nested_top5000_mixed_b32) topk=5000; strategy=mixed-call-ret-d1; budget=32 ;;
    static_nested_top3000_spread64_b8) topk=3000; strategy=spread-distance-64k; budget=8 ;;
    static_nested_top5000_spread64_b8) topk=5000; strategy=spread-distance-64k; budget=8 ;;
    *) echo "[err] unknown static variant ${label}" >&2; return 1 ;;
  esac
  local site_csv="${SITE_EVAL}/site_plans/top${topk}_budget${budget}_${strategy}.csv"
  local run_dir="${RUNS_DIR}/${label}"
  local plan_dir="${run_dir}/plan"
  local plan="${plan_dir}/${PREFETCH_LABEL}.plan.json"
  require_file "${site_csv}"
  mkdir -p "${plan_dir}"
  log "convert static plan ${label}: topk=${topk} strategy=${strategy} budget=${budget}"
  python3 "${STATIC_DIR}/tools/ret/static_site_plan_to_prefetch_plan.py" \
    --binary "${BASELINE_BINARY}" \
    --targets "${STATIC_TARGETS}" \
    --site-plan "${site_csv}" \
    --output "${plan}" \
    --top-k "${topk}" \
    --prefetch-mnemonic "${PREFETCH_MNEMONIC}" \
    --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
    --label "${label}" \
    --nm llvm-nm-19 \
    --addr2line llvm-addr2line-19 \
    --pretty > "${LOG_DIR}/${label}.plan.log" 2>&1
  local target_recall site_cov
  target_recall="$(metric_lookup "${SITE_EVAL}/site_policy_metrics.csv" "${topk}" "${strategy}" "${budget}" target_weighted_recall)"
  site_cov="$(metric_lookup "${SITE_EVAL}/site_policy_metrics.csv" "${topk}" "${strategy}" "${budget}" site_weighted_coverage)"
  metadata_add "${label}" "static_v2" "" "${topk}" "${strategy}" "${budget}" "${target_recall}" "${site_cov}" "${run_dir}" "${plan}" "pending" "pending"
}

log "RET cost-v2 static sweep start: ${OUT_DIR}"
log "trace_inputs=${TRACE_INPUTS}"
log "variants=${STATIC_VARIANTS}"
log "parallel_builds=${PARALLEL_BUILDS} build_jobs=${BUILD_JOBS}"

if [[ ! -f "${STATIC_TARGETS}" ]]; then
  log "generate nested static RET candidates"
  python3 "${STATIC_DIR}/tools/ret/static_return_target_candidates.py" \
    --binary "${BASELINE_BINARY}" \
    --out-csv "${STATIC_TARGETS}" \
    --mode nested \
    --nested-base-count 1500 \
    --nested-per-callee 32 \
    --external-penalty 5 \
    --one-shot-penalty 500 \
    --synthetic-external-size 512 \
    --ras-size 32 \
    --max-depth 96 \
    --nm llvm-nm-19 \
    --objdump llvm-objdump-19 > "${LOG_DIR}/static_target_generation.log" 2>&1
fi

log "evaluate static target overlap"
python3 "${STATIC_DIR}/tools/ret/evaluate_static_targets.py" \
  --binary "${BASELINE_BINARY}" \
  --candidates "${STATIC_TARGETS}" \
  "${TRACE_ARGS[@]}" \
  --ret-mode immediate \
  --k 1000,1500,3000,5000,7500,10000,50000,100000 \
  --out-dir "${STATIC_ROOT}/target_overlap" \
  --nm llvm-nm-19 > "${LOG_DIR}/static_target_overlap.log" 2>&1

SITE_EVAL="${STATIC_ROOT}/site_policy_eval"
log "evaluate injection site policies"
python3 "${STATIC_DIR}/tools/ret/static_injection_site_experiment.py" \
  --binary "${BASELINE_BINARY}" \
  --targets "${STATIC_TARGETS}" \
  "${TRACE_ARGS[@]}" \
  --out-dir "${SITE_EVAL}" \
  --top-k 1500,3000,5000 \
  --strategy callsite \
  --strategy mixed-call-ret-d1 \
  --strategy spread-distance-64k \
  --site-budget-list 1,8,32 \
  --nm llvm-nm-19 \
  --objdump llvm-objdump-19 > "${LOG_DIR}/static_site_policy_eval.log" 2>&1

metadata_add "pgo_ret_cov100" "pgo_ret" "100" "" "lbr-top-sites" "8" "" "" "${PGO_RET100_RUN_DIR}" "${PGO_RET100_PLAN}" "ok" "ok"

for label in ${STATIC_VARIANTS}; do
  static_variant_to_plan "${label}"
done

log "start parallel builds"
mapfile -t build_rows < <(python3 - <<'PY' "${METADATA}"
import csv,sys
for r in csv.DictReader(open(sys.argv[1], newline='', encoding='utf-8')):
    if r['category'] == 'static_v2':
        print(r['label'] + '\t' + r['plan_path'])
PY
)
for row in "${build_rows[@]}"; do
  IFS=$'\t' read -r label plan <<< "${row}"
  wait_for_slot
  build_with_external_plan "${label}" "${plan}" </dev/null &
done
wait

while IFS=$'\t' read -r label status rc run_dir note; do
  [[ -n "${label}" ]] || continue
  profile="pending"
  [[ "${status}" == "fail" ]] && profile="skip_build_fail"
  metadata_update_status "${label}" "${status}" "${profile}"
done < "${BUILD_STATUS}"

log "build phase complete; start sequential profiles"
profile_built_variants

log "generate final summary and plot"
python3 "${STATIC_DIR}/tools/ret/summarize_ret_static_vs_pgo.py" \
  --metadata "${METADATA}" \
  --baseline-per-iteration "${BASELINE_PER_ITER}" \
  --profile-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
  --out-dir "${PLOTS_DIR}" > "${LOG_DIR}/summary.log" 2>&1

log "numeric validation"
python3 - <<'PY' "${PLOTS_DIR}/ret_static_vs_pgo_summary.csv" | tee "${OUT_DIR}/numeric_validation.txt"
import csv, math, sys
bad=[]
rows=list(csv.DictReader(open(sys.argv[1], newline='', encoding='utf-8')))
for r in rows:
    if r.get('valid') != '1':
        continue
    for k,v in r.items():
        if v == '':
            continue
        if k in ('label','category','run_dir','plan_path','per_iteration_csv','site_strategy'):
            continue
        try:
            x=float(v)
        except ValueError:
            continue
        if not math.isfinite(x):
            bad.append((r.get('label'),k,v))
print('rows', len(rows))
print('bad_numeric', bad)
if bad:
    raise SystemExit(1)
PY

ln -sfn "${OUT_DIR}" "${STATIC_DIR}/results/ret_cost_v2_runtime/latest"
log "complete: ${OUT_DIR}"
