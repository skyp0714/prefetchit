#!/usr/bin/env bash
# cdn_bench relink, take 3: the glog CMake export files still pointed at libglog.so; drop the shared-target exports so the static
# libglog.a (built in cdn_relink2) is used, re-configure foss_revproxy, relink, install, smoke-test content_server.
P=/home/hnpark2/prefetchit/benchmarks/dcperf_v2/packages/cdn_bench; D=$P/_build/deps
ls $D/lib/cmake/glog/ 2>/dev/null | tr '\n' ' '; echo
for f in $D/lib/cmake/glog/*.cmake; do grep -q "libglog\.so" "$f" && { echo "drop $f"; mv "$f" "$f.shared.bak"; }; done
grep -l "libglog\.a" $D/lib/cmake/glog/*.cmake | head -2
cd $P/_build/foss_revproxy_build && rm -f CMakeCache.txt && rm -rf CMakeFiles && cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_PREFIX_PATH=$D -DCMAKE_INSTALL_PREFIX=$P/binaries -DCMAKE_POSITION_INDEPENDENT_CODE=ON $P/src > /tmp/cdn_cmake3.log 2>&1 && taskset -c 12-35 make -j12 > /tmp/cdn_make3.log 2>&1; echo "relink rc=$?"; grep -aE "undefined reference|: error|No rule" /tmp/cdn_make3.log | head -3 | cut -c1-200
cp -f traffic_client proxy_server content_server $P/binaries/ 2>/dev/null && ldd $P/binaries/content_server | grep -E "glog|gflags" | cut -c1-100
(cd $P && LD_LIBRARY_PATH=binaries/lib timeout 6 binaries/content_server --port=18082 > /tmp/cs_test4.log 2>&1; echo "content_server test rc=$? (124 = ran until timeout = OK)"); tail -2 /tmp/cs_test4.log | cut -c1-160
echo "[$(date +%T)] CDN3_REBUILT"
