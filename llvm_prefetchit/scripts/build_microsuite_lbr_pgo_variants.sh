#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 router|setalgebra|recommend|hdsearch PLAN_VARIANTS_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
SUITE="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src"
DEB_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
OMP19_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/omp19/root"
PASS="${PASS:-${ROOT}/llvm_prefetchit/build/PrefetchITPass.so}"
CXX="${CXX:-clang++-19}"
BENCHMARK="$1"
PLANS="$(readlink -f "$2")"
OUT="$(readlink -m "$3")"
GRPC_MAX_THREADS="${GRPC_MAX_THREADS:-8}"
FULL_REBUILD="${FULL_REBUILD:-0}"
HD_CLEANUP_RESPONSE_STATE="${HD_CLEANUP_RESPONSE_STATE:-0}"
HD_LOG_RESPONSE_STATE_INTERVAL="${HD_LOG_RESPONSE_STATE_INTERVAL:-0}"

COMMON_FLAGS=(
  -O3 -g -fno-omit-frame-pointer -pthread -fopenmp=libgomp -Wall
  -I"${DEB_ROOT}/usr/include"
  -I/usr/local/include
)
LINK_LIBS=(
  /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2
  /lib/x86_64-linux-gnu/libgrpc.so.10.0.0
  /lib/x86_64-linux-gnu/libgpr.so.10.0.0
  /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4
  -pthread -lgomp -lssl -lcrypto -lz
  /lib/x86_64-linux-gnu/libcares.so.2 -ldl
)
REBUILD_SOURCES=()
LINK_PREFIX=()
LINK_MIDDLE=()
MAIN_FLAGS=()
EXTRA_LINK=()

