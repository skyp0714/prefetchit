#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
WORK="${WORK:-${ROOT}/work/pgo_goal_20260713}"
OUT="${OUT:-${ROOT}/results/pgo_goal_20260713/screens/router_static_grpc_fullcode}"
RUNNER="${ROOT}/scripts/run_final_microsuite_paired.sh"
BASELINE="${WORK}/router-static-grpc-baseline/mid_tier_server"
ROUTER_DEPTH="${ROUTER_DEPTH:-16}"
ROUTER_PREWARM_DEPTH="${ROUTER_PREWARM_DEPTH:-${ROUTER_DEPTH}}"

default_variants=(
  cov25_b1_o0
  cov25_b1_o064
  cov25_d4_b4_o064
  cov50_d4_b1_o064
  cov50_d8_b2_o064
)

declare -A binary_dirs=(
  [cov25_b1_o0]="router-static-grpc-pgo-cov25_b1_o0"
  [cov25_b1_o064]="router-static-grpc-pgo-cov25-b1-o064"
  [cov25_d4_b4_o064]="router-static-grpc-pgo-cov25_d4_b4_o064"
  [cov50_d4_b1_o064]="router-static-grpc-pgo-cov50_d4_b1_o064"
  [cov50_d8_b2_o064]="router-static-grpc-pgo-cov50_d8_b2_o064"
  [cov25_tops_d4_b1_o0]="router-static-grpc-pgo-depth64-tops-d4-o0"
  [cov25_tops_d4_b1_o064]="router-static-grpc-pgo-depth64-tops-d4-o064"
  [cov25_tops_d8_b1_o0]="router-static-grpc-pgo-depth64-tops-d8-o0"
  [cov25_tops_d8_b1_o064]="router-static-grpc-pgo-depth64-tops-d8-o064"
  [cov25_tops_d4_t1_b1_o064]="router-static-grpc-pgo-depth64-tops-d4-t1-o064"
  [cov25_tops_d4_t3_b1_o064]="router-static-grpc-pgo-depth64-tops-d4-t3-o064"
  [cov25_tops_d4_t5_b1_o064]="router-static-grpc-pgo-depth64-tops-d4-t5-o064"
  [cov25_tops_d4_b1_o064128]="router-static-grpc-pgo-depth64-tops-d4-o064128"
  [cov25_tops_d4_b1_o064128192]="router-static-grpc-pgo-depth64-tops-d4-o064128192"
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
  directory="${binary_dirs[${variant}]:-}"
  [[ -n "${directory}" ]] || { echo "unknown variant: ${variant}" >&2; exit 2; }
  binary="${WORK}/${directory}/mid_tier_server"
  result="${OUT}/${variant}"
  [[ -x "${binary}" ]] || { echo "missing candidate: ${binary}" >&2; exit 2; }

  binary_sha256="$(sha256sum "${binary}" | awk '{print $1}')"
  assembly_prefetches="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch' || true)"
  status=ok
  if ! env \
    REPS="${REPS:-1}" DURATION="${DURATION:-15}" \
    PREWARM_DURATION=30 PREWARM_DEPTH="${ROUTER_PREWARM_DEPTH}" \
    MEASURE_SETTLE_DURATION=10 \
    GRPC_CORE_CAP=4 DISABLE_ASLR=1 ROUTER_PREPOPULATE=1 \
    ROUTER_LEAF_INSTANCES=4 ROUTER_FIXED_PREWARM_REQUESTS=120000 \
    ROUTER_FIXED_PREWARM_TIMEOUT=180 EVICT_CACHES=1 \
    EVICT_BYTES_PER_CORE=8388608 EVICT_PASSES=4 \
    EXPECTED_MID_TIDS=20 REQUIRE_MATCHED_MID_TIDS=1 \
    DEPTH="${ROUTER_DEPTH}" PARALLELISM=4 DISPATCH=4 RESPONSES=4 \
    MAX_ATTEMPTS=5 \
    "${RUNNER}" router "${BASELINE}" "${binary}" "${result}"; then
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
