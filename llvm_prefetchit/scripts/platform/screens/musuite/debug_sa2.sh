#!/usr/bin/env bash
S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run
(cd $S/SetAlgebra/intersection_service/service && exec taskset -c 30-34 ./intersection_server 127.0.0.1:50054 $D/SetAlgebra/posting_lists_1G.txt 4 0 1 > /tmp/dbg_leaf.log 2>&1) & LEAF=$!; sleep 30
(cd $S/SetAlgebra/union_service/service && exec taskset -c 30-34 ./mid_tier_server 1 $R/sa_leaf_ips.txt 127.0.0.1:50053 4 > /tmp/dbg_mid.log 2>&1) & MID=$!; sleep 3
cd $S/SetAlgebra/load_generator && timeout 120 gdb -batch -ex run -ex bt --args ./load_generator_open_loop $D/SetAlgebra/query_set.txt /tmp/res.txt 30 3000 127.0.0.1:50053 2>&1 | grep -vE "^\[Thread|^\[New|^\[Inferior|Using host|Downloading" | head -25 | cut -c1-200
pkill -P $LEAF; pkill -P $MID; kill $LEAF $MID 2>/dev/null; killall -q intersection_server mid_tier_server 2>/dev/null; echo DEBUG2_DONE
