#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 router|setalgebra|hdsearch" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
SUITE="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src"
DEB_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/data_prefetch_reexperiment_20260712/microsuite_handoff/$1}"
CXX="${CXX:-clang++-19}"
BENCHMARK="$1"
GRPC_MAX_THREADS="${GRPC_MAX_THREADS:-8}"
OPENMP_FLAG=-fopenmp=libgomp
if [[ "$(basename "${CXX}")" == g++* ]]; then
  OPENMP_FLAG=-fopenmp
fi

COMMON_FLAGS=(
  -std=c++17 -O3 -g -fno-omit-frame-pointer -pthread
  -I"${DEB_ROOT}/usr/include"
  -I/usr/lib/gcc/x86_64-linux-gnu/11/include
  -I"${SUITE}" -I/usr/local/include
  "${OPENMP_FLAG}" -Wall
)
GRPC_LINK=(
  /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2
  /lib/x86_64-linux-gnu/libgrpc.so.10.0.0
  /lib/x86_64-linux-gnu/libgpr.so.10.0.0
  /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4
  -pthread -lgomp -lssl -lcrypto -lz
  /lib/x86_64-linux-gnu/libcares.so.2 -ldl
)

labels=(
  baseline
  producer_tag1 producer_tag2 producer_tag4 producer_tag8
  producer_code1 producer_code2 producer_code4 producer_code8
  producer_tag1_code1 producer_tag2_code2 producer_tag4_code2 producer_tag4_code4
  consumer_tag1_code1 consumer_tag2_code2 consumer_tag4_code4
  both_tag1_code1 both_tag2_code2 both_tag4_code4
  producer_tag2_code2_l2 producer_tag2_code2_l1 producer_tag2_code2_nta
  producer_tag2_l2 producer_tag2_l1 producer_tag2_nta
  producer_tag1_nta producer_tag4_l2 producer_tag4_l1 producer_tag4_nta
  producer_tag8_nta
)
stages=(0 1 1 1 1 1 1 1 1 1 1 1 1 2 2 2 3 3 3 1 1 1 1 1 1 1 1 1 1 1)
tag_lines=(0 1 2 4 8 0 0 0 0 1 2 4 4 1 2 4 1 2 4 2 2 2 2 2 2 1 4 4 4 8)
code_lines=(0 0 0 0 0 1 2 4 8 1 2 2 4 1 2 4 1 2 4 2 2 2 0 0 0 0 0 0 0 0)
localities=(3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 2 1 0 2 1 0 0 2 1 0 0)
lsh_data_lines=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)
lsh_lookaheads=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)

if [[ "${BENCHMARK}" == hdsearch ]]; then
  labels+=(
    lsh_line1 lsh_line2 lsh_line4 lsh_line8
    lsh_line2_l2 lsh_line2_l1 lsh_line2_nta
    lsh_ahead16 lsh_ahead32 lsh_ahead64
    lsh_line2_ahead16 lsh_line2_ahead32
    producer_tag1_lsh_line2 producer_tag2_lsh_line2 producer_tag4_lsh_line2
  )
  stages+=(0 0 0 0 0 0 0 0 0 0 0 0 1 1 1)
  tag_lines+=(0 0 0 0 0 0 0 0 0 0 0 0 1 2 4)
  code_lines+=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)
  localities+=(3 3 3 3 2 1 0 3 3 3 3 3 3 3 3)
  lsh_data_lines+=(1 2 4 8 2 2 2 0 0 0 2 2 2 2 2)
  lsh_lookaheads+=(0 0 0 0 0 0 0 16 32 64 16 32 0 0 0)
fi
if [[ "${BASELINE_ONLY:-0}" == 1 ]]; then
  labels=(baseline)
  stages=(0)
  tag_lines=(0)
  code_lines=(0)
  localities=(3)
  lsh_data_lines=(0)
  lsh_lookaheads=(0)
fi

mkdir -p "${OUT}"
EXTRA_LINK=()
EXTRA_FLAGS=()

