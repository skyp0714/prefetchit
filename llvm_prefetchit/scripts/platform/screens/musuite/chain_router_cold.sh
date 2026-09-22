#!/usr/bin/env bash
# After round 17 (DSB cold arm): Router cold-path A/B (base, cold, cold_nop, cold_seq, cold_seq_nop), isolated then shared with noise.
R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; cd $R
until grep -q CHAIN_COLD_DONE /home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink/logs/chain_cold.log 2>/dev/null; do sleep 15; done
ARMS="base cold cold_nop cold_seq cold_seq_nop"
echo "[$(date +%T)] router cold ab isolated"; ./router_ab.sh router_cold_ab.csv isolated 3 $ARMS > router_cold_iso.log 2>&1; grep -E " r[0-9]:" router_cold_iso.log | tail -10
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
echo "[$(date +%T)] router cold ab shared"; ./router_ab.sh router_cold_ab.csv shared 3 $ARMS > router_cold_shared.log 2>&1; grep -E " r[0-9]:" router_cold_shared.log | tail -10
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo "[$(date +%T)] ROUTER_COLD_DONE"
