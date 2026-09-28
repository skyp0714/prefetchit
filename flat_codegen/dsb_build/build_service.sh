#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh" 2>/dev/null || true
# Build PostStorageService inside dsb-deps-jammy with clang-19.
# Usage: build_service.sh <outdir> [extra CXXFLAGS...]
set -e
OUT=$1; shift
EXTRA="$*"
LDX=()
# stack-independent: MAKE_TARGET names the service, BIN_GLOB the produced executables. mediaMicroservices differs from socialNetwork in
# two places: jaegertracing is an IMPORTED SHARED target in src/CMakeLists.txt (not commented out) and the root CMakeLists has no -O3.
if [[ "${FATSTATIC:-0}" == "1" ]]; then
  # link thrift/mongoc/bson/jaeger/opentracing/yaml-cpp and libstdc++ statically into the service (one link unit: pc-relative prefetch targets)
  T=${MAKE_TARGET:-UserTimelineService}; CL=/src/src/$T/CMakeLists.txt; SL=/src/src/CMakeLists.txt
  cp -p $CL /tmp/${T}_cmake.bak; cp -p $SL /tmp/${T}_src_cmake.bak
  trap "cat /tmp/${T}_cmake.bak > $CL; cat /tmp/${T}_src_cmake.bak > $SL" EXIT
  STATICJ='/usr/local/lib/libjaegertracing.a /usr/local/lib/libopentracing.a /usr/local/lib/libyaml-cpp.a /usr/local/lib/libthrift.a'
  # the IMPORTED jaegertracing target in media's src/CMakeLists.txt is left alone (the per-service sed below removes its use)
  sed -i -e 's#find_package(libmongoc-1.0 1.13 REQUIRED)#find_package(libmongoc-static-1.0 1.13 REQUIRED)\nset(MONGOC_INCLUDE_DIRS ${MONGOC_STATIC_INCLUDE_DIRS})#' $SL
  sed -i -e '1i find_package(libmongoc-static-1.0 1.13 REQUIRED)' -e 's#\${MONGOC_LIBRARIES}#${MONGOC_STATIC_LIBRARIES}#' -e 's#\${THRIFT_LIB}#/usr/local/lib/libthrift.a#' \
    -e "s#^\(\s*\)jaegertracing\s*\$#\1${STATICJ}#" \
    -e "s#/usr/local/lib/libjaegertracing\.so#${STATICJ}#" $CL
  LDX=("-DCMAKE_EXE_LINKER_FLAGS=-static-libstdc++ -static-libgcc ${PREFETCHIT_RUNTIME_OBJECT:-}")
fi
cd /src
rm -rf build && mkdir build && cd build
CC=clang-19 CXX="clang++-19 $EXTRA" cmake -DPREFETCHIT_LOCAL_PREFIX=/usr/local -DCMAKE_CXX_STANDARD_LIBRARIES=/usr/local/lib/libyaml-cpp.a -DCMAKE_CXX_FLAGS="-g $EXTRA" "${LDX[@]}" .. > cmake.log 2>&1
make -j32 ${MAKE_TARGET:-} > make.log 2>&1
find src -maxdepth 2 -type f -executable -name "${BIN_GLOB:-*Service}" -exec cp {} "$OUT/" \;
ls "$OUT"
