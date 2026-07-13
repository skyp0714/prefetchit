#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
CXX="${CXX:-clang++-19}"

"${CXX}" -O3 -std=c++17 -pthread \
  "${ROOT}/tools/evict_cpu_caches.cc" \
  -o "${ROOT}/tools/evict_cpu_caches"
