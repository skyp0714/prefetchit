#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
BINARY="${BINARY:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2/mid_tier_server.baseline}"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_static_plans}"
PLANNER="${ROOT}/static_return_prefetch/tools/static_branch_target_plan.py"

mkdir -p "${OUT}"
sha256sum "${BINARY}" > "${OUT}/static_binary.sha256"

generate() {
  local output="$1" label="$2" targets="$3" budget="$4" depth="$5"
  local offsets="$6" per_line="$7" per_function="$8"
  python3 "${PLANNER}" \
    --binary "${BINARY}" \
    --output "${OUT}/${output}.plan.json" \
    --label "${label}" \
    --prefetch-mnemonic prefetcht0 \
    --prefetch-byte-offsets "${offsets}" \
    --top-functions 0 \
    --min-function-size 16 \
    --branch-types CALL,COND,RET,UNCOND \
    --target-modes body \
    --site-depth "${depth}" \
    --max-injections "${budget}" \
    --max-injections-per-target-function "${per_function}" \
    --max-injections-per-target-cacheline "${per_line}" \
    --body-target-functions "${targets}" \
    --body-cachelines-per-function 64 \
    --min-body-target-size 16 \
    --rank-by structural-hotpath \
    --skip-same-cacheline \
    --pretty
}

generate bodytop1_b64_d4_o0_general_v5 stable_v2_top1_d4_o0 1 64 4 0 1 64
generate bodytop2_b128_d4_o0_general_v5 stable_v2_top2_d4_o0 2 128 4 0 1 64
generate bodytop2_b128_d4_o064_general_v5 stable_v2_top2_d4_o064 2 128 4 0,64 1 64
generate bodytop2_b256_s2_d4_o0_general_v5 stable_v2_top2_s2_d4_o0 2 256 4 0 2 128
generate bodytop2_b128_d8_o0_general_v5 stable_v2_top2_d8_o0 2 128 8 0 1 64
generate bodytop2_b128_d16_o0_general_v5 stable_v2_top2_d16_o0 2 128 16 0 1 64
generate bodytop2_b128_d32_o0_general_v5 stable_v2_top2_d32_o0 2 128 32 0 1 64
generate bodytop2_b128_d64_o0_general_v5 stable_v2_top2_d64_o0 2 128 64 0 1 64
generate bodytop3_b192_d4_o0_general_v5 stable_v2_top3_d4_o0 3 192 4 0 1 64
generate bodytop4_b256_d4_o0_general_v5 stable_v2_top4_d4_o0 4 256 4 0 1 64

printf 'plan,targets,injections,prefetches\n' > "${OUT}/plan_summary.csv"
for plan in "${OUT}"/*.plan.json; do
  jq -r --arg plan "$(basename "${plan}")" '[
    $plan,
    .options.body_target_functions,
    .stats.selected_injections,
    .stats.planned_prefetches
  ] | @csv' "${plan}" >> "${OUT}/plan_summary.csv"
done
cat "${OUT}/plan_summary.csv"
