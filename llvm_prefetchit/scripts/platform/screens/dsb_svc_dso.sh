#!/usr/bin/env bash
# per-service DSO/symbol breakdown of L2I misses for the hottest DSB services (after the MariaDB clean pass; no other measurement running)
set -u
until grep -q MARIADB_FINAL_DONE /tmp/mariadb_final.log; do sleep 30; done
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/dsb_socialnetwork/svc_dso; mkdir -p $OUT
cd $SN; docker compose up -d > $OUT/up.log 2>&1; sleep 25
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $OUT/init.log 2>&1; tail -1 $OUT/init.log
LUA=/tmp/screen_inputs/mixed-workload-nosocket.lua
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/warmup.log 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 60 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/wrk2.log 2>&1 &
WP=$!; sleep 5
for svc in user-timeline-service home-timeline-service compose-post-service post-storage-service nginx-thrift; do
  pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-$svc-1); cg=$(awk -F: 'NR==1{print $3}' /proc/$pid/cgroup)
  echo ps101899 | sudo -S perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -c 1000 -o $OUT/$svc.data -a -G "${cg#/}" -- sleep 30 > /dev/null 2>&1 &
done; wait
grep -E "Requests/sec|Non-2xx" $OUT/wrk2.log
for svc in user-timeline-service home-timeline-service compose-post-service post-storage-service nginx-thrift; do
  echo ps101899 | sudo -S chown hnpark2 $OUT/$svc.data 2>/dev/null
  echo "== $svc: misses by DSO"; perf report -i $OUT/$svc.data --sort dso --stdio 2>/dev/null | grep -vE "^#|^$" | head -6
  echo "   top symbols:"; perf report -i $OUT/$svc.data --sort sym --stdio 2>/dev/null | grep -vE "^#|^$" | head -5 | cut -c1-110
done
docker compose down > /dev/null 2>&1; echo DSBSVC_DONE
