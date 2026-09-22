#!/usr/bin/env bash
# Router A/B: arms from MicroSuite/variants/<arm>/{lookup_server,mid_tier_server}; leaf+mid-tier measured 30 s under 3,000 qps open-loop load.
# Usage: router_ab.sh OUTCSV MODE(shared|isolated) REPS arm... ; shared = servers on 0-42 with the DSB noise loop; isolated = 36-39.
set -u
OUT=$1; MODE=$2; REPS=$3; shift 3; ARMS=("$@"); S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; V=/home/hnpark2/prefetchit/benchmarks/MicroSuite/variants; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run
EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I/,context-switches'; [[ -f $OUT ]] || echo "arm,tier,mode,rep,instr,cycles,l2i,cs,p50us,p99us" > $OUT
cores=0-42; [[ $MODE == isolated ]] && cores=36-39
for rep in $(seq 1 $REPS); do for arm in "${ARMS[@]}"; do
  taskset -c $cores memcached -p 11311 -t 2 -m 512 -u $USER > /tmp/mc.log 2>&1 & MC=$!; sleep 1
  (cd $S/Router/lookup_service/service && exec taskset -c $cores $V/$arm/lookup_server 127.0.0.1:50052 11311 4 0 > /tmp/leaf.log 2>&1) & LEAF=$!; sleep 2
  (cd $S/Router/mid_tier_service/service && exec taskset -c $cores $V/$arm/mid_tier_server 1 $R/router_leaf_ips.txt 127.0.0.1:50051 4 4 4 1 > /tmp/mid.log 2>&1) & MID=$!; sleep 2
  (cd $S/Router/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/Router/twitter_requests_query_set.dat /tmp/res.txt 60 3000 127.0.0.1:50051 90 10 > /tmp/load_router_$arm.log 2>&1) & LP=$!; sleep 15
  perf stat -x, -e $EV -p $LEAF -- sleep 30 2> /tmp/cs_leaf.txt > /dev/null & M1=$!; perf stat -x, -e $EV -p $MID -- sleep 30 2> /tmp/cs_mid.txt > /dev/null & M2=$!; wait $M1 $M2; wait $LP
  lat=$(grep -oE "^[0-9 ]+[0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+ [0-9.]+" /tmp/load_router_$arm.log | tail -1)
  python3 - $arm $MODE $rep $OUT /tmp/cs_leaf.txt /tmp/cs_mid.txt "$lat" <<'PY'
import csv,sys
arm,mode,rep,out,fl,fm,lat=sys.argv[1:8]
def rd(f):
    v={}
    for r in csv.reader(open(f)):
        if len(r)>=3:
            try: v[r[2]]=float(r[0])
            except: pass
    return v
t=lat.split(); p50=t[3] if len(t)>4 else '0'; p99=t[10] if len(t)>10 else '0'
for tier,f in (('leaf',fl),('midtier',fm)):
    v=rd(f); open(out,'a').write(f"{arm},{tier},{mode},{rep},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f},{p50},{p99}\n")
    print(f"{arm} {tier} {mode} r{rep}: MPKI={1000*v.get('L2I',0)/max(1,v.get('instructions',1)):.1f} IPC={v.get('instructions',0)/max(1,v.get('cycles',1)):.3f} cycles={v.get('cycles',0)/1e9:.2f}G")
PY
  kill $LEAF $MID $MC 2>/dev/null; sleep 2; killall -q lookup_server mid_tier_server 2>/dev/null; sleep 1
done; done
echo ROUTER_AB_DONE
