#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INPUT="${INPUT_PLAN:-${ROOT}/results/pgo_goal_20260713/recommend/plans_static_racefix/base/cov100/combined.plan.json}"
OUT="${OUT_DIR:-${ROOT}/results/pgo_goal_20260713/recommend/plans_incremental_v1}"
DERIVER="${ROOT}/tools/derive_prefetch_plan.py"

[[ -s "${INPUT}" ]] || { echo "missing input plan: ${INPUT}" >&2; exit 1; }
mkdir -p "${OUT}"
printf 'label,depth_min,depth_max,max_injections,selected_injections,selected_targets,new_covered_samples,site_samples\n' \
  > "${OUT}/manifest.csv"

while read -r label depth_min depth_max max_injections; do
  plan="${OUT}/${label}/prefetchit.plan.json"
  python3 "${DERIVER}" \
    --input "${INPUT}" \
    --output "${plan}" \
    --label "recommend_${label}" \
    --depth-min "${depth_min}" \
    --depth-max "${depth_max}" \
    --sites-per-target-after-filter 1 \
    --max-injections "${max_injections}" \
    --selection-order new-samples \
    --min-new-covered-samples 1 \
    --exclude-site-target-same-cacheline \
    --byte-offsets 0
  printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "${label}" "${depth_min}" "${depth_max}" "${max_injections}" \
    "$(jq -r '.stats.selected_injections' "${plan}")" \
    "$(jq -r '.stats.selected_targets' "${plan}")" \
    "$(jq -r '.stats.selected_new_covered_samples' "${plan}")" \
    "$(jq -r '.stats.selected_site_samples' "${plan}")" \
    >> "${OUT}/manifest.csv"
done <<'MATRIX'
inc_d2_4_n5 2 4 5
inc_d2_4_n10 2 4 10
inc_d4_8_n5 4 8 5
inc_d4_8_n10 4 8 10
inc_d4_8_n20 4 8 20
inc_d8_16_n5 8 16 5
inc_d8_16_n10 8 16 10
inc_d8_16_n20 8 16 20
inc_d12_24_n5 12 24 5
inc_d12_24_n10 12 24 10
MATRIX

cat "${OUT}/manifest.csv"
