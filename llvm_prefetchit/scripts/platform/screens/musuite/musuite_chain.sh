#!/usr/bin/env bash
# Router and SetAlgebra cold-start screens with the socialNetwork load as co-tenant noise (containers on 0-35)
R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; cd $R
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
for svc in Router SetAlgebra; do echo "[$(date +%T)] $svc"; ./musuite_screen.sh $svc musuite.csv ${QPS:-3000} > ${svc}.log 2>&1; tail -3 ${svc}.log | cut -c1-120; done
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo "[$(date +%T)] MUSUITE_CHAIN_DONE"
