#!/usr/bin/env bash
# μSuite realistic screen: leaf + mid-tier (+ memcached for Router) pinned to CORES (4), open-loop load generator on 40-42, qps sweep
# until the pinned cores exceed ~85% or latency blows up; per step: util, user-mode L2I MPKI / IPC per tier, p50/p99.
# Usage: musuite_realistic_sweep.sh OUT.csv Router|SetAlgebra|HDSearch [qps...]
OUT=$1; APP=$2; shift 2; QPSS=${@:-1000 2000 3000 4000 6000 8000}; CORES=${CORES:-36-39}; NC=4
S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; RR=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; V=/home/hnpark2/prefetchit/benchmarks/MicroSuite/variants/base
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'; [[ -f $OUT ]] || echo "app,tier,cores,qps,achieved_qps,util_pct,l2i,instr,cycles,mpki,ipc,p50us,p99us" > $OUT
start() { case $APP in
  Router) taskset -c $CORES memcached -p 11311 -t 2 -m 512 -u $USER > /tmp/mc.log 2>&1 & MC=$!; sleep 1
    (cd $S/Router/lookup_service/service && exec taskset -c $CORES $V/lookup_server 127.0.0.1:50052 11311 4 0 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 2
    (cd $S/Router/mid_tier_service/service && exec taskset -c $CORES $V/mid_tier_server 1 $RR/router_leaf_ips.txt 127.0.0.1:50051 4 4 4 1 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
    LOAD="cd $S/Router/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/Router/twitter_requests_query_set.dat /tmp/res.txt 50 QPS 127.0.0.1:50051 90 10";;
  SetAlgebra) (cd $S/SetAlgebra/intersection_service/service && exec taskset -c $CORES ./intersection_server 127.0.0.1:50054 $D/SetAlgebra/posting_lists_1G.txt 4 0 1 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 25
    (cd $S/SetAlgebra/union_service/service && exec taskset -c $CORES ./mid_tier_server 1 $RR/sa_leaf_ips.txt 127.0.0.1:50053 4 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
    LOAD="cd $S/SetAlgebra/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/SetAlgebra/query_set.txt /tmp/res.txt 50 QPS 127.0.0.1:50053";;
  HDSearch) (cd $S/HDSearch/bucket_service/service && exec taskset -c $CORES ./bucket_server $D/HDSearch/image_feature_vectors.dat 127.0.0.1:50056 2 4 0 1 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 40
    (cd $S/HDSearch/mid_tier_service/service && LD_LIBRARY_PATH=/home/hnpark2/prefetchit/benchmarks/MicroSuite/flann_local/lib exec taskset -c $CORES ./mid_tier_server 1 20 2 1 $RR/hd_leaf_ips.txt $D/HDSearch/image_feature_vectors.dat 127.0.0.1:50055 4 4 4 1 > /tmp/mid.log 2>&1) & MID=$!; sleep 5
    LOAD="cd $S/HDSearch/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/HDSearch/image_feature_vectors.dat /tmp/res.txt 1 50 QPS 127.0.0.1:50055 /tmp/t /tmp/q /tmp/u";;
esac; }
stop() { kill $MID $LEAF ${MC:-} 2>/dev/null; sleep 2; killall -q lookup_server mid_tier_server intersection_server bucket_server 2>/dev/null; [[ -n ${MC:-} ]] && kill -9 $MC 2>/dev/null; sleep 1; }
start
for Q in $QPSS; do
  (bash -c "${LOAD/QPS/$Q}" > /tmp/lg_$Q.log 2>&1) & LP=$!; sleep 12
  perf stat -x, -o /tmp/ms_leaf.csv -e $EV -p $LEAF -- sleep 30 > /dev/null 2>&1 & P1=$!; perf stat -x, -o /tmp/ms_mid.csv -e $EV -p $MID -- sleep 30 > /dev/null 2>&1 & P2=$!; wait $P1 $P2; wait $LP
  python3 - $APP $CORES $NC $Q $OUT <<'PY'
import csv,re,sys
app,cores,nc,q,out=sys.argv[1:6]
lg=open(f'/tmp/lg_{q}.log').read()
lat=[l for l in lg.splitlines() if re.match(r'^[0-9 ]+[0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+',l)]
t=lat[-1].split() if lat else []; p50=float(t[3]) if len(t)>4 else 0; p99=float(t[10]) if len(t)>10 else 0; ach=float(t[0]) if t else 0
res=[]
for tier,f in (('leaf','/tmp/ms_leaf.csv'),('midtier','/tmp/ms_mid.csv')):
    v={}
    for r in csv.reader(open(f)):
        if len(r)>=3:
            try: v[r[2]]=float(r[0])
            except: pass
    i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); tc=v.get('task-clock',0); util=100*tc/(30000*int(nc))
    open(out,'a').write(f"{app},{tier},{cores},{q},{ach:.0f},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{p50},{p99}\n"); res.append((tier,util,1000*m/i if i else 0,i/c if c else 0))
print(f"{app} qps={q} achieved={ach:.0f} p50={p50}us p99={p99}us | "+' '.join(f"{t}: util={u:.0f}% MPKI={mp:.1f} IPC={ip:.2f}" for t,u,mp,ip in res))
sys.exit(1 if (p99>20000 or max(u for _,u,_,_ in res)>85) else 0)
PY
  [[ $? -ne 0 ]] && { echo "limit reached at qps=$Q"; break; }
done; stop; echo MUSUITE_${APP}_DONE
