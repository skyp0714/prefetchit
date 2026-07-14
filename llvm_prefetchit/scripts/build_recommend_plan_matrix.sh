#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
PLAN_ROOT="${1:?usage: $0 PLAN_ROOT BIN_DIR METADATA_DIR}"
BIN_DIR="${2:?usage: $0 PLAN_ROOT BIN_DIR METADATA_DIR}"
METADATA_DIR="${3:?usage: $0 PLAN_ROOT BIN_DIR METADATA_DIR}"
BUILD_DIR="${BUILD_DIR:-${ROOT}/work/pgo_goal_20260713/recommend-plan-matrix-build}"
BUILDER="${ROOT}/scripts/build_microsuite_static_grpc.sh"
COMPONENT="${COMPONENT:-mid}"
case "${COMPONENT}" in
  mid) output_name=mid_tier_server ;;
  leaf) output_name=cf_server ;;
  *) echo "COMPONENT must be mid or leaf" >&2; exit 2 ;;
esac

mkdir -p "${BIN_DIR}" "${METADATA_DIR}"
printf 'label,plan_injections,assembly_prefetches,sha256\n' > "${METADATA_DIR}/build_summary.csv"

while IFS=, read -r label _depth_min _depth_max _max_injections selected_injections _rest; do
  [[ "${label}" != label ]] || continue
  plan="${PLAN_ROOT}/${label}/prefetchit.plan.json"
  meta="${METADATA_DIR}/${label}"
  binary="${BIN_DIR}/${output_name}.${label}"
  PREFETCHIT_COMPONENT="${COMPONENT}" \
    GRPC_MAX_THREADS=4 GRPC_CLIENT_MAX_THREADS=4 JOBS="${JOBS:-16}" \
    "${BUILDER}" recommend pgo "${BUILD_DIR}" "${plan}"
  mkdir -p "${meta}"
  cp "${BUILD_DIR}/${output_name}" "${binary}"
  cp "${BUILD_DIR}/build.conf" "${BUILD_DIR}/build.log" \
    "${BUILD_DIR}/configure.log" "${BUILD_DIR}/prefetch_pass.log" \
    "${BUILD_DIR}/assembly_prefetch_count.txt" \
    "${BUILD_DIR}/${output_name}.sha256" "${meta}/"
  sha="$(sha256sum "${binary}" | awk '{print $1}')"
  assembly_prefetches="$(cat "${meta}/assembly_prefetch_count.txt")"
  printf '%s,%s,%s,%s\n' "${label}" "${selected_injections}" \
    "${assembly_prefetches}" "${sha}" >> "${METADATA_DIR}/build_summary.csv"
done < "${PLAN_ROOT}/manifest.csv"

rm -rf "${BUILD_DIR}"
cat "${METADATA_DIR}/build_summary.csv"