case "${BENCHMARK}" in
  router)
    SRC="${SUITE}/Router"
    MAIN="${SRC}/mid_tier_service/service/mid_tier_server.cc"
    COMMON_FLAGS+=(-std=c++17 -I/usr/lib/gcc/x86_64-linux-gnu/11/include -I"${SRC}")
    REBUILD_SOURCES=(
      "${SRC}/lookup_service/service/helper_files/client_helper.cc"
      "${SRC}/mid_tier_service/service/helper_files/router_server_helper.cc"
      "${MAIN}"
    )
    LINK_PREFIX=(
      "${SRC}/protoc_files/lookup.pb.o" "${SRC}/protoc_files/lookup.grpc.pb.o"
      "${SRC}/protoc_files/router.pb.o" "${SRC}/protoc_files/router.grpc.pb.o"
      "${SRC}/mid_tier_service/src/spookyhash.o"
    )
    LINK_MIDDLE=(
      "${SRC}/mid_tier_service/service/helper_files/timing.o"
      "${SRC}/mid_tier_service/service/helper_files/utils.o"
    )
    MAIN_FLAGS=(
      "-DPREFETCHIT_GRPC_MAX_THREADS=${GRPC_MAX_THREADS}"
      -DPREFETCHIT_ROUTER_HANDOFF_STAGE=0 -DPREFETCHIT_ROUTER_TAG_LINES=0
      -DPREFETCHIT_ROUTER_CODE_LINES=0 -DPREFETCHIT_ROUTER_PREFETCH_LOCALITY=3
      -DPREFETCHIT_HD_LSH_DATA_LINES=0 -DPREFETCHIT_HD_LSH_LOOKAHEAD=0
      -DPREFETCHIT_HD_LSH_PREFETCH_LOCALITY=3
    )
    if ((FULL_REBUILD == 1)); then
      REBUILD_SOURCES=(
        "${SRC}/protoc_files/lookup.pb.cc"
        "${SRC}/protoc_files/lookup.grpc.pb.cc"
        "${SRC}/protoc_files/router.pb.cc"
        "${SRC}/protoc_files/router.grpc.pb.cc"
        "${SRC}/mid_tier_service/src/spookyhash.cc"
        "${SRC}/lookup_service/service/helper_files/client_helper.cc"
        "${SRC}/mid_tier_service/service/helper_files/router_server_helper.cc"
        "${SRC}/mid_tier_service/service/helper_files/timing.cc"
        "${SRC}/mid_tier_service/service/helper_files/utils.cc"
        "${MAIN}"
      )
      LINK_PREFIX=()
      LINK_MIDDLE=()
    fi
    ;;
  setalgebra)
    SRC="${SUITE}/SetAlgebra"
    MAIN="${SRC}/union_service/service/mid_tier_server.cc"
    COMMON_FLAGS+=(-std=c++17 -I/usr/lib/gcc/x86_64-linux-gnu/11/include -I"${SRC}")
    REBUILD_SOURCES=(
      "${SRC}/intersection_service/service/helper_files/client_helper.cc"
      "${SRC}/union_service/service/helper_files/union_server_helper.cc"
      "${MAIN}"
    )
    LINK_PREFIX=(
      "${SRC}/protoc_files/intersection.pb.o" "${SRC}/protoc_files/intersection.grpc.pb.o"
      "${SRC}/protoc_files/union.pb.o" "${SRC}/protoc_files/union.grpc.pb.o"
    )
    LINK_MIDDLE=(
      "${SRC}/union_service/service/helper_files/timing.o"
      "${SRC}/union_service/service/helper_files/utils.o"
    )
    MAIN_FLAGS=(
      "-DPREFETCHIT_GRPC_MAX_THREADS=${GRPC_MAX_THREADS}"
      -DPREFETCHIT_SET_HANDOFF_STAGE=0 -DPREFETCHIT_SET_TAG_LINES=0
      -DPREFETCHIT_SET_CODE_LINES=0 -DPREFETCHIT_SET_PREFETCH_LOCALITY=3
      -DPREFETCHIT_HD_LSH_DATA_LINES=0 -DPREFETCHIT_HD_LSH_LOOKAHEAD=0
      -DPREFETCHIT_HD_LSH_PREFETCH_LOCALITY=3
    )
    ;;
  hdsearch)
    SRC="${SUITE}/HDSearch"
    MAIN="${SRC}/mid_tier_service/service/mid_tier_server.cc"
    COMMON_FLAGS+=(
      -std=c++17 -I"${OMP19_ROOT}/usr/lib/llvm-19/lib/clang/19/include" -I"${SRC}"
    )
    REBUILD_SOURCES=("${MAIN}")
    LINK_PREFIX=(
      "${SRC}/protoc_files/bucket.pb.o" "${SRC}/protoc_files/bucket.grpc.pb.o"
      "${SRC}/protoc_files/mid_tier.pb.o" "${SRC}/protoc_files/mid_tier.grpc.pb.o"
      "${SRC}/bucket_service/src/multiple_points.o" "${SRC}/bucket_service/src/point.o"
      "${SRC}/bucket_service/src/utils.o" "${SRC}/bucket_service/src/dist_calc.o"
      "${SRC}/bucket_service/src/custom_priority_queue.o"
      "${SRC}/bucket_service/service/helper_files/client_helper.o"
      "${SRC}/mid_tier_service/service/helper_files/mid_tier_server_helper.o"
      "${SRC}/mid_tier_service/service/helper_files/timing.o"
      "${SRC}/mid_tier_service/service/helper_files/utils.o"
    )
    MAIN_FLAGS=(
      -I"${SRC}/mid_tier_service/src/cpp" -mavx2 -mavx
      "-DPREFETCHIT_GRPC_MAX_THREADS=${GRPC_MAX_THREADS}"
      -DPREFETCHIT_HD_HANDOFF_STAGE=0 -DPREFETCHIT_HD_TAG_LINES=0
      -DPREFETCHIT_HD_CODE_LINES=0 -DPREFETCHIT_HD_PREFETCH_LOCALITY=3
      -DPREFETCHIT_HD_LSH_DATA_LINES=0 -DPREFETCHIT_HD_LSH_LOOKAHEAD=0
      -DPREFETCHIT_HD_LSH_PREFETCH_LOCALITY=3
      "-DPREFETCHIT_HD_CLEANUP_RESPONSE_STATE=${HD_CLEANUP_RESPONSE_STATE}"
      "-DPREFETCHIT_HD_LOG_RESPONSE_STATE_INTERVAL=${HD_LOG_RESPONSE_STATE_INTERVAL}"
    )
    EXTRA_LINK=(-lopenblas -llz4)
    ;;
  recommend)
    SRC="${SUITE}/Recommend"
    MAIN="${SRC}/recommender_service/service/mid_tier_server.cc"
    COMMON_FLAGS+=(
      -std=c++14 -mavx2 -mavx
      -I"${OMP19_ROOT}/usr/lib/llvm-19/lib/clang/19/include"
      -I"${SRC}" -I"${SRC}/protoc_files"
      -I"${SRC}/cf_service/service" -I"${SRC}/cf_service/service/helper_files"
      -I"${SRC}/recommender_service/service"
      -I"${SRC}/recommender_service/service/helper_files"
      -I"${SRC}/recommender_service/src"
    )
    REBUILD_SOURCES=(
      "${SRC}/protoc_files/cf.pb.cc" "${SRC}/protoc_files/cf.grpc.pb.cc"
      "${SRC}/protoc_files/recommender.pb.cc" "${SRC}/protoc_files/recommender.grpc.pb.cc"
      "${SRC}/cf_service/service/helper_files/client_helper.cc"
      "${SRC}/recommender_service/service/helper_files/recommender_server_helper.cc"
      "${SRC}/recommender_service/service/helper_files/timing.cc"
      "${SRC}/recommender_service/service/helper_files/utils.cc"
      "${MAIN}"
    )
    ;;
  *)
    echo "unsupported benchmark: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

