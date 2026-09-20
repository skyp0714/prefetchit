#!/usr/bin/env bash
# cdn_bench, take 4 (no relink): the clash is gflags-in-libglog.so.1 vs libgflags.a in the binaries. Rebuild glog *shared without
# gflags* and install it over deps/lib/libglog.so.1 — same soname/path, so the existing binaries just pick it up.
P=/home/hnpark2/prefetchit/benchmarks/dcperf_v2/packages/cdn_bench; D=$P/_build/deps
mv $D/lib_shared_glog/libglog.so* $D/lib/ 2>/dev/null; mv $D/lib/cmake/glog/*.shared.bak $D/lib/cmake/glog/ 2>/dev/null; for f in $D/lib/cmake/glog/*.shared.bak; do [[ -f $f ]] && mv "$f" "${f%.shared.bak}"; done
cd $D/glog && rm -rf build_nogflags && mkdir build_nogflags && cd build_nogflags && cmake .. -DBUILD_SHARED_LIBS=ON -DWITH_GTEST=OFF -DWITH_GFLAGS=OFF -DWITH_UNWIND=OFF -DCMAKE_PREFIX_PATH=$D -DCMAKE_INSTALL_PREFIX=$D > /tmp/glog4_cmake.log 2>&1 && taskset -c 12-35 make -j8 > /tmp/glog4_make.log 2>&1 && make install > /tmp/glog4_install.log 2>&1; echo "glog shared/no-gflags rc=$?"
nm -D $D/lib/libglog.so.1 | grep -c "gflags" | sed 's/^/gflags symbols left in libglog.so.1: /'
(cd $P && LD_LIBRARY_PATH=binaries/lib timeout 6 binaries/content_server --port=18082 > /tmp/cs_test5.log 2>&1; echo "content_server test rc=$? (124 = ran until timeout = OK)"); tail -2 /tmp/cs_test5.log | cut -c1-160
echo "[$(date +%T)] CDN4_REBUILT"
