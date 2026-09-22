#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PROFILE_DIR="${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_profiles/rep5"
BINARY="${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2/mid_tier_server.baseline"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_tuned_plans}"
PLANNER="${ROOT}/llvm_prefetchit/tools/prefetchit_trace_to_plan.py"

traces=()
for rep in 1 2 3 4 5; do
  traces+=(--trace-dir "${PROFILE_DIR}/rep${rep}/trace")
done

generate() {
  local label="$1" coverage="$2" depth_min="$3" depth_max="$4"
  local policy="$5"
  local plan_dir="${OUT}/${label}_o0"
  local policy_args=()
  [[ -z "${policy}" ]] || policy_args+=(--branch-depth-policy "${policy}")
  mkdir -p "${plan_dir}"
  python3 "${PLANNER}" "${traces[@]}" \
    --binary "${BINARY}" --validation-binary "${BINARY}" \
    --output "${plan_dir}/prefetchit.plan.json" --summary-dir "${plan_dir}" \
    --top-k 999999 --target-coverage-pct "${coverage}" \
    --depth-min "${depth_min}" --depth "${depth_max}" \
    --site-budget-per-target 4 --candidate-pool 1000 \
    --selection-mode top-sites --target-ip-source lbr-to \
    --allow-unresolved-targets \
    --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0 \
    "${policy_args[@]}" > "${plan_dir}/plan.log" 2>&1

  python3 - "${plan_dir}/prefetchit.plan.json" "${OUT}/${label}_o064/prefetchit.plan.json" <<'PY'
import json
import sys
from pathlib import Path

source, output = map(Path, sys.argv[1:])
plan = json.loads(source.read_text())
plan["prefetch"]["byte_offsets"] = [0, 64]
plan["options"]["prefetch_byte_offsets"] = [0, 64]
plan["stats"]["planned_prefetches"] = 2 * plan["stats"]["selected_injections"]
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
PY
}

mkdir -p "${OUT}"
generate cov75_d4_12_b4 75 4 12 ""
generate cov75_d8_16_b4 75 8 16 ""
generate cov75_d12_24_b4 75 12 24 ""
generate cov100_d8_24_b4 100 8 24 ""
generate cov75_policy_b4 75 4 24 'CALL:4-10,COND:6-16,UNCOND:6-16,RET:10-24,IND:6-18,IND_CALL:4-12'

printf 'label,targets,injections,prefetches,depth_min,depth_max\n' > "${OUT}/plan_summary.csv"
for plan in "${OUT}"/*/prefetchit.plan.json; do
  label="$(basename "$(dirname "${plan}")")"
  jq -r --arg name "${label}" '[
    $name,
    .stats.selected_targets,
    .stats.selected_injections,
    .stats.planned_prefetches,
    .options.depth_min,
    .options.depth
  ] | @csv' "${plan}" >> "${OUT}/plan_summary.csv"
done
cat "${OUT}/plan_summary.csv"
