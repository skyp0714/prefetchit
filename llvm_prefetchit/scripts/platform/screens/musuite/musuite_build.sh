#!/usr/bin/env bash
# Build μSuite services against distro gRPC 1.51 / protobuf 3.21 / OpenBLAS (instead of MKL) / FLANN 1.9 / libmemcached. Logs per target.
set -u
ROOT=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; L=/tmp/musuite_logs; mkdir -p $L
# MKL -> OpenBLAS: replace the MKL static link group and include dirs
find $ROOT -name Makefile | while read m; do
  sed -i -E 's#-Wl,--start-group[^ ]*libmkl_intel_ilp64\.a [^ ]*libmkl_sequential\.a [^ ]*libmkl_core\.a -Wl,--end-group#-lopenblas#g; s#-Wl,--start-group /opt/intel/mkl/lib/intel64/libmkl_intel_ilp64.a /opt/intel/mkl/lib/intel64/libmkl_sequential.a /opt/intel/mkl/lib/intel64/libmkl_core.a -Wl,--end-group#-lopenblas#g; s#-DMKL_ILP64 -m64 -I/opt/intel/mkl/include#-I/usr/include/x86_64-linux-gnu/openblas-pthread#g; s#-I/opt/intel/mkl/include##g' "$m"
done
grep -rl "mkl_cblas.h\|mkl.h" $ROOT --include=*.cpp --include=*.cc --include=*.h | xargs -r sed -i 's#<mkl_cblas.h>#<cblas.h>#; s#"mkl_cblas.h"#<cblas.h>#; s#<mkl.h>#<cblas.h>#'
for s in HDSearch Router SetAlgebra Recommend; do
  echo "=== $s protoc"; (cd $ROOT/$s/protoc_files && make > $L/${s}_protoc.log 2>&1; ls *.pb.cc *.grpc.pb.cc 2>/dev/null | tr '\n' ' '; echo)
done
for t in HDSearch/bucket_service/service HDSearch/mid_tier_service/service HDSearch/load_generator Router/lookup_service/service Router/mid_tier_service/service Router/load_generator SetAlgebra/intersection_service/service SetAlgebra/union_service/service SetAlgebra/load_generator Recommend/cf_service/service Recommend/recommender_service/service Recommend/load_generator; do
  n=$(echo $t | tr '/' '_'); (cd $ROOT/$t && make -j16 > $L/$n.log 2>&1); rc=$?; echo "$t: rc=$rc $(ls $ROOT/$t | grep -vE '\.(cc|cpp|h|o|d)$|Makefile|helper' | tr '\n' ' ' | cut -c1-80) $(grep -m1 -E 'error' $L/$n.log | cut -c1-120)"
done
echo BUILD_SCRIPT_DONE
