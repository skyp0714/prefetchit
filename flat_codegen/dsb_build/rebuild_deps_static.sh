#!/bin/bash
PREFETCHIT_ROOT=${PREFETCHIT_ROOT:-/home/hnpark2/prefetchit}
# Rebuild DSB dependency libs (thrift/mongoc+bson/opentracing/yaml/jaeger)
# inside dsb-deps-jammy with clang-19 -O2 -g at STABLE source paths
# (/opt/src/<lib>), optionally with the PrefetchIT pass, then docker-commit
# the result as a new image.
# Usage: rebuild_deps_g.sh <new-image-tag> [plan.json]
# With a plan: compiles libs with -fpass-plugin + PREFETCHIT_PLAN.
set -e
TAG=$1; PLAN=$2; EXTRA_ENV=${EXTRA_PASS_ENV:-}
NAME=depsbuild_$$
PASSDIR=${PREFETCHIT_ROOT}/llvm_prefetchit/build
DSB=${PREFETCHIT_ROOT}/flat_codegen/dsb_build

PASSFLAG=""
PLANENV=""
if [[ -n "$PLAN" && "$PLAN" != "-" ]]; then
  PASSFLAG="-fpass-plugin=/pass/PrefetchITPass.so"
  PLANENV="PREFETCHIT_PLAN=/dsb/$(basename $PLAN)"
  cp -f "$PLAN" "$DSB/$(basename $PLAN)"
fi
# plan-free pass modes: EXTRA_PASS_ENV="PREFETCHIT_CALLEE_BURST_LINES=3 PREFETCHIT_SEQ_DISTANCE=4096 ..." enables the pass without a plan
if [[ -n "$EXTRA_ENV" ]]; then
  PASSFLAG="-fpass-plugin=/pass/PrefetchITPass.so"
  PLANENV="$PLANENV $EXTRA_ENV"
fi

docker rm -f $NAME 2>/dev/null || true
docker run --name $NAME \
  -v $PASSDIR:/pass -v $DSB:/dsb --entrypoint bash dsb-deps-jammy -c "
