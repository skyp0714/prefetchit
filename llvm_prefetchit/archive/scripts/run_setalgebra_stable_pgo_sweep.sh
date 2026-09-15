#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_microsuite_variant.sh"
BASE="${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2/mid_tier_server.baseline"
BIN_DIR="${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2_pgo_bins"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_pgo_sweep}"

labels=(base cov25_o0 cov25_o064 cov50_o0 cov50_o064 cov75_o0 cov75_o064 cov100_o0 cov100_o064)
bins=(
  "${BASE}"
  "${BIN_DIR}/mid_tier_server.cov25_o0"
  "${BIN_DIR}/mid_tier_server.cov25_o064"
  "${BIN_DIR}/mid_tier_server.cov50_o0"
  "${BIN_DIR}/mid_tier_server.cov50_o064"
  "${BIN_DIR}/mid_tier_server.cov75_o0"
  "${BIN_DIR}/mid_tier_server.cov75_o064"
  "${BIN_DIR}/mid_tier_server.cov100_o0"
  "${BIN_DIR}/mid_tier_server.cov100_o064"
)

mkdir -p "${OUT}"
printf 'label,attempt,runner_rc,valid,cpu_migrations\n' > "${OUT}/attempts.csv"
for i in "${!labels[@]}"; do
  label="${labels[$i]}"
  binary="${bins[$i]}"
  valid=0
  for attempt in 1 2 3; do
    set +e
    DURATION="${DURATION:-30}" PREWARM_DURATION="${PREWARM_DURATION:-60}" \
      PREWARM_DEPTH=32 GRPC_CORE_CAP=6 DEPTH=32 PARALLELISM=4 DISPATCH=4 \
      RESPONSES=1 "${RUNNER}" setalgebra "stable_v2_pgo_${label}" \
      "${binary}" "${OUT}/${label}"
    rc=$?
    set -e
    valid=0
    migrations=""
    if [[ "${rc}" == 0 && -s "${OUT}/${label}/summary.json" ]]; then
      valid="$(jq -r '.valid' "${OUT}/${label}/summary.json")"
      migrations="$(jq -r '.cpu_migrations' "${OUT}/${label}/summary.json")"
    fi
    printf '%s,%s,%s,%s,%s\n' "${label}" "${attempt}" "${rc}" \
      "${valid}" "${migrations}" | tee -a "${OUT}/attempts.csv"
    [[ "${valid}" == 1 ]] && break
  done
  [[ "${valid}" == 1 ]] || {
    echo "no valid run after 3 attempts: ${label}" >&2
    exit 1
  }
done

args=()
for label in "${labels[@]:1}"; do
  args+=(--variant "${OUT}/${label}/summary.json")
done
python3 "${ROOT}/llvm_prefetchit/tools/summarize_variant_sweep.py" \
  --baseline "${OUT}/base/summary.json" "${args[@]}" \
  --output-prefix "${OUT}/sweep_summary"
