#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/HDSearch"
DEPS="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
PATCH="${ROOT}/llvm_prefetchit/patches/microsuite-hd-deterministic-query-reset.patch"
FIXED_WORK_PATCH="${ROOT}/llvm_prefetchit/patches/microsuite-hd-fixed-work.patch"
OUT="${1:-${ROOT}/llvm_prefetchit/work/pgo_lbr_path_20260712/harness/hdsearch}"
COPY="${OUT}/load_generator_closed_loop.cc"
OBJECT="${OUT}/load_generator_closed_loop.o"
BINARY="${OUT}/load_generator_closed_loop"

mkdir -p "${OUT}"
cp "${SRC}/load_generator/load_generator_closed_loop.cc" "${COPY}"
if ! rg -q 'PREFETCHIT_QUERY_SEED' "${COPY}"; then
  patch "${COPY}" < "${PATCH}"
fi
if ! rg -q 'PREFETCHIT_FIXED_REQUESTS' "${COPY}"; then
  patch "${COPY}" < "${FIXED_WORK_PATCH}"
fi

g++ -std=c++11 -O3 -mavx2 -mavx -fopenmp -DMKL_ILP64 -m64 \
  -I"${SRC}" -I"${SRC}/load_generator" \
  -I"${DEPS}/usr/include" -I/usr/local/include \
  -pthread -g -Wall -c "${COPY}" -o "${OBJECT}"

g++ \
  "${SRC}/protoc_files/mid_tier.pb.o" \
  "${SRC}/protoc_files/mid_tier.grpc.pb.o" \
  "${SRC}/bucket_service/src/multiple_points.o" \
  "${SRC}/bucket_service/src/point.o" \
  "${SRC}/bucket_service/src/utils.o" \
  "${SRC}/bucket_service/src/dist_calc.o" \
  "${SRC}/bucket_service/src/custom_priority_queue.o" \
  "${SRC}/load_generator/helper_files/mid_tier_client_helper.o" \
  "${SRC}/load_generator/helper_files/timing.o" \
  "${SRC}/load_generator/helper_files/utils.o" \
  "${OBJECT}" -O3 -o "${BINARY}" \
  /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 \
  /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 \
  /lib/x86_64-linux-gnu/libgpr.so.10.0.0 \
  /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 \
  -pthread -lgomp -lssl -lcrypto -lz \
  /lib/x86_64-linux-gnu/libcares.so.2 -ldl -lopenblas -llz4

sha256sum "${BINARY}" > "${OUT}/load_generator_closed_loop.sha256"
cat "${OUT}/load_generator_closed_loop.sha256"
