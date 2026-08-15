#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${ROOT}/benchmarks/dcperf/benchmarks/feedsim/src"
BUILD="${SRC}/build"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/feedsim_manual_bins}"
JOBS="${JOBS:-16}"
PREFIX="${ROOT}/benchmarks/dcperf/benchmarks/feedsim/third_party/build-deps;/usr/local"
DISTANCES="${DISTANCES:-4 8 16 32 64 128}"
NEXT_MODES="${NEXT_MODES:-0 1}"
INCLUDE_BASE="${INCLUDE_BASE:-1}"
RESET_MANIFEST="${RESET_MANIFEST:-1}"
SHUFFLE_SEED="${SHUFFLE_SEED:-1}"
LABEL_PREFIX="${LABEL_PREFIX:-}"

mkdir -p "${OUT}/logs"
if [[ "${RESET_MANIFEST}" == "1" || ! -f "${OUT}/manifest.csv" ]]; then
  printf 'label,distance,next_line,binary,size_bytes,prefetch_instructions,sha256\n' > "${OUT}/manifest.csv"
fi

build_one() {
  local distance="$1" next_line="$2" label binary prefetch_count checksum
  if [[ "${distance}" == "0" ]]; then
    label="${LABEL_PREFIX}base"
  elif [[ "${next_line}" == "1" ]]; then
    label="${LABEL_PREFIX}d${distance}_target_next"
  else
    label="${LABEL_PREFIX}d${distance}_target"
  fi
  cmake -S "${SRC}" -B "${BUILD}" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="${PREFIX}" \
    -DICACHEBUSTER_PREFETCH_DISTANCE="${distance}" \
    -DICACHEBUSTER_PREFETCH_NEXT_LINE="${next_line}" \
    -DICACHEBUSTER_SHUFFLE_SEED="${SHUFFLE_SEED}" \
    > "${OUT}/logs/configure_${label}.log" 2>&1
  cmake --build "${BUILD}" --target LeafNodeRank -j "${JOBS}" \
    > "${OUT}/logs/build_${label}.log" 2>&1
  binary="${OUT}/LeafNodeRank.${label}"
  cp -f "${BUILD}/workloads/ranking/LeafNodeRank" "${binary}"
  chmod 755 "${binary}"
  prefetch_count="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch(?:t[012]|nta|it[01])\b' || true)"
  checksum="$(sha256sum "${binary}" | awk '{print $1}')"
  printf '%s,%s,%s,%s,%s,%s,%s\n' \
    "${label}" "${distance}" "${next_line}" "${binary}" "$(stat -c %s "${binary}")" \
    "${prefetch_count}" "${checksum}" >> "${OUT}/manifest.csv"
}

if [[ "${INCLUDE_BASE}" == "1" ]]; then
  build_one 0 0
fi
for distance in ${DISTANCES}; do
  for next_mode in ${NEXT_MODES}; do
    build_one "${distance}" "${next_mode}"
  done
done

cat "${OUT}/manifest.csv"
