#!/usr/bin/env bash
# Wake-attributed line list for a user-timeline binary (fat-static layout): system-wide L2I-miss samples + sched_switch + sys_exit on the
# shared cores, attributed per hook by wake_lines.py. Usage: utl_wake_pipeline.sh BIN_DIR LIBS_DIR IMAGE OUT LIST_OUT [TOP=256]
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
BIN=$1; LIBS=$2; IMG=$3; OUT=$4; LIST=$5; TOP=${6:-256}; R=${R:-6000}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
export UTL_BIN=$BIN UTL_LIBS=$LIBS UTL_IMG=$IMG WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
cd $SN; docker compose -f docker-compose.yml -f $PL/compose-override-utl-warm.yml up -d --force-recreate --no-deps user-timeline-service > $OUT/up.log 2>&1; sleep 6
docker update --cpuset-cpus ${SHARED_CORES:-0-35} socialnetwork-user-timeline-service-1 > /dev/null 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); echo "pid=$pid"
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > /dev/null 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 50 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2.log 2>&1 & WP=$!; sleep 8
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
echo ps101899 | sudo -S -p '' perf record -a -C ${SHARED_CORES:-0-35} -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -c 2003 -e sched:sched_switch -e raw_syscalls:sys_exit -o $OUT/wake.data -- sleep 30 > $OUT/record.log 2>&1
wait $WP; echo ps101899 | sudo -S -p '' chmod a+r $OUT/wake.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/wake.data -F comm,tid,time,event,ip,sym,dso,trace 2> $OUT/script.err | grep -E '^\s*UserTimeline' > $OUT/events.txt
wc -l < $OUT/events.txt; MAIN_NAME=UserTimelineService python3 $PL/wake_lines.py $OUT/events.txt $OUT/maps.txt $LIST --top $TOP | tail -5
rm -f $OUT/wake.data
