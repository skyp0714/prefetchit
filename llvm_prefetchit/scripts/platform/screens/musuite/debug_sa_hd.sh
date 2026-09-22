#!/usr/bin/env bash
# Debug SetAlgebra loadgen segfault and HDSearch mid-tier crash on spare cores (30-34 servers, 40-42 client); prints backtraces.
S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; FL=/home/hnpark2/prefetchit/benchmarks/MicroSuite/flann_local
echo "=== SetAlgebra"; head -200 $D/SetAlgebra/query_set.txt > /tmp/sa_q.txt
(cd $S/SetAlgebra/intersection_service/service && exec taskset -c 30-34 ./intersection_server 127.0.0.1:50054 $D/SetAlgebra/posting_lists_1G.txt 4 0 1 > /tmp/dbg_leaf.log 2>&1) & LEAF=$!; sleep 30
(cd $S/SetAlgebra/union_service/service && exec taskset -c 30-34 ./mid_tier_server 1 $R/sa_leaf_ips.txt 127.0.0.1:50053 4 > /tmp/dbg_mid.log 2>&1) & MID=$!; sleep 3
tail -2 /tmp/dbg_leaf.log /tmp/dbg_mid.log | cut -c1-120
cd $S/SetAlgebra/load_generator && timeout 60 gdb -batch -ex run -ex bt --args ./load_generator_open_loop /tmp/sa_q.txt /tmp/res.txt 10 200 127.0.0.1:50053 2>&1 | grep -E "^#|SIGSEGV|Program received|exited" | head -12 | cut -c1-160
pkill -P $LEAF; pkill -P $MID; kill $LEAF $MID 2>/dev/null; killall -q intersection_server mid_tier_server 2>/dev/null; sleep 2
echo "=== HDSearch"; (cd $S/HDSearch/bucket_service/service && exec taskset -c 30-34 ./bucket_server $D/HDSearch/image_feature_vectors.dat 127.0.0.1:50056 2 4 0 1 > /tmp/dbg_hleaf.log 2>&1) & LEAF=$!; sleep 45; tail -2 /tmp/dbg_hleaf.log | cut -c1-120
cd $S/HDSearch/mid_tier_service/service && LD_LIBRARY_PATH=$FL/lib timeout 300 gdb -batch -ex run -ex bt --args ./mid_tier_server 1 20 2 1 $R/hd_leaf_ips.txt $D/HDSearch/image_feature_vectors.dat 2 127.0.0.1:50055 1 4 4 0 2>&1 | grep -E "^#|SIGSEGV|Program received|exited|Format|argument" | head -12 | cut -c1-160
pkill -P $LEAF; kill $LEAF 2>/dev/null; killall -q bucket_server mid_tier_server 2>/dev/null; echo DEBUG_DONE
