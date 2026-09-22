#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SRC="${ROOT}/benchmarks/dcperf/benchmarks/feedsim/src"
BUILD="${SRC}/build"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/feedsim_manual_bins}"
JOBS="${JOBS:-16}"
DEPS="${ROOT}/benchmarks/dcperf/benchmarks/feedsim/third_party/build-deps"
PREFIX="${DEPS};/usr/local"
# Reproduce the DCPerf installer's build environment exactly: the FeedSim
# ExternalProjects (folly, wangle, ...) were compiled against the vendored
# boost/glog/gflags under build-deps, so the rebuild must resolve the same
# headers and libraries even when newer system copies are installed.
STAGED_CMAKE="${ROOT}/benchmarks/dcperf/benchmarks/feedsim/third_party/cmake-3.14.5/staging/bin"
[[ -d "${STAGED_CMAKE}" ]] && export PATH="${STAGED_CMAKE}:${PATH}"
export PATH="${DEPS}/bin:${PATH}"
export PKG_CONFIG_PATH="${DEPS}/lib/pkgconfig:${DEPS}/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="${DEPS}/lib:${DEPS}/lib64:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="${DEPS}/lib:${DEPS}/lib64:${LIBRARY_PATH:-}"
export CPATH="${DEPS}/include:/usr/include/x86_64-linux-gnu:/usr/include/libdwarf:${CPATH:-}"
FS_CFLAGS="${BP_CFLAGS:--O3 -DNDEBUG}"
FS_CXXFLAGS="${BP_CXXFLAGS:--O3 -DNDEBUG -Wno-error=maybe-uninitialized -Wno-error=stringop-overflow }"
FS_LDFLAGS="${BP_LDFLAGS:-} -L${DEPS}/lib -L${DEPS}/lib64 -latomic -Wl,--export-dynamic"
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
    -DCMAKE_INCLUDE_PATH="${DEPS}/include;/usr/include/x86_64-linux-gnu;/usr/include/libdwarf" \
    -DCMAKE_LIBRARY_PATH="${DEPS}/lib;${DEPS}/lib64;/usr/local/lib" \
    -DCMAKE_C_COMPILER="${BP_CC:-gcc}" -DCMAKE_CXX_COMPILER="${BP_CXX:-g++}" \
    -DCMAKE_C_FLAGS_RELEASE="${FS_CFLAGS}" -DCMAKE_CXX_FLAGS_RELEASE="${FS_CXXFLAGS}" \
    -DCMAKE_EXE_LINKER_FLAGS_RELEASE="${FS_LDFLAGS}" \
    -DICACHEBUSTER_PREFETCH_DISTANCE="${distance}" \
    -DICACHEBUSTER_PREFETCH_NEXT_LINE="${next_line}" \
    -DICACHEBUSTER_SHUFFLE_SEED="${SHUFFLE_SEED}" \
    > "${OUT}/logs/configure_${label}.log" 2>&1
  # the installer applies the same lib64->lib fixup to the generated ninja file
  sed -i 's/lib64/lib/' "${BUILD}/build.ninja"
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
