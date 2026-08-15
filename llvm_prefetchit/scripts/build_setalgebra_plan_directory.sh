#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/SetAlgebra"
SERVICE="${SRC}/union_service/service"
PLANS="${PLANS:?set PLANS to a directory containing variant subdirectories}"
OUT="${OUT:?set OUT to the binary output directory}"
SUPPORT="${SUPPORT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2}"
PASS="${PASS:-${ROOT}/llvm_prefetchit/build/PrefetchITPass.so}"
DEB_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
CXX="${CXX:-clang++-19}"

mkdir -p "${OUT}"
printf 'label,planned_injections,planned_prefetches,injected,assembly_prefetches,binary\n' > "${OUT}/build_summary.csv"
while IFS= read -r plan; do
  label="$(basename "$(dirname "${plan}")")"
  object="${OUT}/mid_tier_server.${label}.o"
  binary="${OUT}/mid_tier_server.${label}"
  log="${OUT}/build_${label}.log"
  (
    cd "${SERVICE}"
    PREFETCHIT_PLAN="${plan}" "${CXX}" \
      -std=c++17 -O3 -g -fno-omit-frame-pointer -pthread \
      -I"${DEB_ROOT}/usr/include" -I/usr/lib/gcc/x86_64-linux-gnu/11/include \
      -I../ -I../../ -I. -fopenmp=libgomp -I/usr/local/include \
      -Wall -fpass-plugin="${PASS}" -c mid_tier_server.cc -o "${object}"
  ) > "${log}" 2>&1
  "${CXX}" \
    "${SRC}/protoc_files/intersection.pb.o" \
    "${SRC}/protoc_files/intersection.grpc.pb.o" \
    "${SRC}/protoc_files/union.pb.o" \
    "${SRC}/protoc_files/union.grpc.pb.o" \
    "${SUPPORT}/client_helper.o" "${SUPPORT}/union_server_helper.o" \
    "${SRC}/union_service/service/helper_files/timing.o" \
    "${SRC}/union_service/service/helper_files/utils.o" \
    "${object}" -o "${binary}" \
    /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 \
    /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 \
    /lib/x86_64-linux-gnu/libgpr.so.10.0.0 \
    /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 \
    -pthread -lgomp -lssl -lcrypto -lz \
    /lib/x86_64-linux-gnu/libcares.so.2 -ldl >> "${log}" 2>&1
  injected="$(sed -n 's/.*prefetchit-inject: injected=\([0-9][0-9]*\).*/\1/p' "${log}" | tail -1)"
  assembly="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch')"
  printf '%s,%s,%s,%s,%s,%s\n' "${label}" \
    "$(jq -r '.stats.selected_injections' "${plan}")" \
    "$(jq -r '.stats.planned_prefetches' "${plan}")" \
    "${injected:-0}" "${assembly}" "${binary}" >> "${OUT}/build_summary.csv"
done < <(find "${PLANS}" -mindepth 2 -maxdepth 2 -name prefetchit.plan.json | sort)

cat "${OUT}/build_summary.csv"
