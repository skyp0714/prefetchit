#!/usr/bin/env bash
set -euo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cc -O2 -Wall -Wextra -Werror -fPIC -shared \
  "${ROOT}/llvm_prefetchit/tools/pthread_core_pin.c" \
  -o "${ROOT}/llvm_prefetchit/tools/pthread_core_pin.so" \
  -ldl -pthread

cc -O2 -Wall -Wextra -Werror -fPIC -shared \
  "${ROOT}/llvm_prefetchit/tools/grpc_core_cap.c" \
  -o "${ROOT}/llvm_prefetchit/tools/grpc_core_cap.so" \
  -ldl
