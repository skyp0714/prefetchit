#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/SetAlgebra"
SERVICE="${SRC}/union_service/service"
PLANS="${PLANS:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/microsuite_set_exact_plans}"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_exact_bins}"
SUPPORT_OBJECT_DIR="${SUPPORT_OBJECT_DIR:-}"
PASS="${PASS:-${ROOT}/llvm_prefetchit/build/PrefetchITPass.so}"
DEB_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
CXX="${CXX:-clang++-19}"

CLIENT_HELPER_OBJECT="${SRC}/intersection_service/service/helper_files/client_helper.o"
UNION_HELPER_OBJECT="${SRC}/union_service/service/helper_files/union_server_helper.o"
if [[ -n "${SUPPORT_OBJECT_DIR}" ]]; then
  CLIENT_HELPER_OBJECT="${SUPPORT_OBJECT_DIR}/client_helper.o"
  UNION_HELPER_OBJECT="${SUPPORT_OBJECT_DIR}/union_server_helper.o"
fi

mkdir -p "${OUT}"

link_binary() {
  local object="$1" output="$2" log="$3"
  "${CXX}" \
    "${SRC}/protoc_files/intersection.pb.o" \
    "${SRC}/protoc_files/intersection.grpc.pb.o" \
    "${SRC}/protoc_files/union.pb.o" \
    "${SRC}/protoc_files/union.grpc.pb.o" \
    "${CLIENT_HELPER_OBJECT}" \
    "${UNION_HELPER_OBJECT}" \
    "${SRC}/union_service/service/helper_files/timing.o" \
    "${SRC}/union_service/service/helper_files/utils.o" \
    "${object}" -o "${output}" \
    /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 \
    /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 \
    /lib/x86_64-linux-gnu/libgpr.so.10.0.0 \
    /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 \
    -pthread -lgomp -lssl -lcrypto -lz \
    /lib/x86_64-linux-gnu/libcares.so.2 -ldl >> "${log}" 2>&1
}

for coverage in 25 50 75 100; do
  for mode in o0 o064; do
    label="cov${coverage}_${mode}"
    plan="${PLANS}/${label}/prefetchit.plan.json"
    object="${OUT}/mid_tier_server.${label}.o"
    binary="${OUT}/mid_tier_server.${label}"
    log="${OUT}/build_${label}.log"
    [[ -f "${plan}" ]] || { echo "missing plan: ${plan}" >&2; exit 2; }
    (
      cd "${SERVICE}"
      PREFETCHIT_PLAN="${plan}" "${CXX}" \
        -std=c++17 -O3 -g -fno-omit-frame-pointer -pthread \
        -I"${DEB_ROOT}/usr/include" \
        -I/usr/lib/gcc/x86_64-linux-gnu/11/include \
        -I../ -I../../ -I. -fopenmp=libgomp -I/usr/local/include \
        -pthread -O3 -I../../ -Wall -I../../ -fopenmp=libgomp \
        -fpass-plugin="${PASS}" -c -o "${object}" mid_tier_server.cc
    ) > "${log}" 2>&1
    link_binary "${object}" "${binary}" "${log}"
  done
done

printf 'label,planned_injections,planned_prefetches,injected,assembly_prefetches,binary\n' > "${OUT}/build_summary.csv"
for coverage in 25 50 75 100; do
  for mode in o0 o064; do
    label="cov${coverage}_${mode}"
    plan="${PLANS}/${label}/prefetchit.plan.json"
    log="${OUT}/build_${label}.log"
    binary="${OUT}/mid_tier_server.${label}"
    planned_injections="$(jq -r '.stats.selected_injections' "${plan}")"
    planned_prefetches="$(jq -r '.stats.planned_prefetches' "${plan}")"
    injected="$(sed -n 's/.*prefetchit-inject: injected=\([0-9][0-9]*\).*/\1/p' "${log}" | tail -1)"
    assembly_prefetches="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch')"
    printf '%s,%s,%s,%s,%s,%s\n' "${label}" "${planned_injections}" \
      "${planned_prefetches}" "${injected:-0}" "${assembly_prefetches}" "${binary}" \
      >> "${OUT}/build_summary.csv"
  done
done

cat "${OUT}/build_summary.csv"
