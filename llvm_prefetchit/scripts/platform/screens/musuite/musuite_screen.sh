#!/usr/bin/env bash
# μSuite cold-start screen: run leaf + mid-tier of one service (Router | SetAlgebra | HDSearch) under an open-loop load generator,
# measure both tiers with perf stat (30 s) in shared mode (servers float on 0-42 with the DSB co-tenant noise) and isolated mode (36-39).
# Usage: musuite_screen.sh SERVICE OUTCSV [QPS]
set -u
SVC=$1; OUT=$2; QPS=${3:-3000}; S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run
WIN=${WIN:-30}; EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I/,context-switches'
[[ -f $OUT ]] || echo "container,mode,instr,cycles,l2i,cs,migr,taskclock_ms" > $OUT
echo "127.0.0.1:50052" > $R/router_leaf_ips.txt; echo "127.0.0.1:50054" > $R/sa_leaf_ips.txt; echo "127.0.0.1:50056" > $R/hd_leaf_ips.txt
measure(){ local name=$1 mode=$2 pid=$3; echo ps101899 | sudo -S -p '' perf stat -x, -e $EV -p $pid -- sleep $WIN 2> /tmp/cs_$name.txt > /dev/null
  python3 - $name $mode $OUT /tmp/cs_$name.txt <<'PY'
import csv,sys
c,mode,out,f=sys.argv[1:5]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
open(out,'a').write(f"{c},{mode},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f},0,0\n")
PY
}
start(){ local cores=$1
  case $SVC in
    Router)
      taskset -c $cores memcached -p 11311 -t 2 -m 512 -u $USER > /tmp/mc.log 2>&1 & MC=$!; sleep 1
      (cd $S/Router/lookup_service/service && taskset -c $cores ./lookup_server 127.0.0.1:50052 11311 4 0 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 2
      (cd $S/Router/mid_tier_service/service && taskset -c $cores ./mid_tier_server 1 $R/router_leaf_ips.txt 127.0.0.1:50051 4 4 4 1 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
      LOAD="cd $S/Router/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/Router/twitter_requests_query_set.dat /tmp/res.txt 70 $QPS 127.0.0.1:50051 90 10";;
    SetAlgebra)
      (cd $S/SetAlgebra/intersection_service/service && taskset -c $cores ./intersection_server 127.0.0.1:50054 $D/SetAlgebra/posting_lists_1G.txt 4 0 1 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 25
      (cd $S/SetAlgebra/union_service/service && taskset -c $cores ./mid_tier_server 1 $R/sa_leaf_ips.txt 127.0.0.1:50053 4 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
      LOAD="cd $S/SetAlgebra/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/SetAlgebra/query_set.txt /tmp/res.txt 70 $QPS 127.0.0.1:50053";;
    HDSearch)
      (cd $S/HDSearch/bucket_service/service && taskset -c $cores ./bucket_server $D/HDSearch/image_feature_vectors.dat 127.0.0.1:50056 2 4 4 0 1 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 40
      (cd $S/HDSearch/mid_tier_service/service && LD_LIBRARY_PATH=/home/hnpark2/prefetchit/benchmarks/MicroSuite/flann_local/lib taskset -c $cores ./mid_tier_server 1 20 2 1 $R/hd_leaf_ips.txt $D/HDSearch/image_feature_vectors.dat 2 127.0.0.1:50055 1 4 4 0 > /tmp/mid.log 2>&1) & MID=$!; sleep 40
      LOAD="cd $S/HDSearch/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/HDSearch/image_feature_vectors.dat /tmp/res.txt 1 70 $QPS 127.0.0.1:50055 /tmp/t /tmp/q /tmp/u";;
  esac
  LEAFPID=$(pgrep -P $LEAF | head -1); MIDPID=$(pgrep -P $MID | head -1); [[ -n $LEAFPID ]] || LEAFPID=$LEAF; [[ -n $MIDPID ]] || MIDPID=$MID
}
stop(){ kill $MID $LEAF ${MC:-} 2>/dev/null; pkill -P $MID 2>/dev/null; pkill -P $LEAF 2>/dev/null; [[ -n ${MC:-} ]] && pkill -P $MC 2>/dev/null; sleep 3; }
for mode in shared isolated; do
  cores=0-42; [[ $mode == isolated ]] && cores=36-39
  MC=; start $cores
  bash -c "$LOAD" > /tmp/load_$SVC.log 2>&1 & LP=$!; sleep 15
  measure ${SVC}_leaf $mode $LEAFPID & measure ${SVC}_midtier $mode $MIDPID; wait
  wait $LP 2>/dev/null; grep -iE "qps|throughput|latency" /tmp/load_$SVC.log | tail -2 | cut -c1-120
  stop; echo "[$(date +%T)] $SVC $mode done"
done
echo MUSUITE_DONE