obj_name() {
  local source="$1" rel="${source#"${SRC}/"}"
  rel="${rel//\//__}"
  printf '%s.o\n' "${rel%.*}"
}

sum_stat() {
  local key="$1" log="$2"
  sed -n "s/.* ${key}=\([0-9][0-9]*\).*/\1/p" "${log}" | awk '{sum += $1} END {print sum + 0}'
}

mkdir -p "${OUT}"
printf 'benchmark,label,status,planned_injections,planned_prefetches,injected,symbol_offset,got_symbol_offset,blockaddress,missing_target_fn,missing_target_symbol_offset,missing_site_fn,missing_site_loc,assembly_prefetches,sha256,binary\n' \
  > "${OUT}/build_summary.csv"

default_variants=""
for coverage in 25 50 75 100; do
  default_variants+=" cov${coverage}_d1_32_b16_o0 cov${coverage}_d1_32_b16_o064"
done
if [[ "${BUILD_BASE_ONLY:-0}" == 1 ]]; then
  variants=""
else
  variants="${BUILD_VARIANTS:-${default_variants}}"
fi

build_one() {
  local label="$1" plan="$2" dir="${OUT}/${label}" log="${OUT}/build_${label}.log"
  local -a plugin_flags=() objects=() link_objects=()
  local source object
  rm -rf "${dir}"
  mkdir -p "${dir}"
  : > "${log}"
  if [[ -n "${plan}" ]]; then
    plugin_flags=(-fpass-plugin="${PASS}")
    export PREFETCHIT_PLAN="${plan}"
  else
    unset PREFETCHIT_PLAN || true
  fi
  for source in "${REBUILD_SOURCES[@]}"; do
    object="${dir}/$(obj_name "${source}")"
    objects+=("${object}")
    extra=()
    [[ "${source}" != "${MAIN}" ]] || extra=("${MAIN_FLAGS[@]}")
    if ! "${CXX}" "${COMMON_FLAGS[@]}" "${extra[@]}" "${plugin_flags[@]}" \
      -c "${source}" -o "${object}" >> "${log}" 2>&1; then
      unset PREFETCHIT_PLAN || true
      return 1
    fi
  done
  link_objects=("${LINK_PREFIX[@]}")
  for ((i=0; i<${#REBUILD_SOURCES[@]}-1; i++)); do
    link_objects+=("${objects[$i]}")
  done
  link_objects+=("${LINK_MIDDLE[@]}" "${objects[-1]}")
  if ! "${CXX}" "${link_objects[@]}" -o "${OUT}/mid_tier_server.${label}" \
    "${LINK_LIBS[@]}" "${EXTRA_LINK[@]}" >> "${log}" 2>&1; then
    unset PREFETCHIT_PLAN || true
    return 1
  fi
  unset PREFETCHIT_PLAN || true
}

labels=(baseline)
plans=("")
for label in ${variants}; do
  plan="${PLANS}/${label}/prefetchit.plan.json"
  [[ -s "${plan}" ]] || { echo "missing plan: ${plan}" >&2; exit 2; }
  labels+=("${label}")
  plans+=("${plan}")
done

for index in "${!labels[@]}"; do
  label="${labels[$index]}"
  plan="${plans[$index]}"
  status=ok
  if ! build_one "${label}" "${plan}"; then
    status=build_failed
  fi
  binary="${OUT}/mid_tier_server.${label}"
  planned_injections=0
  planned_prefetches=0
  if [[ -n "${plan}" ]]; then
    planned_injections="$(jq -r '.stats.selected_injections' "${plan}")"
    planned_prefetches="$(jq -r '.stats.planned_prefetches' "${plan}")"
  fi
  if [[ "${status}" == ok ]]; then
    assembly="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch' || true)"
    hash="$(sha256sum "${binary}" | awk '{print $1}')"
  else
    assembly=0
    hash=""
  fi
  log="${OUT}/build_${label}.log"
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "${BENCHMARK}" "${label}" "${status}" "${planned_injections}" \
    "${planned_prefetches}" "$(sum_stat injected "${log}")" \
    "$(sum_stat symbol_offset_target "${log}")" \
    "$(sum_stat got_symbol_offset_target "${log}")" \
    "$(sum_stat blockaddress_target "${log}")" \
    "$(sum_stat missing_target_fn "${log}")" \
    "$(sum_stat missing_target_symbol_offset "${log}")" \
    "$(sum_stat missing_site_fn "${log}")" "$(sum_stat missing_site_loc "${log}")" \
    "${assembly}" "${hash}" "${binary}" >> "${OUT}/build_summary.csv"
  if [[ "${status}" != ok && "${CONTINUE_ON_FAIL:-0}" != 1 ]]; then
    tail -100 "${log}" >&2
    exit 1
  fi
done

cat "${OUT}/build_summary.csv"
