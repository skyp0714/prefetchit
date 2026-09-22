#!/usr/bin/env bash
# media movie-id in the INTERLEAVED regime (the whole stack on 8 cores = the 55 MPKI point of the screen). The previous attempt was
# invalid because R=2000 saturated the pool (p99 29 s); here the rate is calibrated down until the stack sustains it, keeping the high
# miss rate. Then the corrected pipeline: miss pool -> candidates -> probe build -> MEASURED site rates -> efficiency selection ->
# final build with the loop-free dominator placement -> 5-rep A/B.
set -u
export SVC_CORES=0-7 POOL=0-7 CL_CORES=32-35
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
D=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920; mkdir -p $O/traces $O/plans $O/logs
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init; cstate 1
GOOD=0
for R in 200 400 600 900; do
  pid=$(svc_pid)
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 12 -L -s $LUA $WRK_URL -R $R > /dev/null 2>&1
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 40 -L -s $LUA $WRK_URL -R $R > /tmp/hi_wrk.log 2>&1 & WP=$!; sleep 8
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/hi.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u',instructions:u,cycles:u,task-clock -p $pid -- sleep 20 > /dev/null 2>&1
  wait $WP
  read -r mpki rps p99 < <(python3 - /tmp/hi.csv /tmp/hi_wrk.log <<'PY'
import csv,sys,re
v={}
for r in csv.reader(open(sys.argv[1])):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
w=open(sys.argv[2]).read(); i=v.get('instructions:u',0); l=v.get('L2I',0)
m=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(m.group(1)) if m else 0
m=re.search(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)",w); p99=(float(m.group(1))*(1000 if m.group(2)=='s' else 0.001 if m.group(2)=='us' else 1)) if m else 0
print("%.2f %.0f %.0f" % (1000*l/i if i else 0, rps, p99))
PY
)
  echo "  R=$R: movie-id MPKI=$mpki achieved=${rps} rps p99=${p99}ms"
  if python3 -c "import sys; sys.exit(0 if $p99<300 and $rps>$R*0.9 else 1)"; then RATE=$R; GOOD=1; fi
done
if [[ $GOOD == 0 ]]; then echo "the interleaved stack cannot sustain any tested rate"; echo "[$(date +%T)] MEDIAHI_FAILED"; exit 1; fi
export RATE; echo "[$(date +%T)] operating point: interleaved on 0-7 at R=$RATE"
for i in 1 2 3; do echo "[$(date +%T)] miss trace $i"; MODE=miss WIN=30 timeout 900 bash $MD/media_trace.sh $O/traces/hi_$i gs 2>&1 | grep -E "^miss:" | cut -c1-150; done
python3 $D/miss_pool.py $O/traces/hi_1 $O/traces/hi_2 $O/traces/hi_3 --lib $DB/out_${OUTPFX}_gs/$SVCBIN --out $O/plans/poolhi.json 2>&1 | tail -6
python3 $D/pool_to_plan.py $O/plans/poolhi.json $DB/out_${OUTPFX}_gs/$SVCBIN $O/plans/candhi.json --cap 64 --callers 4 --budget 20000 2>&1 | tail -4
cd $DB; PLACE="PREFETCHIT_COLD_PLACEMENT=dominator PREFETCHIT_COLD_PLACE_MIN_LEAD=20 PREFETCHIT_COLD_PLACE_MAX_LEAD=2000"
echo "[$(date +%T)] probe build"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh probe dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/candhi.json $PLACE" 2>&1 | tail -2
bash $MD/media_stack.sh recreate probe > /dev/null; pin_all
MODE=instr WIN=30 timeout 900 bash $MD/media_trace.sh $O/traces/instrhi probe 2>&1 | grep -E "^instr:" | cut -c1-150
python3 $D/select_by_efficiency.py $O/plans/candhi.json $O/plans/poolhi.json $O/traces/instrhi/site_exec.txt $O/plans/planhi_eff.json --budget 3e7 --miss-secs 90 2>&1 | tail -3
echo "[$(date +%T)] final build"; cd $DB; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh effhi dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/planhi_eff.json $PLACE" 2>&1 | tail -2
bash $MD/media_stack.sh recreate gs > /dev/null; pin_all
ARMS="gs"; for a in effhi effhinop; do if [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]]; then ARMS="$ARMS $a"; fi; done
echo "[$(date +%T)] A/B interleaved (55 MPKI) at R=$RATE: $ARMS"; timeout 7200 bash $MD/media_ab.sh $O/ab_hi 5 $ARMS 2>&1 | tail -12
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIAHI_DONE"
