#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# Build PostStorageService inside dsb-deps-jammy with clang-19.
# Usage: build_service.sh <outdir> [extra CXXFLAGS...]
set -e
OUT=$1; shift
EXTRA="$*"
cd /src
rm -rf build && mkdir build && cd build
CC=clang-19 CXX=clang++-19 cmake -DPREFETCHIT_LOCAL_PREFIX=/usr/local -DCMAKE_CXX_STANDARD_LIBRARIES=/usr/local/lib/libyaml-cpp.a -DCMAKE_CXX_FLAGS="-g $EXTRA" .. > cmake.log 2>&1
make -j32 ${MAKE_TARGET:-} > make.log 2>&1
find src -maxdepth 2 -type f -executable -name "*Service" -exec cp {} "$OUT/" \;
ls "$OUT"
