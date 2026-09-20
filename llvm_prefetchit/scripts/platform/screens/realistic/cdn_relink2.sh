#!/usr/bin/env bash
# cdn_bench: libglog.so.1 was built with gflags linked in (exports gflags symbols) while the binaries also link libgflags.a →
# gflags aborts ("linked both statically and dynamically"). Rebuild glog static, drop libglog.so*, relink foss_revproxy.
P=/home/hnpark2/prefetchit/benchmarks/dcperf_v2/packages/cdn_bench; D=$P/_build/deps
echo "dynamic deps of content_server from deps/lib:"; ldd $P/binaries/content_server | grep "deps/lib" | awk '{print $1}' | tr '\n' ' '; echo
cd $D/glog && rm -rf build_static && mkdir build_static && cd build_static && cmake .. -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DWITH_GTEST=OFF -DWITH_GFLAGS=ON -DCMAKE_PREFIX_PATH=$D -DCMAKE_INSTALL_PREFIX=$D > /tmp/glog_cmake.log 2>&1 && taskset -c 12-35 make -j8 > /tmp/glog_make.log 2>&1 && make install > /tmp/glog_install.log 2>&1; echo "glog static rc=$?"; ls $D/lib | grep -E "^libglog" | tr '\n' ' '; echo
mkdir -p $D/lib_shared_glog && mv $D/lib/libglog.so* $D/lib_shared_glog/ 2>/dev/null
cd $P/_build/foss_revproxy_build && rm -f CMakeCache.txt && rm -rf CMakeFiles && cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_PREFIX_PATH=$D -DCMAKE_INSTALL_PREFIX=$P/binaries -DCMAKE_POSITION_INDEPENDENT_CODE=ON $P/src > /tmp/cdn_cmake.log 2>&1 && taskset -c 12-35 make -j12 > /tmp/cdn_make.log 2>&1; echo "relink rc=$?"; grep -E "error" /tmp/cdn_make.log | head -2 | cut -c1-160
cp -f traffic_client proxy_server content_server $P/binaries/ && ldd $P/binaries/content_server | grep -E "glog|gflags" | cut -c1-100
(cd $P && LD_LIBRARY_PATH=binaries/lib timeout 6 binaries/content_server --port=18082 > /tmp/cs_test3.log 2>&1; echo "content_server test rc=$? (124 = ran until timeout = OK)"); tail -2 /tmp/cs_test3.log | cut -c1-160
echo "[$(date +%T)] CDN2_REBUILT"
