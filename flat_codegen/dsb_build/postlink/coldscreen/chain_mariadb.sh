#!/usr/bin/env bash
# after round 14: MariaDB wake-up warm-up (trace -> list -> A/B) then a postgres cold-start re-screen with the multi-process fix
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; PG=/home/hnpark2/prefetchit/benchmarks/pg; cd $PL/coldscreen
until grep -q CHAIN_TIMELINE2_DONE $PL/logs/chain_timeline2.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] mariadb trace"; STEP=trace $PL/mariadb_wake_pipeline.sh > mariadb_trace.log 2>&1; tail -7 mariadb_trace.log
echo "[$(date +%T)] mariadb ab"; STEP=ab REPS=3 $PL/mariadb_wake_pipeline.sh > mariadb_ab.log 2>&1; grep -E " r[0-9]:" mariadb_ab.log
echo "[$(date +%T)] postgres re-screen"
W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
./cold_screen_proc.sh postgres native.csv "$PG/install_base/bin/postgres -D $PG/data_scale100 -p 5440 -k /tmp" "postgres -D.*data_scale100" "$PG/install_base/bin/pgbench -h /tmp -p 5440 -c 16 -j 4 -T 120 -M prepared bench" > postgres2.log 2>&1
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
python3 cold_summary.py native.csv; echo "[$(date +%T)] MARIADB_CHAIN_DONE"
