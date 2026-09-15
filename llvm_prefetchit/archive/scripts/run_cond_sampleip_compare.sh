#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-cond_sampleip_compare_$(date +%Y%m%d_%H%M%S)}"
PLAN_DIR="${PLAN_DIR:-$(cat "${LLVM_PREFETCH_DIR}/results/latest_cond_sampleip_plans.txt")}" 
TRACE_INPUTS="${TRACE_INPUTS:-${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace01/l2_miss:${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace02/l2_miss:${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace03/l2_miss}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/cond_sampleip_compare/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
LOG_DIR="${OUT_DIR}/logs"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-3}"
BUILD_JOBS="${BUILD_JOBS:-8}"
FORCE_BUILD="${FORCE_BUILD:-0}"
FORCE_PROFILE="${FORCE_PROFILE:-0}"
VARIANT_LIMIT="${VARIANT_LIMIT:-0}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}" "${LOG_DIR}"
LOG="${OUT_DIR}/run.log"
VARIANTS_CSV="${OUT_DIR}/variants.csv"
BUILD_STATUS="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS="${OUT_DIR}/profile_status.tsv"
SUMMARY_CSV="${OUT_DIR}/summary.csv"
SUMMARY_MD="${OUT_DIR}/summary.md"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
require_file() { [[ -f "$1" ]] || { echo "[err] missing file: $1" | tee -a "${LOG}" >&2; exit 1; }; }
append_status() { local f="$1"; shift; { flock 9; local IFS=$'\t'; printf '%s\n' "$*"; } 9>"${f}.lock" >> "${f}"; }

require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_PER_ITER}"

write_variants() {
  cat > "${VARIANTS_CSV}" <<EOF
variant,group,label,plan
pgo_cond_cov25,pgo,PGO COND 25%,${PLAN_DIR}/pgo/pgo_cond_cov25.plan.json
pgo_cond_cov50,pgo,PGO COND 50%,${PLAN_DIR}/pgo/pgo_cond_cov50.plan.json
pgo_cond_cov75,pgo,PGO COND 75%,${PLAN_DIR}/pgo/pgo_cond_cov75.plan.json
pgo_cond_cov100,pgo,PGO COND 100%,${PLAN_DIR}/pgo/pgo_cond_cov100.plan.json
static_win16_top50k_current,static,Static win16 top50k current,${PLAN_DIR}/static/static_win16_top50000_current.plan.json
static_win16_top100k_current,static,Static win16 top100k current,${PLAN_DIR}/static/static_win16_top100000_current0.plan.json
static_win16_top50k_prev4,static,Static win16 top50k prev4,${PLAN_DIR}/static/static_win16_top50000_prev4.plan.json
EOF
}

build_one() {
  local variant="$1" label="$2" plan="$3"
  local run_dir="${RUNS_DIR}/${variant}"
  local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${variant}"
  local build_log="${LOG_DIR}/${variant}.build.log"
  if [[ "${FORCE_BUILD}" != "1" && -x "${bin}" ]]; then
    append_status "${BUILD_STATUS}" "${variant}" "ok" "0" "${run_dir}" "reuse"
    log "build reuse ${variant}"
    return 0
  fi
  require_file "${plan}"
  log "build start ${variant}: plan=${plan}"
  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${variant}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  EXTERNAL_PLAN="${plan}" \
  PREFETCH_LABEL="${variant}" \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  CONFIG="${CONFIG}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_BASELINE=0 RUN_PROFILE=0 RUN_TRACE=0 CLEAN_WORKDIR=1 \
  OBJDUMP_BIN=llvm-objdump-19 ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${build_log}" 2>&1
  local rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    append_status "${BUILD_STATUS}" "${variant}" "ok" "0" "${run_dir}" "built"
    log "build ok ${variant}"
  else
    append_status "${BUILD_STATUS}" "${variant}" "fail" "${rc}" "${run_dir}" "${build_log}"
    log "build fail ${variant}: rc=${rc}; log=${build_log}"
  fi
}

wait_for_slot() {
  while (( "$(jobs -rp | wc -l)" >= PARALLEL_BUILDS )); do
    wait -n || true
  done
}

run_builds() {
  : > "${BUILD_STATUS}"
  local n=0
  # Keep the loop in the current shell so the final wait observes build_one jobs.
  # A pipe would run the while body in a subshell, letting profiling start early.
  while IFS=, read -r variant group label plan; do
    n=$((n+1))
    if (( VARIANT_LIMIT > 0 && n > VARIANT_LIMIT )); then break; fi
    wait_for_slot
    build_one "${variant}" "${label}" "${plan}" </dev/null &
  done < <(tail -n +2 "${VARIANTS_CSV}")
  wait
}

