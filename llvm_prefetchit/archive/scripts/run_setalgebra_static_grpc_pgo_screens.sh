#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
WORK="${WORK:-${ROOT}/work/pgo_goal_20260713}"
OUT="${OUT:-${ROOT}/results/pgo_goal_20260713/screens/setalgebra_static_grpc_depth32}"
RUNNER="${ROOT}/scripts/run_final_microsuite_paired.sh"
BASELINE="${BASELINE:-${WORK}/setalgebra-static-grpc-baseline/mid_tier_server}"
CANDIDATE_PREFIX="${CANDIDATE_PREFIX:-setalgebra-static-grpc-pgo-}"
EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS:-17}"
GRPC_CORE_CAP="${GRPC_CORE_CAP:-4}"

default_variants=(
  cov25_d4_32_b1_o0
  cov25_d4_32_b1_o064
  cov25_d8_32_b1_o0
  cov25_d8_32_b1_o064
  cov25_d4_32_b2_o0
  cov25_d4_32_b2_o064
  cov50_d4_32_b1_o0
  cov50_d4_32_b1_o064
  cov50_d8_32_b1_o064
)

[[ -x "${BASELINE}" ]] || { echo "missing baseline: ${BASELINE}" >&2; exit 2; }
if [[ -n "${VARIANTS:-}" ]]; then
  read -r -a variants <<< "${VARIANTS}"
else
  variants=("${default_variants[@]}")
fi

mkdir -p "${OUT}"
printf 'variant,status,binary_sha256,assembly_prefetches,speedup,l2i_reduction_pct,baseline_qps,prefetch_qps,summary\n' \
  > "${OUT}/screen_summary.csv"

for variant in "${variants[@]}"; do
  directory="${WORK}/${CANDIDATE_PREFIX}${variant}"
  binary="${directory}/mid_tier_server"
  result="${OUT}/${variant}"
  [[ -x "${binary}" ]] || { echo "missing candidate: ${binary}" >&2; exit 2; }

  binary_sha256="$(sha256sum "${binary}" | awk '{print $1}')"
  assembly_prefetches="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch' || true)"
  status=ok
  if ! env \
    REPS="${REPS:-1}" DURATION="${DURATION:-10}" \
    PREWARM_DURATION="${PREWARM_DURATION:-10}" PREWARM_DEPTH=32 \
    MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION:-5}" \
    GRPC_CORE_CAP="${GRPC_CORE_CAP}" DISABLE_ASLR=0 EVICT_CACHES=0 \
    EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS}" REQUIRE_MATCHED_MID_TIDS=1 \
    DEPTH=32 PARALLELISM=4 DISPATCH=4 RESPONSES=1 MAX_ATTEMPTS=5 \
    "${RUNNER}" setalgebra "${BASELINE}" "${binary}" "${result}"; then
    status=failed
  fi

  if [[ "${status}" == ok && -s "${result}/paired_summary.json" ]]; then
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "${variant}" "${status}" "${binary_sha256}" "${assembly_prefetches}" \
      "$(jq -r '.speedup.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.l2i_reduction_pct.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.baseline_qps.mean' "${result}/paired_summary.json")" \
      "$(jq -r '.prefetch_qps.mean' "${result}/paired_summary.json")" \
      "${result}/paired_summary.json" >> "${OUT}/screen_summary.csv"
  else
    printf '%s,%s,%s,%s,,,,,%s\n' \
      "${variant}" "${status}" "${binary_sha256}" "${assembly_prefetches}" \
      "${result}/paired_summary.json" >> "${OUT}/screen_summary.csv"
  fi
done

cat "${OUT}/screen_summary.csv"
