#!/usr/bin/env bash
# after the Router/SetAlgebra screens: HDSearch screen (if its mid-tier built)
R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; cd $R
until grep -q MUSUITE_CHAIN_DONE musuite_chain.log 2>/dev/null; do sleep 10; done
if [[ -x $S/HDSearch/mid_tier_service/service/mid_tier_server ]]; then
  ( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
  echo "[$(date +%T)] HDSearch"; ./musuite_screen.sh HDSearch musuite.csv ${QPS:-1000} > HDSearch.log 2>&1; tail -3 HDSearch.log | cut -c1-120
  kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
else echo "HDSearch mid-tier not built"; fi
echo "[$(date +%T)] MUSUITE_CHAIN2_DONE"
