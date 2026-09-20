#!/usr/bin/env bash
# cdn_bench binaries abort at startup: gflags is linked statically into the binaries and dynamically through libglog.so.1 → gflags
# "linked both statically and dynamically". Hide the static gflags archives and relink foss_revproxy against libgflags.so.
P=/home/hnpark2/prefetchit/benchmarks/dcperf_v2/packages/cdn_bench; cd $P/_build/deps/lib && mkdir -p ../lib_static_gflags && mv libgflags*.a ../lib_static_gflags/ 2>/dev/null
cd $P/_build/foss_revproxy_build && rm -f CMakeCache.txt && cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_PREFIX_PATH=$P/_build/deps -DCMAKE_INSTALL_PREFIX=$P/binaries -DCMAKE_POSITION_INDEPENDENT_CODE=ON $P/src > /tmp/cdn_cmake.log 2>&1 && taskset -c 12-35 make -j12 > /tmp/cdn_make.log 2>&1; echo "relink rc=$?"
cp -f traffic_client proxy_server content_server $P/binaries/ && ldd $P/binaries/content_server | grep -E "gflags|glog" | cut -c1-100
(cd $P && LD_LIBRARY_PATH=binaries/lib timeout 6 binaries/content_server --port=18082 > /tmp/cs_test2.log 2>&1; echo "content_server test rc=$?"); tail -2 /tmp/cs_test2.log | cut -c1-160
echo "[$(date +%T)] CDN_REBUILT"
