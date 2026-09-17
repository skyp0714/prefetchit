#!/usr/bin/env bash
# after the hotel screen: native candidates under socialNetwork co-tenant noise (containers on 0-35): masstree (TailBench), MariaDB durable, PostgreSQL
CS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink/coldscreen; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
cd $CS; until grep -q HOTEL_DONE chain_cold_hotel.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] C-state separation rerun"
./cold_screen_cstate.sh sn_cstate.csv "taskset -c 40-42 /home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk -D exp -t 3 -c 48 -d 70 -L -s /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua http://localhost:8080/wrk2-api/post/compose -R 6000" socialnetwork-user-timeline-service-1 socialnetwork-unique-id-service-1 socialnetwork-social-graph-service-1 socialnetwork-user-mention-service-1 socialnetwork-post-storage-service-1 socialnetwork-compose-post-service-1 socialnetwork-home-timeline-service-1 > sn_cstate.log 2>&1
echo "[$(date +%T)] native screen start"
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
# masstree: integrated, 4 server threads, 2000 qps open-loop -> threads sleep between requests
./cold_screen_proc.sh masstree native.csv "bash -c 'cd /home/hnpark2/prefetchit/benchmarks/tailbench/tailbench/masstree && NTHREADS=4 QPS=2000 MAXREQS=400000 WARMUPREQS=2000 ./run.sh'" "mttest_integrated" > masstree.log 2>&1
# MariaDB durable (fsync + binlog), 8 sysbench threads on 40-42
/home/hnpark2/prefetchit/benchmarks/mariadb/install_base/bin/mariadb-admin --socket=/tmp/mariadb_cold.sock -u root shutdown > /dev/null 2>&1
./cold_screen_proc.sh mariadb native.csv "/home/hnpark2/prefetchit/benchmarks/mariadb/install_base/bin/mariadbd --no-defaults --datadir=/home/hnpark2/prefetchit/benchmarks/mariadb/data --port=3310 --socket=/tmp/mariadb_cold.sock --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=1 --sync-binlog=1 --log-bin=/tmp/mariadb_cold_binlog --skip-networking=0" "mariadbd.*mariadb_cold" "sysbench oltp_read_write --mysql-socket=/tmp/mariadb_cold.sock --mysql-user=root --tables=16 --table-size=200000 --threads=8 --time=120 run" > mariadb.log 2>&1
# PostgreSQL scale 100, 16 pgbench clients
./cold_screen_proc.sh postgres native.csv "/home/hnpark2/prefetchit/benchmarks/pg/install_base/bin/postgres -D /home/hnpark2/prefetchit/benchmarks/pg/data_scale100 -p 5440 -k /tmp" "postgres -D.*data_scale100" "/home/hnpark2/prefetchit/benchmarks/pg/install_base/bin/pgbench -h /tmp -p 5440 -c 16 -j 4 -T 120 -M prepared bench" > postgres.log 2>&1
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo "[$(date +%T)] NATIVE_DONE"
