#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CXX="${CXX:-clang++-19}"

"${CXX}" -O3 -std=c++17 -pthread \
  "${ROOT}/tools/evict_cpu_caches.cc" \
  -o "${ROOT}/tools/evict_cpu_caches"
