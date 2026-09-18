#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; cd $R
until grep -q VERILATOR_IT_DONE $R/chain_verilator_it.log 2>/dev/null; do sleep 15; done
ARMS="base"; for a in seq_t1 seq_t1_nop seq_it1 seq_it1_nop seq_it0 seq_it0_nop; do [[ -x $R/../variants/$a/lookup_server ]] && ARMS="$ARMS $a"; done
echo "[$(date +%T)] router ab isolated: $ARMS"; ./router_ab.sh router_ab.csv isolated 3 $ARMS > router_ab_iso.log 2>&1; grep -E " r[0-9]:" router_ab_iso.log | tail -14
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
echo "[$(date +%T)] router ab shared"; ./router_ab.sh router_ab.csv shared 3 $ARMS > router_ab_shared.log 2>&1; grep -E " r[0-9]:" router_ab_shared.log | tail -14
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo "[$(date +%T)] ROUTER_AB_CHAIN_DONE"
