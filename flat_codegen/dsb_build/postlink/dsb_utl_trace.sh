#!/usr/bin/env bash
# LBR trace of L2I code misses in the user-timeline-service process under the mixed wrk2 load.
# Usage: dsb_utl_trace.sh OUTDIR [DUR=40] [PERIOD=2003]
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
OUT=$1; DUR=${2:-40}; PERIOD=${3:-2003}; R=${R:-6000}; mkdir -p $OUT
pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1)
taskset -c 60-67 $W -D exp -t 8 -c 64 -d $((DUR+25)) -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2.log 2>&1 &
WP=$!; sleep 12
echo ps101899 | sudo -S perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c $PERIOD -p $pid -o $OUT/l2miss.data -- sleep $DUR > $OUT/perf_record.log 2>&1
wait $WP
echo ps101899 | sudo -S chmod a+r $OUT/l2miss.data
echo ps101899 | sudo -S perf script -i $OUT/l2miss.data -F ip,sym,dso,brstack > $OUT/lbr_raw.txt 2> $OUT/perf_script.err
echo ps101899 | sudo -S perf report -i $OUT/l2miss.data --stdio --sort dso 2>/dev/null | grep -E "^\s+[0-9.]+%" | head -12 > $OUT/dso_share.txt
wc -l $OUT/lbr_raw.txt; cat $OUT/dso_share.txt
