#!/usr/bin/env bash
# Where does the fat-static gain come from? Per-arm counters (ITLB/DTLB walks, branch mispredicts by type, L2 code/data misses) under the standard
# load, service pid, 30 s window. Usage: cold_counters.sh OUT REPS name=bindir:libsdir:image ...
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
OUT=$1; REPS=$2; shift 2; mkdir -p $OUT; OUT=$(readlink -f $OUT); R=${R:-6000}
EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I_MISS/,cpu/event=0x24,umask=0x21,name=L2D_MISS/,cpu/event=0x11,umask=0x0e,name=ITLB_WALK/,cpu/event=0x12,umask=0x0e,name=DTLB_LD_WALK/,branch-misses,cpu/event=0xc5,umask=0x80,name=BR_MISP_INDIRECT/,cpu/event=0xc5,umask=0x08,name=BR_MISP_RET/'
CSV=$OUT/counters.csv; [[ -f $CSV ]] || echo "arm,rep,instructions,cycles,L2I_MISS,L2D_MISS,ITLB_WALK,DTLB_LD_WALK,branch-misses,BR_MISP_INDIRECT,BR_MISP_RET" > $CSV
export WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
for rep in $(seq 1 $REPS); do for arm in "$@"; do name=${arm%%=*}; IFS=: read -r bindir libsdir img <<< "${arm#*=}"
  export UTL_BIN=$bindir UTL_LIBS=$libsdir UTL_IMG=$img
  (cd $SN && docker compose -f docker-compose.yml -f $PL/compose-override-utl-warm.yml up -d --force-recreate --no-deps user-timeline-service > $OUT/up_${name}_r$rep.log 2>&1); sleep 6
  docker update --cpuset-cpus ${SHARED_CORES:-0-35} socialnetwork-user-timeline-service-1 > /dev/null 2>&1
  pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1)
  taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > /dev/null 2>&1
  taskset -c 60-67 $W -D exp -t 8 -c 64 -d 60 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2_${name}_r$rep.log 2>&1 & WP=$!; sleep 15
  echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/perf_${name}_r$rep.csv -e $EV -p $pid -- sleep 30 > /dev/null 2>&1; wait $WP
  python3 - $OUT/perf_${name}_r$rep.csv $name $rep $CSV <<'PY'
import csv,sys
f,name,rep,out=sys.argv[1:5]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
cols=["instructions","cycles","L2I_MISS","L2D_MISS","ITLB_WALK","DTLB_LD_WALK","branch-misses","BR_MISP_INDIRECT","BR_MISP_RET"]
open(out,'a').write(f"{name},{rep}," + ",".join(f"{v.get(c,0):.0f}" for c in cols) + "\n")
kI=v.get("instructions",1)/1000
print(f"{name} r{rep}: IPC={v.get('instructions',0)/max(1,v.get('cycles',1)):.3f} " + " ".join(f"{c}/kI={v.get(c,0)/kI:.2f}" for c in cols[2:]))
PY
done; done; echo COUNTERS_DONE
