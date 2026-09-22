#!/usr/bin/env bash
# Rerun of the plan round after fixing libc anchors: plan-mode deps + service (cold5), round 21, twin/prefetch traces + target analysis.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
PLANENV="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_gs.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image (plan mode)"; (cd $DB && EXTRA_PASS_ENV="$PLANENV" bash rebuild_deps_static.sh dsb-deps-plan - > $PL/logs/deps_plan.log 2>&1); grep -E "LIBS_DONE|DEP_MAKE_FAILED|READY" $PL/logs/deps_plan.log | tail -2
echo "[$(date +%T)] service build cold5"; (cd $DB && rm -rf out_utl_cold5 libs_utl_cold5 libs_utl_cold5nop; FATSTATIC=1 bash build_utl_variant.sh cold5 dsb-deps-plan "$PLANENV" > $PL/logs/build_utl_cold5.log 2>&1)
grep -h "prefetchit-cold-plan:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | awk '{for(i=1;i<=NF;i++){split($i,a,"="); if(a[1]=="sites")s+=a[2]; if(a[1]=="direct")d+=a[2]; if(a[1]=="got")g+=a[2]}} END{print "service plan: sites="s" direct="d" got="g}'
f=$DB/out_utl_cold5/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED cold5"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD6_DONE" >> logs/chain_cold6.log; exit 1; }
echo "cold5: size=$(stat -c %s $f) rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_cold5nop; cp $f.nop $DB/out_utl_cold5nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold5=$DB/out_utl_cold5:$L:dsb-deps-g:-:-:64:0:20000:0 cold5_nop=$DB/out_utl_cold5nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round21 arms: $ARMS"; rm -rf results/round21; ./dsb_warm_ab2.sh results/round21 3 $ARMS > logs/round21.log 2>&1
python3 summarize_ab.py results/round21/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] trace cold5 twin + cold5"
SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold5nop $L dsb-deps-g results/trace_cold5nop 0.9 2>&1 | tail -2
SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold5 $L dsb-deps-g results/trace_cold5 0.9 2>&1 | tail -2
python3 cold_target_analysis.py $f results/trace_cold5nop results/trace_cold5 > results/target_analysis_cold5.txt 2>&1; head -12 results/target_analysis_cold5.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD6_DONE" | tee -a logs/chain_cold6.log
