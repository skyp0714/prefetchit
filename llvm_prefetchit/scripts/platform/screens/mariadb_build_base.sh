#!/usr/bin/env bash
# MariaDB 10.11 baseline from the official source tarball: clang-19 -O3 -g (no layout PGO), installed under install_base
set -euo pipefail
cd /home/hnpark2/prefetchit/benchmarks/mariadb
V=10.11.14
[[ -f mariadb-$V.tar.gz ]] || curl -sSL -o mariadb-$V.tar.gz https://archive.mariadb.org/mariadb-$V/source/mariadb-$V.tar.gz
[[ -d mariadb-$V ]] || tar xzf mariadb-$V.tar.gz
rm -rf build_base; mkdir build_base; cd build_base
cmake ../mariadb-$V -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 \
  -DCMAKE_C_FLAGS_RELWITHDEBINFO="-O3 -g -DNDEBUG -fno-omit-frame-pointer" -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-O3 -g -DNDEBUG -fno-omit-frame-pointer" \
  -DCMAKE_INSTALL_PREFIX=/home/hnpark2/prefetchit/benchmarks/mariadb/install_base -DWITH_SSL=system -DWITH_ZLIB=system \
  -DPLUGIN_ROCKSDB=NO -DPLUGIN_MROONGA=NO -DPLUGIN_SPIDER=NO -DPLUGIN_CONNECT=NO -DPLUGIN_TOKUDB=NO -DPLUGIN_OQGRAPH=NO -DPLUGIN_SPHINX=NO \
  -DWITH_WSREP=OFF -DWITH_UNIT_TESTS=OFF -DWITH_EMBEDDED_SERVER=OFF > cmake.log 2>&1
make -j32 > make.log 2>&1
make install > install.log 2>&1
echo "MARIADB BUILD DONE $(ls /home/hnpark2/prefetchit/benchmarks/mariadb/install_base/bin/mariadbd)"
