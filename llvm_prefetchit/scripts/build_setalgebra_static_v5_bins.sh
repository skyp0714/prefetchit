#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/SetAlgebra"
SERVICE="${SRC}/union_service/service"
PLAN_DIR="${PLAN_DIR:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/static_structural_set/plans}"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_static_v5_bins}"
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

labels=(boundary_o0 top1_o0 top2_o0 top2_o064 top2_s2_o0 top2_d8_o0 top2_d16_o0 top2_d32_o0 top2_d64_o0 top3_o0 top4_o0 merged_o0 merged_o064)
plans=(
  "${PLAN_DIR}/bodyonly_b128_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop1_b64_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d4_o064_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b256_s2_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d8_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d16_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d32_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop2_b128_d64_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop3_b192_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/bodytop4_b256_d4_o0_general_v5.plan.json"
  "${PLAN_DIR}/merged_boundary_top2_o0_general_v5.plan.json"
  "${PLAN_DIR}/merged_boundary_top2_o064_general_v5.plan.json"
)

if [[ "${STABLE_SUBSET:-0}" == 1 ]]; then
  labels=(top1_o0 top2_o0 top2_o064 top2_s2_o0 top2_d8_o0 top2_d16_o0 top2_d32_o0 top2_d64_o0 top3_o0 top4_o0)
  plans=(
    "${PLAN_DIR}/bodytop1_b64_d4_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d4_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d4_o064_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b256_s2_d4_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d8_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d16_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d32_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop2_b128_d64_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop3_b192_d4_o0_general_v5.plan.json"
    "${PLAN_DIR}/bodytop4_b256_d4_o0_general_v5.plan.json"
  )
fi

mkdir -p "${OUT}"
for i in "${!labels[@]}"; do
  label="${labels[$i]}"
  plan="${plans[$i]}"
  object="${OUT}/mid_tier_server.${label}.o"
  binary="${OUT}/mid_tier_server.${label}"
  log="${OUT}/build_${label}.log"
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
  "${CXX}" \
    "${SRC}/protoc_files/intersection.pb.o" \
    "${SRC}/protoc_files/intersection.grpc.pb.o" \
    "${SRC}/protoc_files/union.pb.o" \
    "${SRC}/protoc_files/union.grpc.pb.o" \
    "${CLIENT_HELPER_OBJECT}" \
    "${UNION_HELPER_OBJECT}" \
    "${SRC}/union_service/service/helper_files/timing.o" \
    "${SRC}/union_service/service/helper_files/utils.o" \
    "${object}" -o "${binary}" \
    /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 \
    /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 \
    /lib/x86_64-linux-gnu/libgpr.so.10.0.0 \
    /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 \
    -pthread -lgomp -lssl -lcrypto -lz \
    /lib/x86_64-linux-gnu/libcares.so.2 -ldl >> "${log}" 2>&1
done

printf 'label,planned_injections,planned_prefetches,injected,assembly_prefetches,binary\n' > "${OUT}/build_summary.csv"
for i in "${!labels[@]}"; do
  label="${labels[$i]}"
  plan="${plans[$i]}"
  log="${OUT}/build_${label}.log"
  binary="${OUT}/mid_tier_server.${label}"
  injected="$(sed -n 's/.*prefetchit-inject: injected=\([0-9][0-9]*\).*/\1/p' "${log}" | tail -1)"
  assembly_prefetches="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch')"
  printf '%s,%s,%s,%s,%s,%s\n' "${label}" \
    "$(jq -r '.stats.selected_injections' "${plan}")" \
    "$(jq -r '.stats.planned_prefetches' "${plan}")" \
    "${injected:-0}" "${assembly_prefetches}" "${binary}" \
    >> "${OUT}/build_summary.csv"
done

cat "${OUT}/build_summary.csv"
