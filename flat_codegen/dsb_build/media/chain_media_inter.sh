#!/usr/bin/env bash
# media movie-id in the INTERLEAVED regime (the whole stack shares an 8-core pool): 55 MPKI, 32x Django's miss rate, same tooling.
# Miss pool from three traces -> cover-everything plan (body lines at the owning function, entry lines from direct callers) with the
# loop-free dominator placement -> 5-rep A/B against the pass-free fat-static base and the NOP twin.
set -u
export SVC_CORES=0-7 POOL=0-7 CL_CORES=32-35 RATE=${RATE:-2000}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920; W=/home/hnpark2/prefetchit/llvm_prefetchit/results/verilator_asm_20260920
mkdir -p $O/traces $O/plans $O/logs
until grep -q "VERILATOR6_DONE" $W/logs/chain_v6.log 2>/dev/null; do sleep 60; done
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init; cstate 1
echo "[$(date +%T)] interleaved: every container on $SVC_CORES"; bash $MD/media_stack.sh smoke
for i in 1 2 3; do echo "[$(date +%T)] miss trace $i"; MODE=miss WIN=30 timeout 900 bash $MD/media_trace.sh $O/traces/imiss_$i gs 2>&1 | grep -E "^miss:|Requests/sec" | cut -c1-150; done
python3 $D/miss_pool.py $O/traces/imiss_1 $O/traces/imiss_2 $O/traces/imiss_3 --lib $DB/out_${OUTPFX}_gs/$SVCBIN --out $O/plans/miss_pool_inter.json 2>&1 | tail -8
python3 $D/pool_to_plan.py $O/plans/miss_pool_inter.json $DB/out_${OUTPFX}_gs/$SVCBIN $O/plans/plan_pool_inter.json --cap 64 --callers 4 --budget 12000 2>&1 | tail -5
cd $DB; PLACE="PREFETCHIT_COLD_PLACEMENT=dominator PREFETCHIT_COLD_PLACE_MIN_LEAD=20 PREFETCHIT_COLD_PLACE_MAX_LEAD=2000"
echo "[$(date +%T)] build pool arm"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh pi dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/plan_pool_inter.json $PLACE" 2>&1 | tail -3
grep -ho "moved=[0-9]* loop_levels_saved=[0-9]*" $DB/out_${OUTPFX}_pi/build.log | awk -F'[= ]' '{m+=$2; l+=$4} END{printf "  placement: moved %d sites, saved %d loop levels\n", m, l}'
ARMS="gs"; [[ -x $DB/out_${OUTPFX}_pi/$SVCBIN ]] && ARMS="$ARMS pi pinop"
echo "[$(date +%T)] A/B interleaved: $ARMS"; timeout 7200 bash $MD/media_ab.sh $O/ab_inter 5 $ARMS 2>&1 | tail -12
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIA_INTER_DONE"
