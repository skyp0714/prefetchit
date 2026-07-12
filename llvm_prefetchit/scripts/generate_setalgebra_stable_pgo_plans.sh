#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
PROFILE_DIR="${PROFILE_DIR:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_profiles/rep5}"
BINARY="${BINARY:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2/mid_tier_server.baseline}"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_plans}"
PLANNER="${ROOT}/llvm_prefetchit/tools/prefetchit_trace_to_plan.py"

trace_args=()
for rep in 1 2 3 4 5; do
  trace="${PROFILE_DIR}/rep${rep}/trace"
  [[ -s "${trace}/lbr_symbolic_dump.txt" ]] || {
    echo "missing profile trace: ${trace}" >&2
    exit 2
  }
  trace_args+=(--trace-dir "${trace}")
done

mkdir -p "${OUT}"
sha256sum "${BINARY}" > "${OUT}/plan_binary.sha256"
for coverage in 25 50 75 100; do
  for mode in o0 o064; do
    offsets=0
    [[ "${mode}" == o064 ]] && offsets=0,64
    plan_dir="${OUT}/cov${coverage}_${mode}"
    mkdir -p "${plan_dir}"
    if [[ "${REUSE_PLANS:-0}" == 1 && -s "${plan_dir}/prefetchit.plan.json" ]]; then
      continue
    fi
    python3 "${PLANNER}" "${trace_args[@]}" \
      --binary "${BINARY}" \
      --validation-binary "${BINARY}" \
      --output "${plan_dir}/prefetchit.plan.json" \
      --summary-dir "${plan_dir}" \
      --top-k 999999 \
      --target-coverage-pct "${coverage}" \
      --depth-min 4 \
      --depth 24 \
      --site-budget-per-target 8 \
      --candidate-pool 1000 \
      --selection-mode top-sites \
      --target-ip-source lbr-to \
      --allow-unresolved-targets \
      --prefetch-mnemonic prefetcht1 \
      --prefetch-byte-offsets "${offsets}" \
      > "${plan_dir}/plan.log" 2>&1
  done
done

printf 'label,targets,injections,prefetches,samples,rejected_samples\n' > "${OUT}/plan_summary.csv"
for coverage in 25 50 75 100; do
  for mode in o0 o064; do
    label="cov${coverage}_${mode}"
    plan="${OUT}/${label}/prefetchit.plan.json"
    jq -r --arg name "${label}" '[
      $name,
      .stats.selected_targets,
      .stats.selected_injections,
      .stats.planned_prefetches,
      .stats.parsed_samples,
      .stats.validation_rejected_target_samples
    ] | @csv' "${plan}" >> "${OUT}/plan_summary.csv"
  done
done

cat "${OUT}/plan_summary.csv"
