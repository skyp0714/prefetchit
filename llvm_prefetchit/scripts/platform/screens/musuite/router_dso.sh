#!/usr/bin/env bash
# Router L2I-miss breakdown by DSO (leaf + mid-tier), isolated cores 36-39, 3,000 qps open loop. Usage: router_dso.sh ARM
set -u; ARM=${1:-base}; S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; V=/home/hnpark2/prefetchit/benchmarks/MicroSuite/variants; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; O=$R/dso_$ARM; mkdir -p $O; cores=36-39
taskset -c $cores memcached -p 11311 -t 2 -m 512 -u $USER > /tmp/mc.log 2>&1 & MC=$!; sleep 1
(cd $S/Router/lookup_service/service && exec taskset -c $cores $V/$ARM/lookup_server 127.0.0.1:50052 11311 4 0 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 2
(cd $S/Router/mid_tier_service/service && exec taskset -c $cores $V/$ARM/mid_tier_server 1 $R/router_leaf_ips.txt 127.0.0.1:50051 4 4 4 1 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
(cd $S/Router/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/Router/twitter_requests_query_set.dat /tmp/res.txt 45 3000 127.0.0.1:50051 90 10 > /tmp/load_dso.log 2>&1) & LP=$!; sleep 15
perf record -e cpu/event=0x24,umask=0x24/ -c 2000 -p $LEAF -o $O/leaf.data -- sleep 10 > /dev/null 2>&1; perf record -e cpu/event=0x24,umask=0x24/ -c 2000 -p $MID -o $O/mid.data -- sleep 10 > /dev/null 2>&1
wait $LP; kill $LEAF $MID $MC 2>/dev/null; sleep 1; killall -q lookup_server mid_tier_server 2>/dev/null
for t in leaf mid; do echo "== $t by DSO"; perf report -i $O/$t.data --sort dso --stdio 2>/dev/null | grep -E "^ +[0-9]" | head -12; echo "== $t top symbols"; perf report -i $O/$t.data --sort dso,sym --stdio 2>/dev/null | grep -E "^ +[0-9]" | head -15 | cut -c1-140; done
