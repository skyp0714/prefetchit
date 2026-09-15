#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 PLAN_VARIANTS_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SRC="${ROOT}/work/data_prefetch_reexperiment_20260712/memcached_variants/src"
PASS="${PASS:-${ROOT}/build/PrefetchITPass.so}"
PLANS="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
JOBS="${JOBS:-4}"
VARIANTS="${BUILD_VARIANTS:-cov25_d1_32_b16_o0 cov25_d1_32_b16_o064 cov50_d1_32_b16_o0 cov50_d1_32_b16_o064 cov75_d1_32_b16_o0 cov75_d1_32_b16_o064 cov100_d1_32_b16_o0 cov100_d1_32_b16_o064}"

BASE_CFLAGS=(
  -O3 -g -fno-omit-frame-pointer
  -Wno-error=strict-prototypes -Wno-error=unused-but-set-variable
  -Wno-language-extension-token -Wall -Werror -pedantic
  -Wmissing-prototypes -Wmissing-declarations -Wredundant-decls
  -DMEMCACHED_PREFETCH_CMD_TARGET=0
  -DMEMCACHED_PREFETCH_ASCII_GET_TARGETS=0
  -DMEMCACHED_PREFETCH_ASCII_GET_MASK=0x00
  -DMEMCACHED_PREFETCH_ASCII_GET_EARLY=0
  -DMEMCACHED_PREFETCH_ASCII_GET_LOCALITY=3
  -DMEMCACHED_PREFETCH_ASCII_GET_NEXT_LINE=0
  -DMEMCACHED_ASSOC_PREFETCH_BUCKET_LINES=0
  -DMEMCACHED_ASSOC_PREFETCH_CHAIN_LINES=0
  -DMEMCACHED_ASSOC_PREFETCH_MATCH_DATA_LINES=0
  -DMEMCACHED_ASSOC_PREFETCH_LOCALITY=3
)

mkdir -p "${OUT}"
printf 'label,status,planned_injections,planned_prefetches,assembly_prefetches,sha256,binary\n' \
  > "${OUT}/build_summary.csv"

build_one() {
  local label="$1" plan="$2" flags
  local binary="${OUT}/memcached.${label}"
  local log="${OUT}/build_${label}.log"
  flags="${BASE_CFLAGS[*]}"
  make -C "${SRC}" clean > "${log}" 2>&1
  if [[ -n "${plan}" ]]; then
    export PREFETCHIT_PLAN="${plan}"
    flags+=" -fpass-plugin=${PASS}"
  else
    unset PREFETCHIT_PLAN || true
  fi
  make -C "${SRC}" -j"${JOBS}" memcached CFLAGS="${flags}" >> "${log}" 2>&1
  cp -p "${SRC}/memcached" "${binary}"
  planned_injections=0
  planned_prefetches=0
  if [[ -n "${plan}" ]]; then
    planned_injections="$(jq -r '.stats.selected_injections' "${plan}")"
    planned_prefetches="$(jq -r '.stats.planned_prefetches' "${plan}")"
  fi
  assembly_prefetches="$(objdump -d "${binary}" 2>/dev/null | rg -c '\bprefetcht1\b' || true)"
  assembly_prefetches="${assembly_prefetches:-0}"
  sha="$(sha256sum "${binary}" | awk '{print $1}')"
  printf '%s,ok,%s,%s,%s,%s,%s\n' "${label}" "${planned_injections}" \
    "${planned_prefetches}" "${assembly_prefetches}" "${sha}" "${binary}" \
    | tee -a "${OUT}/build_summary.csv"
}

build_one baseline ""
for label in ${VARIANTS}; do
  plan="${PLANS}/${label}/prefetchit.plan.json"
  [[ -s "${plan}" ]] || { echo "missing plan: ${plan}" >&2; exit 2; }
  build_one "${label}" "${plan}"
done