case "${BENCHMARK}" in
  router)
    SRC="${SUITE}/Router"
    MAIN="${SRC}/mid_tier_service/service/mid_tier_server.cc"
    STAGE_MACRO=PREFETCHIT_ROUTER_HANDOFF_STAGE
    TAG_MACRO=PREFETCHIT_ROUTER_TAG_LINES
    CODE_MACRO=PREFETCHIT_ROUTER_CODE_LINES
    LOCALITY_MACRO=PREFETCHIT_ROUTER_PREFETCH_LOCALITY
    "${CXX}" "${COMMON_FLAGS[@]}" -I"${SRC}" -c \
      "${SRC}/lookup_service/service/helper_files/client_helper.cc" \
      -o "${OUT}/client_helper.o"
    "${CXX}" "${COMMON_FLAGS[@]}" -I"${SRC}" -c \
      "${SRC}/mid_tier_service/service/helper_files/router_server_helper.cc" \
      -o "${OUT}/router_server_helper.o"
    LINK_OBJECTS=(
      "${SRC}/protoc_files/lookup.pb.o" "${SRC}/protoc_files/lookup.grpc.pb.o"
      "${SRC}/protoc_files/router.pb.o" "${SRC}/protoc_files/router.grpc.pb.o"
      "${SRC}/mid_tier_service/src/spookyhash.o"
      "${OUT}/client_helper.o" "${OUT}/router_server_helper.o"
      "${SRC}/mid_tier_service/service/helper_files/timing.o"
      "${SRC}/mid_tier_service/service/helper_files/utils.o"
    )
    ;;
  setalgebra)
    SRC="${SUITE}/SetAlgebra"
    MAIN="${SRC}/union_service/service/mid_tier_server.cc"
    STAGE_MACRO=PREFETCHIT_SET_HANDOFF_STAGE
    TAG_MACRO=PREFETCHIT_SET_TAG_LINES
    CODE_MACRO=PREFETCHIT_SET_CODE_LINES
    LOCALITY_MACRO=PREFETCHIT_SET_PREFETCH_LOCALITY
    "${CXX}" "${COMMON_FLAGS[@]}" -I"${SRC}" -c \
      "${SRC}/intersection_service/service/helper_files/client_helper.cc" \
      -o "${OUT}/client_helper.o"
    "${CXX}" "${COMMON_FLAGS[@]}" -I"${SRC}" -c \
      "${SRC}/union_service/service/helper_files/union_server_helper.cc" \
      -o "${OUT}/union_server_helper.o"
    LINK_OBJECTS=(
      "${SRC}/protoc_files/intersection.pb.o" "${SRC}/protoc_files/intersection.grpc.pb.o"
      "${SRC}/protoc_files/union.pb.o" "${SRC}/protoc_files/union.grpc.pb.o"
      "${OUT}/client_helper.o" "${OUT}/union_server_helper.o"
      "${SRC}/union_service/service/helper_files/timing.o"
      "${SRC}/union_service/service/helper_files/utils.o"
    )
    ;;
  hdsearch)
    SRC="${SUITE}/HDSearch"
    MAIN="${SRC}/mid_tier_service/service/mid_tier_server.cc"
    STAGE_MACRO=PREFETCHIT_HD_HANDOFF_STAGE
    TAG_MACRO=PREFETCHIT_HD_TAG_LINES
    CODE_MACRO=PREFETCHIT_HD_CODE_LINES
    LOCALITY_MACRO=PREFETCHIT_HD_PREFETCH_LOCALITY
    LINK_OBJECTS=(
      "${SRC}/protoc_files/bucket.pb.o" "${SRC}/protoc_files/bucket.grpc.pb.o"
      "${SRC}/protoc_files/mid_tier.pb.o" "${SRC}/protoc_files/mid_tier.grpc.pb.o"
      "${SRC}/bucket_service/src/multiple_points.o"
      "${SRC}/bucket_service/src/point.o"
      "${SRC}/bucket_service/src/utils.o"
      "${SRC}/bucket_service/src/dist_calc.o"
      "${SRC}/bucket_service/src/custom_priority_queue.o"
      "${SRC}/bucket_service/service/helper_files/client_helper.o"
      "${SRC}/mid_tier_service/service/helper_files/mid_tier_server_helper.o"
      "${SRC}/mid_tier_service/service/helper_files/timing.o"
      "${SRC}/mid_tier_service/service/helper_files/utils.o"
    )
    EXTRA_LINK=(-lopenblas -llz4)
    EXTRA_FLAGS=(-I"${SRC}/mid_tier_service/src/cpp" -mavx2 -mavx)
    ;;
  *)
    echo "unsupported benchmark: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

printf 'label,stage,tag_lines,code_lines,locality,lsh_data_lines,lsh_lookahead,prefetch_opcodes,binary\n' > "${OUT}/build_summary.csv"
for i in "${!labels[@]}"; do
  label="${labels[$i]}"
  if [[ -n "${BUILD_VARIANTS:-}" ]] &&
      [[ " ${BUILD_VARIANTS} " != *" ${label} "* ]]; then
    continue
  fi
  object="${OUT}/mid_tier_server.${label}.o"
  binary="${OUT}/mid_tier_server.${label}"
  "${CXX}" "${COMMON_FLAGS[@]}" -I"${SRC}" "${EXTRA_FLAGS[@]}" \
    "-DPREFETCHIT_GRPC_MAX_THREADS=${GRPC_MAX_THREADS}" \
    "-D${STAGE_MACRO}=${stages[$i]}" \
    "-D${TAG_MACRO}=${tag_lines[$i]}" \
    "-D${CODE_MACRO}=${code_lines[$i]}" \
    "-D${LOCALITY_MACRO}=${localities[$i]}" \
    "-DPREFETCHIT_HD_LSH_DATA_LINES=${lsh_data_lines[$i]}" \
    "-DPREFETCHIT_HD_LSH_LOOKAHEAD=${lsh_lookaheads[$i]}" \
    "-DPREFETCHIT_HD_LSH_PREFETCH_LOCALITY=${localities[$i]}" \
    -c "${MAIN}" -o "${object}"
  "${CXX}" "${LINK_OBJECTS[@]}" "${object}" -o "${binary}" \
    "${GRPC_LINK[@]}" "${EXTRA_LINK[@]}"
  count="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch' || true)"
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "${label}" "${stages[$i]}" \
    "${tag_lines[$i]}" "${code_lines[$i]}" "${localities[$i]}" \
    "${lsh_data_lines[$i]}" "${lsh_lookaheads[$i]}" \
    "${count}" "${binary}" >> "${OUT}/build_summary.csv"
done

cat "${OUT}/build_summary.csv"
