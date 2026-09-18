#!/usr/bin/env bash
# Decompose the shared-core (cold start) loss of user-timeline: top-down + ITLB/DTLB walks + L2 data misses + branch mispredicts,
# shared (container on 0-35 with all others) vs isolated (main@40 / pool@41-44, others moved off 40-44). Runs after the μSuite screens.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; C=socialnetwork-user-timeline-service-1; OUT=$PL/results/decomp; mkdir -p $OUT
until grep -q MUSUITE_CHAIN2_DONE /home/hnpark2/prefetchit/benchmarks/MicroSuite/run/musuite_chain2.log 2>/dev/null; do sleep 15; done
EV1='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I_miss/,cpu/event=0x24,umask=0x21,name=L2D_miss/,cpu/event=0x11,umask=0x0e,name=ITLB_walk/,cpu/event=0x12,umask=0x0e,name=DTLB_walk/,branch-misses,branches'
EV2='{slots,topdown-retiring,topdown-bad-spec,topdown-fe-bound,topdown-be-bound}'
run(){ local mode=$1; local pid; pid=$(docker inspect -f '{{.State.Pid}}' $C)
  taskset -c 40-42 $W -D exp -t 3 -c 48 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1
  taskset -c 40-42 $W -D exp -t 3 -c 48 -d 80 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1 & LP=$!; sleep 8
  echo ps101899 | sudo -S -p '' perf stat -x, -e $EV1 -p $pid -- sleep 30 2> $OUT/ev1_$mode.txt > /dev/null
  echo ps101899 | sudo -S -p '' perf stat -x, -e "$EV2" -p $pid -- sleep 25 2> $OUT/ev2_$mode.txt > /dev/null
  wait $LP; }
for c in $(docker ps --format '{{.Names}}' | grep "^socialnetwork"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
echo "[$(date +%T)] shared"; run shared
for c in $(docker ps --format '{{.Names}}' | grep "^socialnetwork" | grep -v user-timeline-service); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
echo ps101899 | sudo -S -p '' nohup $PL/pin_threads.sh $C 40 41-44 > /dev/null 2>&1 & PINPID=$!; sleep 3
echo "[$(date +%T)] isolated"; run isolated
echo ps101899 | sudo -S -p '' pkill -P $PINPID > /dev/null 2>&1; echo ps101899 | sudo -S -p '' kill $PINPID > /dev/null 2>&1; docker update --cpuset-cpus 0-35 $C > /dev/null 2>&1
python3 - $OUT <<'PY'
import csv,sys,os
out=sys.argv[1]
def rd(f):
    v={}
    for r in csv.reader(open(f)):
        if len(r)>=3:
            try: v[r[2]]=float(r[0])
            except: pass
    return v
print("| metric | shared | isolated |"); print("|---|---:|---:|")
s=rd(f"{out}/ev1_shared.txt"); i=rd(f"{out}/ev1_isolated.txt")
for k,lab in (('L2I_miss','L2 code misses / kI'),('L2D_miss','L2 demand data misses / kI'),('ITLB_walk','ITLB walks / kI'),('DTLB_walk','DTLB load walks / kI'),('branch-misses','branch mispredicts / kI')):
    print(f"| {lab} | {1000*s.get(k,0)/s['instructions']:.2f} | {1000*i.get(k,0)/i['instructions']:.2f} |")
print(f"| IPC | {s['instructions']/s['cycles']:.3f} | {i['instructions']/i['cycles']:.3f} |")
s2=rd(f"{out}/ev2_shared.txt"); i2=rd(f"{out}/ev2_isolated.txt")
for k in ('topdown-retiring','topdown-bad-spec','topdown-fe-bound','topdown-be-bound'):
    if k in s2 and 'slots' in s2: print(f"| {k} (% of slots) | {100*s2[k]/s2['slots']:.1f} | {100*i2.get(k,0)/i2.get('slots',1):.1f} |")
PY
echo "[$(date +%T)] DECOMP_DONE"
