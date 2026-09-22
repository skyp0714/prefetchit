#!/usr/bin/env bash
# PostgreSQL baseline build (clang-19 -O3 -g, no layout PGO) for the 2026-09 re-screen
set -euo pipefail
SRC=/home/hnpark2/prefetchit/benchmarks/datacenter_sources/postgres
B=/home/hnpark2/prefetchit/benchmarks/pg/build_base; I=/home/hnpark2/prefetchit/benchmarks/pg/install_base
rm -rf "$B"; mkdir -p "$B"; cd "$B"
CC=clang-19 CFLAGS="-O3 -g -fno-omit-frame-pointer" "$SRC/configure" --prefix="$I" --without-icu --without-readline --without-zlib > configure.log 2>&1
make -j32 > make.log 2>&1 && make install > install.log 2>&1 && make -C contrib/pg_prewarm install >> install.log 2>&1 || true
echo "PG BUILD DONE $(ls $I/bin/postgres)"
