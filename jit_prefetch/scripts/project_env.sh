#!/usr/bin/env bash

JIT_PREFETCH_ROOT="${JIT_PREFETCH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PREFETCHIT_ROOT="${PREFETCHIT_ROOT:-$(cd "${JIT_PREFETCH_ROOT}/.." && pwd)}"
JDK="${JDK:-${JIT_PREFETCH_ROOT}/openjdk/build/linux-x86_64-server-release/images/jdk}"
DACAPO="${DACAPO:-${PREFETCHIT_ROOT}/benchmarks/tools/dacapo/dacapo-23.11-MR2-chopin.jar}"
REN="${REN:-${PREFETCHIT_ROOT}/benchmarks/tools/renaissance/renaissance-gpl.jar}"
export JIT_PREFETCH_ROOT PREFETCHIT_ROOT JDK DACAPO REN
