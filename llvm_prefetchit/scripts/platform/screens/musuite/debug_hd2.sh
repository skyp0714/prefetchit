#!/usr/bin/env bash
S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; FL=/home/hnpark2/prefetchit/benchmarks/MicroSuite/flann_local
until grep -q DEBUG2_DONE $R/debug_sa2.log 2>/dev/null; do sleep 10; done
(cd $S/HDSearch/bucket_service/service && exec taskset -c 30-34 ./bucket_server $D/HDSearch/image_feature_vectors.dat 127.0.0.1:50056 2 4 0 1 > /tmp/dbg_hleaf.log 2>&1) & LEAF=$!; sleep 60; tail -3 /tmp/dbg_hleaf.log | cut -c1-120
cd $S/HDSearch/mid_tier_service/service && LD_LIBRARY_PATH=$FL/lib timeout 400 gdb -batch -ex run -ex bt --args ./mid_tier_server 1 20 2 1 $R/hd_leaf_ips.txt $D/HDSearch/image_feature_vectors.dat 2 127.0.0.1:50055 1 4 4 0 2>&1 | grep -vE "^\[Thread|^\[New|^\[Inferior|Using host|Downloading" | head -25 | cut -c1-200 &
GP=$!; sleep 150; (cd $S/HDSearch/load_generator && timeout 30 ./load_generator_open_loop $D/HDSearch/image_feature_vectors.dat /tmp/res.txt 1 10 100 127.0.0.1:50055 /tmp/t /tmp/q /tmp/u 2>&1 | tail -3 | cut -c1-160); wait $GP
pkill -P $LEAF; kill $LEAF 2>/dev/null; killall -q bucket_server mid_tier_server 2>/dev/null; echo DEBUG_HD2_DONE