set -e
export ${PLANENV:-PREFETCHIT_DUMMY=1} PF='$PASSFLAG'
mkdir -p /opt/src && cd /opt/src
[ -d mongo-c-driver-1.15.0 ] || { wget -q https://github.com/mongodb/mongo-c-driver/releases/download/1.15.0/mongo-c-driver-1.15.0.tar.gz && tar -zxf mongo-c-driver-1.15.0.tar.gz; }
( export PREFETCHIT_COLD_DIRECT_SYMS= PREFETCHIT_COLD_DIRECT_IN_PIC=0; cd mongo-c-driver-1.15.0 && rm -rf b && CC=clang-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DENABLE_TESTS=0 -DENABLE_EXAMPLES=0 -DENABLE_SHM_COUNTERS=OFF -DENABLE_STATIC=ON -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined -DCMAKE_C_FLAGS=\"-Wno-error -O2 -g \$PF\" . > /dev/null && { make -C b -j32 > /dsb/dep_make_\$(basename \$PWD).log 2>&1 || { echo \"DEP_MAKE_FAILED in \$PWD\"; grep -B4 -m3 -E \"error:|Error 1\" /dsb/dep_make_\$(basename \$PWD).log; exit 1; }; } && make -C b install > /dev/null )
cd /opt/src
[ -d thrift-0.12.0 ] || { wget -qO thrift.tar.gz https://github.com/apache/thrift/archive/v0.12.0.tar.gz && tar -zxf thrift.tar.gz; }
cd thrift-0.12.0 && rm -rf b && CC=clang-19 CXX=clang++-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_COMPILER=OFF -DWITH_SHARED_LIB=OFF -DBUILD_TESTING=0 -DBUILD_TUTORIALS=0 -DBUILD_PYTHON=0 -DBUILD_JAVA=0 -DBUILD_JAVASCRIPT=0 -DBUILD_NODEJS=0 -DCMAKE_CXX_FLAGS=\"-Wno-error -Wno-enum-constexpr-conversion -Wno-deprecated-declarations -O2 -g \$PF\" . > /dev/null && { make -C b -j32 > /dsb/dep_make_\$(basename \$PWD).log 2>&1 || { echo \"DEP_MAKE_FAILED in \$PWD\"; grep -B4 -m3 -E \"error:|Error 1\" /dsb/dep_make_\$(basename \$PWD).log; exit 1; }; } && make -C b install > /dev/null
cd /opt/src
[ -d yaml-cpp-yaml-cpp-0.6.2 ] || { wget -qO yaml.tar.gz https://github.com/jbeder/yaml-cpp/archive/yaml-cpp-0.6.2.tar.gz && tar -zxf yaml.tar.gz; }
cd yaml-cpp-yaml-cpp-0.6.2 && rm -rf b && CC=clang-19 CXX=clang++-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CXX_FLAGS=\"-fPIC -Wno-enum-constexpr-conversion -O2 -g \$PF\" -DYAML_CPP_BUILD_TESTS=0 -DYAML_CPP_BUILD_TOOLS=0 -DYAML_CPP_BUILD_CONTRIB=0 . > /dev/null && { make -C b -j32 > /dsb/dep_make_\$(basename \$PWD).log 2>&1 || { echo \"DEP_MAKE_FAILED in \$PWD\"; grep -B4 -m3 -E \"error:|Error 1\" /dsb/dep_make_\$(basename \$PWD).log; exit 1; }; } && make -C b install > /dev/null
cd /opt/src
[ -d opentracing-cpp-1.5.1 ] || { wget -qO ot.tar.gz https://github.com/opentracing/opentracing-cpp/archive/v1.5.1.tar.gz && tar -zxf ot.tar.gz; }
cd opentracing-cpp-1.5.1 && rm -rf b && CC=clang-19 CXX=clang++-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CXX_FLAGS=\"-fPIC -Wno-enum-constexpr-conversion -O2 -g \$PF\" -DBUILD_TESTING=0 -DBUILD_SHARED_LIBS=OFF . > /dev/null && { make -C b -j32 > /dsb/dep_make_\$(basename \$PWD).log 2>&1 || { echo \"DEP_MAKE_FAILED in \$PWD\"; grep -B4 -m3 -E \"error:|Error 1\" /dsb/dep_make_\$(basename \$PWD).log; exit 1; }; } && make -C b install > /dev/null
cd /opt/src
[ -d jaeger-client-cpp-0.4.2 ] || { wget -qO jaeger.tar.gz https://github.com/jaegertracing/jaeger-client-cpp/archive/v0.4.2.tar.gz && tar -zxf jaeger.tar.gz; }
cd jaeger-client-cpp-0.4.2 && rm -rf b && CC=clang-19 CXX=clang++-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CXX_FLAGS=\"-fPIC -Wno-error -Wno-enum-constexpr-conversion -O2 -g \$PF\" -DHUNTER_ENABLED=0 -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=0 -DJAEGERTRACING_WITH_YAML_CPP=1 -DJAEGERTRACING_BUILD_EXAMPLES=0 . > /dev/null && { make -C b -j32 > /dsb/dep_make_\$(basename \$PWD).log 2>&1 || { echo \"DEP_MAKE_FAILED in \$PWD\"; grep -B4 -m3 -E \"error:|Error 1\" /dsb/dep_make_\$(basename \$PWD).log; exit 1; }; } && make -C b install > /dev/null
cd /opt/src
[ -d hiredis ] || git clone -q https://github.com/redis/hiredis.git
cd hiredis && git checkout -q v1.0.0 && make clean > /dev/null 2>&1; PREFETCHIT_COLD_DIRECT_SYMS= PREFETCHIT_COLD_DIRECT_IN_PIC=0 make -j\$(nproc) USE_SSL=1 CC=clang-19 OPTIMIZATION=-O2 DEBUG_FLAGS=\"-g \$PF\" && make USE_SSL=1 install
cd /opt/src
[ -d redis-plus-plus ] || { git clone -q https://github.com/sewenew/redis-plus-plus.git && cd redis-plus-plus && git checkout -q 1.2.3 && sed -i '/Transaction transaction/i\\    ShardsPool* get_shards_pool(){\\n        return &_pool;\\n    }\\n' src/sw/redis++/redis_cluster.h; cd /opt/src; }
cd redis-plus-plus && export PREFETCHIT_COLD_DIRECT_SYMS= PREFETCHIT_COLD_DIRECT_IN_PIC=0 && rm -rf b && CC=clang-19 CXX=clang++-19 cmake -B b -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CXX_FLAGS=\"-fPIC -Wno-enum-constexpr-conversion -O2 -g \$PF\" -DREDIS_PLUS_PLUS_USE_TLS=ON -DREDIS_PLUS_PLUS_BUILD_TEST=OFF . && make -C b -j\$(nproc) && make -C b install
ldconfig
echo LIBS_DONE
"
docker commit $NAME "$TAG"
docker rm -f $NAME
echo "IMAGE $TAG READY"
