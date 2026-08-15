#!/usr/bin/env bash
set -euo pipefail

cd /home/hnpark2/prefetchit
BASE=/home/hnpark2/prefetchit/llvm_prefetchit/results/prefetcht_branch_type_sweep/prefetcht_branch_types_20260624_041139
PLAN=${PLAN:-${BASE}/merged_call_ret_plan/prefetcht1_call_ret.plan.json}
RUN_ID=${RUN_ID:-v07_branch_call_ret_each50}
LOG=${BASE}/logs/${RUN_ID}.driver.log

trace_inputs_from_plan() {
  python3 - "$1" <<'PY'
import json, sys
plan=json.load(open(sys.argv[1], encoding='utf-8'))
print(':'.join(plan.get('trace_dirs') or []))
PY
}

TRACE_INPUTS=${TRACE_INPUTS:-$(trace_inputs_from_plan "${PLAN}")}
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] no trace inputs found in ${PLAN}" >&2
  exit 1
fi

{
  echo "[$(date '+%F %T')] build/profile CALL+RET each50 start"
  RESULT_BASE=${BASE}/runs \
  RUN_ID=${RUN_ID} \
  EXTERNAL_PLAN=${PLAN} \
  TRACE_INPUTS=${TRACE_INPUTS} \
  TRACE_INPUT=${TRACE_INPUTS%%:*} \
  BASELINE_BINARY=/home/hnpark2/prefetchit/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig \
  SOURCE_WORK=/home/hnpark2/prefetchit/llvm_prefetchit/work/verilator_llvm_prefetchit \
  CONFIG=DualMegaBoomAndSingleRocketConfig \
  PREFETCH_MNEMONIC=prefetcht1 \
  PREFETCH_LABEL=prefetcht1 \
  MAX_CYCLES=538240 \
  PROFILE_ITERATIONS=3 \
  PROFILE_CORE=0 \
  BUILD_JOBS=8 \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  RUN_BASELINE=0 \
  RUN_PROFILE=1 \
  RUN_TRACE=0 \
  CLEAN_WORKDIR=1 \
  bash llvm_prefetchit/scripts/run_prefetcht1_l2_eval.sh
  echo "[$(date '+%F %T')] build/profile CALL+RET each50 done"

  META=${BASE}/branch_type_variants_with_call_ret.csv
  cp ${BASE}/branch_type_variants.csv ${META}
  python3 - <<PY
from pathlib import Path
base=Path('${BASE}')
meta=base/'branch_type_variants_with_call_ret.csv'
text=meta.read_text(encoding='utf-8')
row=f"v07_branch_call_ret_each50,CALL+RET,CALL+RET,{base}/runs/v07_branch_call_ret_each50,ok,ok\n"
if 'v07_branch_call_ret_each50' not in text:
    with meta.open('a', encoding='utf-8') as f:
        f.write(row)
PY
  python3 llvm_prefetchit/tools/plot_branch_type_prefetch_results.py \
    --metadata ${META} \
    --baseline-per-iteration /home/hnpark2/prefetchit/llvm_prefetchit/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_538240/per_iteration.csv \
    --general-per-iteration /home/hnpark2/prefetchit/llvm_prefetchit/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/prefetcht1_qsort_538240/per_iteration.csv \
    --profile-name prefetcht1_qsort_538240 \
    --out-dir ${BASE}/plots_call_ret
  echo "[$(date '+%F %T')] plot update done"
} > "${LOG}" 2>&1
