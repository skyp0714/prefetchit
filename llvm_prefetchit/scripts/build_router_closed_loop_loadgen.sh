#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
REPO="${ROOT}/llvm_prefetchit"
SRC="${ROOT}/benchmarks/datacenter_sources/MicroSuite/src/Router"
DEB_ROOT="${REPO}/work/datacenter_goal_20260708/deb_deps/root"
CXX="${CXX:-clang++-19}"
OUT="${ROUTER_CLOSED_LOOP_BINARY:-${SRC}/load_generator/load_generator_closed_loop}"

"${CXX}" -O3 -g -std=c++17 -pthread -fopenmp=libgomp \
  -I"${DEB_ROOT}/usr/include" -I/usr/local/include -I"${SRC}" \
  "${SRC}/load_generator/load_generator_closed_loop.cc" \
  "${SRC}/protoc_files/router.pb.o" \
  "${SRC}/protoc_files/router.grpc.pb.o" \
  "${SRC}/load_generator/helper_files/loadgen_router_client_helper.o" \
  "${SRC}/mid_tier_service/service/helper_files/timing.o" \
  "${SRC}/mid_tier_service/service/helper_files/utils.o" \
  /lib/x86_64-linux-gnu/libgrpc++.so.1.30.2 \
  /lib/x86_64-linux-gnu/libgrpc.so.10.0.0 \
  /lib/x86_64-linux-gnu/libgpr.so.10.0.0 \
  /lib/x86_64-linux-gnu/libprotobuf.so.23.0.4 \
  -lssl -lcrypto -lz /lib/x86_64-linux-gnu/libcares.so.2 -ldl \
  -o "${OUT}"