profile_builds() {
  : > "${PROFILE_STATUS}"
  sort -V "${BUILD_STATUS}" | while IFS=$'\t' read -r variant status rc run_dir note; do
    if [[ "${status}" != "ok" ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "skip_build_fail" "${rc}" "${run_dir}" "${note:-}"
      continue
    fi
    local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${variant}"
    local per_iter="${run_dir}/detailed_profile/${variant}_qsort_${MAX_CYCLES}/per_iteration.csv"
    if [[ "${FORCE_PROFILE}" != "1" && -f "${per_iter}" ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "ok" "0" "${run_dir}" "reuse"
      log "profile reuse ${variant}"
      continue
    fi
    require_file "${bin}"
    log "profile start ${variant}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
    set +e
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "${variant}_qsort_${MAX_CYCLES}" \
      --sim-binary "${bin}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" \
      > "${LOG_DIR}/${variant}.profile.log" 2>&1 </dev/null
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "ok" "0" "${run_dir}" "profiled"
      log "profile ok ${variant}"
    else
      append_status "${PROFILE_STATUS}" "${variant}" "fail" "${rc}" "${run_dir}" "${LOG_DIR}/${variant}.profile.log"
      log "profile fail ${variant}: rc=${rc}; log=${LOG_DIR}/${variant}.profile.log"
    fi
  done
}

summarize() {
  python3 - "${OUT_DIR}" "${VARIANTS_CSV}" "${BASELINE_SUMMARY}" "${BASELINE_PER_ITER}" "${MAX_CYCLES}" <<'PY'
import csv, json, statistics, sys
from pathlib import Path
out=Path(sys.argv[1]); variants=Path(sys.argv[2]); baseline_summary=Path(sys.argv[3]); baseline_per=Path(sys.argv[4]); max_cycles=sys.argv[5]
def read_summary(path):
    return {r['metric']: float(r['mean']) for r in csv.DictReader(open(path, newline='', encoding='utf-8'))}
def read_per(path):
    rows=list(csv.DictReader(open(path, newline='', encoding='utf-8')))
    vals=[float(r['elapsed_sec']) for r in rows if r.get('elapsed_sec')]
    return len(vals), (statistics.mean(vals) if vals else 0.0), (statistics.stdev(vals) if len(vals)>1 else 0.0)
base=read_summary(baseline_summary); bn,bmean,bsd=read_per(baseline_per)
rows=[]
rows.append({'variant':'baseline','group':'baseline','label':'Baseline','status':'ok','runtime_mean':base.get('elapsed_sec',0),'runtime_stdev':bsd,'l2i_mpki':base.get('l2i_mpki',0),'l1i_mpki':base.get('l1i_mpki',0),'instructions':base.get('instructions',0),'speedup_pct':0.0,'injections':0,'planned_prefetches':0})
for v in csv.DictReader(open(variants, newline='', encoding='utf-8')):
    run_dir=out/'runs'/v['variant']
    summary=run_dir/'detailed_profile'/f"{v['variant']}_qsort_{max_cycles}"/'summary.csv'
    per=run_dir/'detailed_profile'/f"{v['variant']}_qsort_{max_cycles}"/'per_iteration.csv'
    plan=Path(v['plan'])
    if not summary.exists():
        rows.append({'variant':v['variant'],'group':v['group'],'label':v['label'],'status':'missing_profile','runtime_mean':0,'runtime_stdev':0,'l2i_mpki':0,'l1i_mpki':0,'instructions':0,'speedup_pct':0,'injections':'','planned_prefetches':''})
        continue
    s=read_summary(summary); n,mean,sd=read_per(per)
    st={}
    if plan.exists():
        st=json.load(open(plan)).get('stats',{})
    rt=s.get('elapsed_sec',0)
    speed=(base.get('elapsed_sec',0)/rt-1)*100 if rt else 0
    rows.append({'variant':v['variant'],'group':v['group'],'label':v['label'],'status':'ok','runtime_mean':rt,'runtime_stdev':sd,'l2i_mpki':s.get('l2i_mpki',0),'l1i_mpki':s.get('l1i_mpki',0),'instructions':s.get('instructions',0),'speedup_pct':speed,'injections':st.get('selected_injections',''),'planned_prefetches':st.get('planned_prefetches','')})
fields=list(rows[0])
with open(out/'summary.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
lines=['# COND Sample-IP Prefetch Compare','','| Variant | Group | Runtime mean (s) | Runtime stdev | Speedup % | L2I MPKI | L1I MPKI | Instructions | Injections |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
    def fmt(x, n=3):
        try: return f"{float(x):.{n}f}"
        except: return str(x)
    lines.append(f"| {r['label']} | {r['group']} | {fmt(r['runtime_mean'])} | {fmt(r['runtime_stdev'])} | {fmt(r['speedup_pct'])} | {fmt(r['l2i_mpki'])} | {fmt(r['l1i_mpki'])} | {fmt(r['instructions'],0)} | {r['injections']} |")
(out/'summary.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print('\n'.join(lines))
PY
}

write_variants
cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
plan_dir=${PLAN_DIR}
max_cycles=${MAX_CYCLES}
profile_iterations=${PROFILE_ITERATIONS}
profile_core=${PROFILE_CORE}
parallel_builds=${PARALLEL_BUILDS}
build_jobs=${BUILD_JOBS}
target_ip_source=sample-ip
EOF
log "start cond sample-ip compare: ${OUT_DIR}"
run_builds
profile_builds
summarize | tee -a "${LOG}"
ln -sfn "${OUT_DIR}" "${LLVM_PREFETCH_DIR}/results/cond_sampleip_compare/latest"
log "done"
