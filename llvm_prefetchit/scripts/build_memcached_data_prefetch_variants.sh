#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SRC="${ROOT}/work/data_prefetch_reexperiment_20260712/memcached_variants/src"
BIN_DIR="${ROOT}/work/data_prefetch_reexperiment_20260712/memcached_variants/bins"

BASE_CFLAGS=(
  -O3 -g -fno-omit-frame-pointer
  -Wno-error=strict-prototypes -Wno-error=unused-but-set-variable
  -Wno-language-extension-token -Wall -Werror -pedantic
  -Wmissing-prototypes -Wmissing-declarations -Wredundant-decls
  -DMEMCACHED_PREFETCH_CMD_TARGET=0
  -DMEMCACHED_PREFETCH_ASCII_GET_TARGETS=0
)

mkdir -p "${BIN_DIR}"

build_variant() {
  local name="$1" mask="$2" early="$3" locality="$4" next_line="$5"
  local bucket_lines="${6:-0}" chain_lines="${7:-0}" match_lines="${8:-0}"
  local data_locality="${9:-3}"
  if [[ -n "${BUILD_VARIANTS:-}" ]] &&
      [[ " ${BUILD_VARIANTS} " != *" ${name} "* ]]; then
    return
  fi
  local flags=(
    "${BASE_CFLAGS[@]}"
    "-DMEMCACHED_PREFETCH_ASCII_GET_MASK=${mask}"
    "-DMEMCACHED_PREFETCH_ASCII_GET_EARLY=${early}"
    "-DMEMCACHED_PREFETCH_ASCII_GET_LOCALITY=${locality}"
    "-DMEMCACHED_PREFETCH_ASCII_GET_NEXT_LINE=${next_line}"
    "-DMEMCACHED_ASSOC_PREFETCH_BUCKET_LINES=${bucket_lines}"
    "-DMEMCACHED_ASSOC_PREFETCH_CHAIN_LINES=${chain_lines}"
    "-DMEMCACHED_ASSOC_PREFETCH_MATCH_DATA_LINES=${match_lines}"
    "-DMEMCACHED_ASSOC_PREFETCH_LOCALITY=${data_locality}"
  )

  rm -f "${SRC}/memcached-proto_text.o" "${SRC}/memcached-assoc.o" "${SRC}/memcached"
  make -C "${SRC}" -j2 memcached-proto_text.o memcached-assoc.o memcached CFLAGS="${flags[*]}"
  cp -p "${SRC}/memcached" "${BIN_DIR}/memcached.${name}"
}

rm -f "${SRC}/memcached-memcached.o"
make -C "${SRC}" -j2 memcached-memcached.o CFLAGS="${BASE_CFLAGS[*]}"

build_variant baseline 0x00 0 3 0
build_variant get_late 0x02 0 3 0
build_variant get_early 0x02 1 3 0
build_variant item_early 0x04 1 3 0
build_variant doitem_early 0x08 1 3 0
build_variant assoc_early 0x10 1 3 0
build_variant get_item_early 0x06 1 3 0
build_variant get_item_do_early 0x0e 1 3 0
build_variant get_item_do_assoc_early 0x1e 1 3 0
build_variant get_item_do_assoc_resp_early 0x3e 1 3 0
build_variant all_early 0x3f 1 3 0
build_variant get_item_do_assoc_early_l2 0x1e 1 2 0
build_variant get_item_do_assoc_early_l1 0x1e 1 1 0
build_variant get_item_do_assoc_early_nta 0x1e 1 0 0
build_variant get_early_next 0x02 1 3 1
build_variant get_item_early_next 0x06 1 3 1
build_variant get_item_do_early_next 0x0e 1 3 1
build_variant get_item_do_assoc_early_next 0x1e 1 3 1
build_variant all_early_next 0x3f 1 3 1
build_variant data_bucket1 0x00 0 3 0 1 0 0 3
build_variant data_bucket2 0x00 0 3 0 2 0 0 3
build_variant data_chain1 0x00 0 3 0 0 1 0 3
build_variant data_chain2 0x00 0 3 0 0 2 0 3
build_variant data_match1 0x00 0 3 0 0 0 1 3
build_variant data_match2 0x00 0 3 0 0 0 2 3
build_variant data_match4 0x00 0 3 0 0 0 4 3
build_variant data_match8 0x00 0 3 0 0 0 8 3
build_variant data_match16 0x00 0 3 0 0 0 16 3
build_variant data_match32 0x00 0 3 0 0 0 32 3
build_variant data_all1 0x00 0 3 0 1 1 1 3
build_variant data_all2 0x00 0 3 0 1 1 2 3
build_variant data_all4 0x00 0 3 0 1 1 4 3
build_variant data_all8 0x00 0 3 0 1 1 8 3
build_variant data_all16 0x00 0 3 0 1 1 16 3
build_variant data_all8_l2 0x00 0 3 0 1 1 8 2
build_variant data_all8_nta 0x00 0 3 0 1 1 8 0
build_variant data_all2_l2 0x00 0 3 0 1 1 2 2
build_variant data_all2_l1 0x00 0 3 0 1 1 2 1
build_variant data_all2_nta 0x00 0 3 0 1 1 2 0

sha256sum "${BIN_DIR}"/memcached.*
