#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/SetAlgebra"
OUT="${OUT:-${ROOT}/llvm_prefetchit/work/final_campaign_20260711/microsuite_set_stable_v2}"
DEB_ROOT="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
CXX="${CXX:-clang++-19}"
SANITIZE="${SANITIZE:-}"

mkdir -p "${OUT}"

COMMON_FLAGS=(
  -std=c++17 -O3 -g -fno-omit-frame-pointer -pthread
  -I"${DEB_ROOT}/usr/include"
  -I/usr/lib/gcc/x86_64-linux-gnu/11/include
  -I"${SRC}" -I/usr/local/include
  -fopenmp=libgomp -Wall
)
LINK_FLAGS=()
if [[ "${SANITIZE}" == "address" ]]; then
  COMMON_FLAGS+=(-fsanitize=address)
  LINK_FLAGS+=(-fsanitize=address)
fi

"${CXX}" "${COMMON_FLAGS[@]}" -c "${SRC}/intersection_service/service/helper_files/client_helper.cc" -o "${OUT}/client_helper.o"

"${CXX}" "${COMMON_FLAGS[@]}" -c "${SRC}/union_service/service/helper_files/union_server_helper.cc" -o "${OUT}/union_server_helper.o"

"${CXX}" "${COMMON_FLAGS[@]}" -c "${SRC}/union_service/service/mid_tier_server.cc" -o "${OUT}/mid_tier_server.baseline.o"

"${CXX}" "${LINK_FLAGS[@]}" "${SRC}/protoc_files/intersection.pb.o" "${SRC}/protoc_files/intersection.grpc.pb.o" "${SRC}/protoc_files/union.pb.o" "${SRC}/protoc_files/union.grpc.pb.o" "${OUT}/client_helper.o" "${OUT}/union_server_helper.o" "${SRC}/union_service/service/helper_files/timing.o" "${SRC}/union_service/service/helper_files/utils.o" "${OUT}/mid_tier_server.baseline.o" -o "${OUT}/mid_tier_server.baseline" /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 /lib/x86_64-linux-gnu/libgpr.so.10.0.0 /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 -pthread -lgomp -lssl -lcrypto -lz /lib/x86_64-linux-gnu/libcares.so.2 -ldl

llvm-objdump-19 -d "${OUT}/mid_tier_server.baseline" |
  rg -c '\bprefetch' > "${OUT}/baseline_prefetch_count.txt"
sha256sum "${OUT}/mid_tier_server.baseline" > "${OUT}/baseline.sha256"

printf 'baseline=%s\n' "${OUT}/mid_tier_server.baseline"
printf 'prefetch_instructions=%s\n' "$(cat "${OUT}/baseline_prefetch_count.txt")"
