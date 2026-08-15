#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
TEMPLATE="${ROOT}/benchmarks/dcperf/packages/django_workload/templates/gen_icache_buster.py"
REUSE_OBJECT_DIR="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/django/icb_base"
OUT_ROOT="${OUT_ROOT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/django_manual_bins}"
DISTANCES="${DISTANCES:-2 4 8 16 32 64 128}"
NEXT_MODES="${NEXT_MODES:-0 1}"
SHUFFLE_SEED="${SHUFFLE_SEED:-1}"
CXX="${CXX:-clang++}"

mkdir -p "${OUT_ROOT}/generated"
python3 "${TEMPLATE}" \
  --num_methods=100000 --num_splits=24 --output_dir="${OUT_ROOT}/generated"
rm -f "${OUT_ROOT}"/generated/ICacheBuster.part*.cc

mapfile -t PART_OBJECTS < <(find "${REUSE_OBJECT_DIR}" -maxdepth 1 \
  -name 'ICacheBuster.part*.o' -print | sort -V)
if [[ "${#PART_OBJECTS[@]}" -ne 24 ]]; then
  printf 'expected 24 reusable part objects, found %s\n' "${#PART_OBJECTS[@]}" >&2
  exit 1
fi

printf 'label,distance,next_line,shuffle_seed,library,method0_address,sha256\n' > "${OUT_ROOT}/manifest.csv"

build_variant() {
  local label="$1" distance="$2" next_line="$3"
  local dir="${OUT_ROOT}/${label}" lib method_addr sha
  mkdir -p "${dir}"
  cp -f "${OUT_ROOT}/generated/ICacheBuster.h" "${dir}/ICacheBuster.h"
  "${CXX}" -O2 -g -fno-omit-frame-pointer -fPIC -c \
    -DICACHE_BUSTER_PREFETCH_DISTANCE="${distance}" \
    -DICACHE_BUSTER_PREFETCH_NEXT_LINE="${next_line}" \
    -DICACHE_BUSTER_SHUFFLE_SEED="${SHUFFLE_SEED}" \
    -I"${OUT_ROOT}/generated" "${OUT_ROOT}/generated/ICacheBuster.cc" \
    -o "${dir}/ICacheBuster.o"
  lib="${dir}/libicachebuster.so"
  # Place the 100K target methods first so their addresses are identical in
  # baseline and prefetch variants; only the trailing dispatch code changes.
  "${CXX}" -shared -Wl,-soname,libicachebuster.so \
    -o "${lib}" "${PART_OBJECTS[@]}" "${dir}/ICacheBuster.o"
  method_addr="$(nm -D --defined-only "${lib}" | awk '$3 == "_Z11ICBMethod_0PjS_S_" {print $1}')"
  sha="$(sha256sum "${lib}" | awk '{print $1}')"
  printf '%s,%s,%s,%s,%s,%s,%s\n' \
    "${label}" "${distance}" "${next_line}" "${SHUFFLE_SEED}" \
    "${lib}" "${method_addr}" "${sha}" >> "${OUT_ROOT}/manifest.csv"
}

build_variant base 0 0
for distance in ${DISTANCES}; do
  for next_line in ${NEXT_MODES}; do
    suffix=target
    [[ "${next_line}" == 1 ]] && suffix=next
    build_variant "d${distance}_${suffix}" "${distance}" "${next_line}"
  done
done

unique_addresses="$(awk -F, 'NR > 1 {print $6}' "${OUT_ROOT}/manifest.csv" | sort -u | wc -l)"
if [[ "${unique_addresses}" -ne 1 ]]; then
  echo 'target method addresses differ across variants' >&2
  exit 1
fi

rm -rf "${OUT_ROOT}/generated"
printf 'built %s layout-stable variants in %s\n' \
  "$((1 + $(wc -w <<< "${DISTANCES}") * $(wc -w <<< "${NEXT_MODES}")))" "${OUT_ROOT}"
