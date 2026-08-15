#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_microsuite_variant.sh"
BIN_DIR="${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2_tuned_bins"
BASE_SUMMARY="${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_pgo_sweep/base/summary.json"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_stable_v2_tuned_sweep}"

mkdir -p "${OUT}"
printf 'label,attempt,runner_rc,valid,cpu_migrations\n' > "${OUT}/attempts.csv"
variant_args=()
while IFS= read -r binary; do
  label="${binary##*.}"
  valid=0
  for attempt in 1 2 3; do
    set +e
    DURATION="${DURATION:-15}" PREWARM_DURATION="${PREWARM_DURATION:-30}" \
      PREWARM_DEPTH=32 GRPC_CORE_CAP=6 DEPTH=32 PARALLELISM=4 DISPATCH=4 \
      RESPONSES=1 "${RUNNER}" setalgebra "stable_v2_tuned_${label}" \
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
  [[ "${valid}" == 1 ]] || exit 1
  variant_args+=(--variant "${OUT}/${label}/summary.json")
done < <(find "${BIN_DIR}" -maxdepth 1 -type f -name 'mid_tier_server.*' ! -name '*.o' | sort)

python3 "${ROOT}/llvm_prefetchit/tools/summarize_variant_sweep.py" \
  --baseline "${BASE_SUMMARY}" "${variant_args[@]}" \
  --output-prefix "${OUT}/sweep_summary"
