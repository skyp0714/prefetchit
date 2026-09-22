#!/usr/bin/env bash
# media movie-id at an MPKI of about 10: partial interleaving (the service shares a small cpuset with a few neighbours) is used as a
# knob between the alone regime (4.9) and full interleaving (55). Then the whole corrected pipeline runs on that operating point:
#   miss pool (3 traces) -> candidate plan (body lines at the owning function, entry lines from direct callers)
#   -> probe build -> MEASURED site execution rates -> efficiency selection min(exec,miss)/exec under a budget
#   -> final build with the loop-free dominator placement -> 5-rep A/B + SWPF accounting.
set -u
export SVC_CORES=0-1 POOL=2-31 CL_CORES=32-35 RATE=${RATE:-1000}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
D=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920; mkdir -p $O/traces $O/plans $O/logs
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init
# ---- calibrate: how many neighbours does movie-id need to share 2 cores with to reach ~10 MPKI, at a load the stack sustains?
BEST=""; BESTD=999
for spec in "movie-id-service|0-1" "movie-id-service rating-service|0-1" "movie-id-service rating-service text-service|0-1" "movie-id-service rating-service text-service user-service|0-1"; do
  G=${spec%%|*}; GC=${spec#*|}
  bash $MD/media_layout.sh "$G" $GC 2-31 > /dev/null; cstate 1; sleep 3
  pid=$(svc_pid)
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 12 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 40 -L -s $LUA $WRK_URL -R $RATE > /tmp/cal_wrk.log 2>&1 & WP=$!; sleep 8
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/cal.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u',instructions:u,cycles:u,task-clock -p $pid -- sleep 20 > /dev/null 2>&1
  wait $WP
  read -r mpki util rps p99 < <(python3 - /tmp/cal.csv /tmp/cal_wrk.log <<'PY'
import csv,sys,re
v={}
for r in csv.reader(open(sys.argv[1])):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
w=open(sys.argv[2]).read(); i=v.get('instructions:u',0); l=v.get('L2I',0); t=v.get('task-clock',0)
m=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(m.group(1)) if m else 0
m=re.search(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)",w); p99=(float(m.group(1))*(1000 if m.group(2)=='s' else 0.001 if m.group(2)=='us' else 1)) if m else 0
print(f"{1000*l/i if i else 0:.2f} {t/20000/2*100:.0f} {rps:.0f} {p99:.0f}")
PY
)
  echo "  [$G] on $GC: MPKI=$mpki util=${util}% rps=$rps p99=${p99}ms"
  d=$(python3 -c "print(abs($mpki-10))")
  ok=$(python3 -c "print(1 if $p99<500 and $rps>${RATE}*0.9 else 0)")
  if [[ $ok == 1 ]] && python3 -c "import sys; sys.exit(0 if $d<$BESTD else 1)"; then BEST="$G"; BESTD=$d; fi
  cstate 0
done
[[ -z $BEST ]] && { echo "no usable operating point"; echo "[$(date +%T)] MEDIA10_FAILED"; exit 1; }
echo "[$(date +%T)] operating point: movie-id shares 0-1 with [$BEST]"
bash $MD/media_layout.sh "$BEST" 0-1 2-31 > /dev/null; cstate 1
for i in 1 2 3; do echo "[$(date +%T)] miss trace $i"; MODE=miss WIN=30 timeout 900 bash $MD/media_trace.sh $O/traces/m10_$i gs 2>&1 | grep -E "^miss:" | cut -c1-150; done
python3 $D/miss_pool.py $O/traces/m10_1 $O/traces/m10_2 $O/traces/m10_3 --lib $DB/out_${OUTPFX}_gs/$SVCBIN --out $O/plans/pool10.json 2>&1 | tail -6
python3 $D/pool_to_plan.py $O/plans/pool10.json $DB/out_${OUTPFX}_gs/$SVCBIN $O/plans/cand10.json --cap 64 --callers 4 --budget 20000 2>&1 | tail -4
cd $DB; PLACE="PREFETCHIT_COLD_PLACEMENT=dominator PREFETCHIT_COLD_PLACE_MIN_LEAD=20 PREFETCHIT_COLD_PLACE_MAX_LEAD=2000"
echo "[$(date +%T)] probe build (all candidates, to measure site execution rates)"
STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh probe dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/cand10.json $PLACE" 2>&1 | tail -2
bash $MD/media_stack.sh recreate probe > /dev/null; bash $MD/media_layout.sh "$BEST" 0-1 2-31 > /dev/null
MODE=instr WIN=30 timeout 900 bash $MD/media_trace.sh $O/traces/instr10 probe 2>&1 | grep -E "^instr:" | cut -c1-150
python3 $D/select_by_efficiency.py $O/plans/cand10.json $O/plans/pool10.json $O/traces/instr10/site_exec.txt $O/plans/plan10_eff.json --budget 1e7 --miss-secs 90 2>&1 | tail -3
echo "[$(date +%T)] final build"; cd $DB; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh eff dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/plan10_eff.json $PLACE" 2>&1 | tail -2
bash $MD/media_stack.sh recreate gs > /dev/null; bash $MD/media_layout.sh "$BEST" 0-1 2-31 > /dev/null
ARMS="gs"; for a in eff effnop probe; do [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]] && ARMS="$ARMS $a"; done
echo "[$(date +%T)] A/B at the MPKI-10 point: $ARMS"; timeout 7200 bash $MD/media_ab.sh $O/ab_m10 5 $ARMS 2>&1 | tail -12
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIA10_DONE"
