#!/usr/bin/env bash
# media movie-id capacity pipeline (A-2/A-3, alone regime, C6 off): fat-static clang base → stack + dataset → screen → LBR/rate traces →
# cold plan v4 → plan build + twin → 5-rep A/B (stock / gs / plan / twin). Waits for the Django SWPF chain so nothing overlaps a measurement.
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
CD=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919; VW=/home/hnpark2/prefetchit/llvm_prefetchit/results/verilator_asm_20260920
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920; mkdir -p $O/plans $O/traces $O/logs
until grep -qE "DJANGO_STATIC_DONE|DJANGO_STATIC_FAILED" /home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919/logs/chain8.log 2>/dev/null; do sleep 60; done   # measurements are serialized across workloads
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
cd $DB
echo "[$(date +%T)] build gs (clang-19 -O3 fat-static, no pass)"
STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh gs dsb-deps-jammy "" 2>&1 | tail -6
[[ -x $DB/out_${OUTPFX}_gs/$SVCBIN ]] || { echo "gs build FAILED"; tail -25 $DB/out_${OUTPFX}_gs/build.log; echo "[$(date +%T)] MEDIA_FAILED"; exit 1; }
echo "[$(date +%T)] stack up with gs + dataset init"
bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init; cstate 1
bash $MD/media_stack.sh smoke
echo "[$(date +%T)] LBR trace"; MODE=lbr timeout 900 bash $MD/media_trace.sh $O/traces/lbr_gs gs 2>&1 | tail -5
echo "[$(date +%T)] rate trace"; MODE=rate timeout 900 bash $MD/media_trace.sh $O/traces/rate_gs gs 2>&1 | tail -3
echo "[$(date +%T)] plan v4"
LIBC=$(docker run --rm --entrypoint bash dsb-deps-jammy -c "ls /lib/x86_64-linux-gnu/libc.so.6" 2>/dev/null); HOSTLIBC=/lib/x86_64-linux-gnu/libc.so.6
nm --defined-only $DB/out_${OUTPFX}_gs/$SVCBIN | awk '$2~/[TtWw]/{print $3}' | sort -u > $O/plans/instrumentable.txt
CPS=$(python3 -c "print(int(2.0e9))")
read -r REF HZ < <(python3 $CD/calib_rates.py $O/traces/rate_gs $CPS 25 _ZN6media*  2>/dev/null || echo "main 1000")
python3 $DB/postlink/cold_plan.py $O/traces/lbr_gs $DB/out_${OUTPFX}_gs/$SVCBIN $HOSTLIBC $O/plans/instrumentable.txt $O/plans/plan_v4.json \
  --exe-suffix /custom/$SVCBIN --libc-name libc.so.6 --local-aliases --fallback --drop-own-line0 --trace-secs 25 2>&1 | tail -12
[[ -s $O/plans/plan_v4.json ]] || { echo "plan FAILED"; echo "[$(date +%T)] MEDIA_FAILED"; exit 1; }
echo "[$(date +%T)] static cost plan (no profile)"
taskset -c 30 timeout 3600 python3 /home/hnpark2/prefetchit/llvm_prefetchit/tools/static_cost_plan.py $DB/out_${OUTPFX}_gs/$SVCBIN $O/plans/plan_static.json \
  --local-aliases --instrumentable $O/plans/instrumentable.txt --lines 2 --budget 0.005 2>&1 | tail -4
python3 /home/hnpark2/prefetchit/llvm_prefetchit/tools/compare_plans.py $O/plans/plan_static.json $O/plans/plan_v4.json 2>&1 | tail -4
echo "[$(date +%T)] build plan arms (trace ceiling p4, static check st1)"
cd $DB; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh p4 dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/plan_v4.json" 2>&1 | tail -4
cd $DB; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh st1 dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$O/plans/plan_static.json" 2>&1 | tail -4
ARMS="gs"; [[ -x $DB/out_${OUTPFX}_p4/$SVCBIN ]] && ARMS="$ARMS p4 p4nop"; [[ -x $DB/out_${OUTPFX}_st1/$SVCBIN ]] && ARMS="$ARMS st1"
echo "[$(date +%T)] A/B: stock $ARMS"; timeout 5400 bash $MD/media_ab.sh $O/ab_round1 5 stock $ARMS 2>&1 | tail -30
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIA_DONE"
