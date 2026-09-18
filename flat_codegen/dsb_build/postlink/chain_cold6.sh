#!/usr/bin/env bash
# After the counter round: LBR trace of the fat-static base (gs) → trace-guided cold plan → static-only deps + service built in plan mode
# (cold5) → round 21 = gs / cold5 / cold5_nop × 3 → target analysis of cold5 (its twin trace vs its static targets).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD5_DONE logs/chain_cold5.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] LBR trace gs"; SHARED_CORES=0-35 ./cold_trace_lbr.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_lbr 0.9 2>&1 | tail -3
echo "[$(date +%T)] plan"; python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_syms.txt $DB/plans/cold_plan_gs.json 2>&1 | tee results/trace_gs_lbr/plan_stats.txt | cut -c1-300
[[ -s $DB/plans/cold_plan_gs.json ]] || { echo "PLAN FAILED"; exit 1; }
PLANENV="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_gs.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image (plan mode)"; (cd $DB && EXTRA_PASS_ENV="$PLANENV" bash rebuild_deps_static.sh dsb-deps-plan - > $PL/logs/deps_plan.log 2>&1); grep -E "LIBS_DONE|DEP_MAKE_FAILED|READY" $PL/logs/deps_plan.log | tail -2
grep -h "prefetchit-cold-plan:" $DB/dep_make_jaeger-client-cpp-0.4.2.log $DB/dep_make_thrift-0.12.0.log 2>/dev/null | awk '{s+=$2; d+=$3; g+=$4} END{print "lib plan lines:", NR}' 
echo "[$(date +%T)] service build cold5"; (cd $DB && rm -rf out_utl_cold5 libs_utl_cold5 libs_utl_cold5nop; FATSTATIC=1 bash build_utl_variant.sh cold5 dsb-deps-plan "$PLANENV" > $PL/logs/build_utl_cold5.log 2>&1)
grep -h "prefetchit-cold-plan:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | awk '{for(i=1;i<=NF;i++){split($i,a,"="); if(a[1]=="sites")s+=a[2]; if(a[1]=="direct")d+=a[2]; if(a[1]=="got")g+=a[2]}} END{print "service plan: sites="s" direct="d" got="g}'
f=$DB/out_utl_cold5/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED cold5"; grep -m3 -E "error|Error" $PL/logs/build_utl_cold5.log | cut -c1-200; exit 1; }
echo "cold5: size=$(stat -c %s $f) rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_cold5nop; cp $f.nop $DB/out_utl_cold5nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold5=$DB/out_utl_cold5:$L:dsb-deps-g:-:-:64:0:20000:0 cold5_nop=$DB/out_utl_cold5nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round21 arms: $ARMS"; ./dsb_warm_ab2.sh results/round21 3 $ARMS > logs/round21.log 2>&1
python3 summarize_ab.py results/round21/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] trace cold5 twin + cold5 for the target analysis"
SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold5nop $L dsb-deps-g results/trace_cold5nop 0.9 2>&1 | tail -2
SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold5 $L dsb-deps-g results/trace_cold5 0.9 2>&1 | tail -2
python3 cold_target_analysis.py $f results/trace_cold5nop results/trace_cold5 > results/target_analysis_cold5.txt 2>&1; head -12 results/target_analysis_cold5.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD6_DONE"
