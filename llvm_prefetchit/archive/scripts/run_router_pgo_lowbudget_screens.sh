#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BINS="${BINS:-${ROOT}/work/pgo_goal_20260713/bins/router4_grpc4_lowbudget_filter}"
OUT="${OUT:-${ROOT}/results/pgo_goal_20260713/screens/router4_grpc4_lowbudget_filter}"
RUNNER="${ROOT}/scripts/run_final_microsuite_paired.sh"
BASELINE="${BINS}/mid_tier_server.baseline"
EXPECTED_BASELINE_SHA256="225f3914af090062dba4563de32b8022c2fc3354ac3cb7de638a342bee5ecfca"

default_variants=(
  cov25_d4_32_b1_o0
  cov25_d4_32_b1_o064
  cov25_d4_32_b2_o0
  cov25_d4_32_b2_o064
  cov25_d4_32_b4_o064
  cov25_d1_32_b1_o064
  cov50_d4_32_b1_o0
  cov50_d4_32_b1_o064
  cov50_d4_32_b1_o064128
  cov50_d4_32_b2_o064
  cov50_d8_32_b1_o064
  cov75_d4_32_b1_o064
  cov25_d4_32_b2_o064128
  cov25_d4_32_b4_o064128
  cov25_d4_32_b4_o064128192
)

[[ -x "${BASELINE}" ]] || { echo "missing baseline: ${BASELINE}" >&2; exit 2; }
actual_hash="$(sha256sum "${BASELINE}" | awk '{print $1}')"
[[ "${actual_hash}" == "${EXPECTED_BASELINE_SHA256}" ]] || {
  echo "baseline hash mismatch: ${actual_hash}" >&2
  exit 2
}

if [[ -n "${VARIANTS:-}" ]]; then
  read -r -a variants <<< "${VARIANTS}"
else
  variants=("${default_variants[@]}")
fi

mkdir -p "${OUT}"
printf 'variant,status,speedup,l2i_reduction_pct,baseline_qps,prefetch_qps,summary\n' \
  > "${OUT}/screen_summary.csv"

for variant in "${variants[@]}"; do
  binary="${BINS}/mid_tier_server.${variant}"
  result="${OUT}/${variant}"
  [[ -x "${binary}" ]] || { echo "missing candidate: ${binary}" >&2; exit 2; }

  status=ok
  if ! env \
    REPS="${REPS:-1}" DURATION="${DURATION:-10}" \
    PREWARM_DURATION=30 PREWARM_DEPTH=16 MEASURE_SETTLE_DURATION=10 \
    GRPC_CORE_CAP=4 DISABLE_ASLR=1 ROUTER_PREPOPULATE=1 \
    ROUTER_LEAF_INSTANCES=4 ROUTER_FIXED_PREWARM_REQUESTS=60000 \
    ROUTER_FIXED_PREWARM_TIMEOUT=90 EVICT_CACHES=1 \
    EVICT_BYTES_PER_CORE=8388608 EVICT_PASSES=4 \
    EXPECTED_MID_TIDS=20 REQUIRE_MATCHED_MID_TIDS=1 \
    DEPTH=16 PARALLELISM=4 DISPATCH=4 RESPONSES=4 MAX_ATTEMPTS=5 \
    "${RUNNER}" router "${BASELINE}" "${binary}" "${result}"; then
    status=failed
  fi

  if [[ "${status}" == ok && -s "${result}/paired_summary.json" ]]; then
    printf '%s,%s,%s,%s,%s,%s,%s\n' \
      "${variant}" "${status}" \
      "$(jq -r '.speedup.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.l2i_reduction_pct.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.baseline_qps.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.prefetch_qps.mean' "${result}/paired_summary.json")" \
      "${result}/paired_summary.json" >> "${OUT}/screen_summary.csv"
  else
    printf '%s,%s,,,,,%s\n' "${variant}" "${status}" \
      "${result}/paired_summary.json" >> "${OUT}/screen_summary.csv"
  fi
done

cat "${OUT}/screen_summary.csv"
