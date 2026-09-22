#!/usr/bin/env bash
# Capacity/interleaving-only sweep (deep C-states disabled on the cores in use, everything else realistic):
#  1. databases on 4-7 (PG c=4/8/16, MariaDB durable rw t=4/8/16)   2. DaCapo kafka on 8-11 (missing C6-off point)
#  3. after the DCPerf v2 installs: the three DSB stacks in the interleaving regime (all containers on an 8-core pool, then a 16-core pool)
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; DSB=/home/hnpark2/prefetchit/benchmarks/DeathStarBench; PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink
cst() { local mode=$1 cc; shift; for cc in "$@"; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0 $(seq 0 15)' EXIT
cst 1 4 5 6 7 8 9 10 11
echo "[$(date +%T)] databases, C6 off"; CORES=4-7 timeout 1500 $R/c6off_db_sweep.sh $R/c6off_sweep.csv 2>&1 | grep -vE "^\s*$"
echo "[$(date +%T)] dacapo kafka, C6 off (8-11)"; SCR=/tmp/jvm_c6off; mkdir -p $SCR/s_kafka; JDK=/usr/lib/jvm/java-21-openjdk-amd64
taskset -c 8-11 $JDK/bin/java -Xms8g -Xmx8g -XX:ActiveProcessorCount=4 -jar /home/hnpark2/prefetchit/benchmarks/tools/dacapo/dacapo-23.11-MR2-chopin.jar kafka -n 200 --scratch-directory $SCR/s_kafka > $SCR/kafka.log 2>&1 & JP=$!; sleep 40
if kill -0 $JP 2>/dev/null; then perf stat -x, -o /tmp/c6off_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock' -p $JP -- sleep 20 > /dev/null 2>&1; python3 - <<'PY'
import csv; v={}
for r in csv.reader(open('/tmp/c6off_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0)
open('/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918/cause_diag.csv','a').write(f"dacapo/kafka,noC6,8-11,{100*t/(20000*4):.1f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{i:.0f}\n")
print(f"dacapo/kafka noC6: MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
else echo "kafka ended early"; fi; kill $JP 2>/dev/null; sleep 1; kill -9 $JP 2>/dev/null
cst 0 4 5 6 7 8 9 10 11
until grep -q V2_INSTALL_DONE $R/logs/chain_dcperf_v2_install.log 2>/dev/null; do sleep 60; done
echo "[$(date +%T)] stacks in the interleaving regime (C6 off on the pool)"
for POOL in 0-7 0-15; do PN=$(python3 -c "print('$POOL'.split('-')[1])"); cst 1 $(seq 0 $PN)
  echo "[$(date +%T)] socialNetwork pool $POOL"; $PL/reset_sn_stack.sh > $R/logs/c6off_sn_reset_$POOL.log 2>&1
  PREFIX=socialnetwork POOL=$POOL timeout 900 $R/dsb_shared_screen.sh $R/c6off_shared.csv $([[ $POOL == 0-7 ]] && echo "1000 2000 3000" || echo "2000 4000 6000") 2>&1 | grep -vE "^\s*$" | cut -c1-160
  (cd $DSB/socialNetwork && docker compose down > /dev/null 2>&1)
  echo "[$(date +%T)] hotelReservation pool $POOL"; (cd $DSB/hotelReservation && docker compose up -d > /dev/null 2>&1); sleep 25
  PREFIX=hotelreservation URL=http://localhost:5000 LUA=$R/hotel_mixed.lua POOL=$POOL timeout 900 $R/dsb_shared_screen.sh $R/c6off_shared.csv $([[ $POOL == 0-7 ]] && echo "1000 2000 3000" || echo "2000 4000 6000") 2>&1 | grep -vE "^\s*$" | cut -c1-160
  (cd $DSB/hotelReservation && docker compose down > /dev/null 2>&1)
  echo "[$(date +%T)] mediaMicroservices pool $POOL"; (cd $DSB/mediaMicroservices && docker compose up -d > /dev/null 2>&1); sleep 30
  (cd $DSB/mediaMicroservices/scripts && timeout 600 python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > /dev/null 2>&1; timeout 300 bash register_users.sh > /dev/null 2>&1; timeout 300 bash register_movies.sh > /dev/null 2>&1)
  PREFIX=mediamicroservices URL=http://localhost:8080/wrk2-api/review/compose LUA=$R/media_compose_review.lua POOL=$POOL timeout 900 $R/dsb_shared_screen.sh $R/c6off_shared.csv $([[ $POOL == 0-7 ]] && echo "500 1000 1500" || echo "1000 2000 3000") 2>&1 | grep -vE "^\s*$" | cut -c1-160
  (cd $DSB/mediaMicroservices && docker compose down > /dev/null 2>&1); cst 0 $(seq 0 $PN)
done
echo "[$(date +%T)] C6OFF_CHAIN_DONE"
