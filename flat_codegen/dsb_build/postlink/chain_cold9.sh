#!/usr/bin/env bash
# Round 24: plan v4 = v3 sites/targets but sites chosen by lowest entry rate (cycles+LBR rate trace of gs) and pairs costing more than
# 20 prefetch executions per saved miss dropped. Then deps plan4 + service cold8 (+twin), 3 reps, traces, analysis.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD6_DONE logs/chain_cold6.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] rate trace gs"; SHARED_CORES=0-35 ./cold_trace_rate.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_rate 2>&1 | tail -2 | cut -c1-300
echo "[$(date +%T)] plan v4"; python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v4.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20 2>&1 | tee results/trace_gs_lbr/plan_stats_v4.txt | head -6 | cut -c1-250
n=cold8; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v4.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-plan4"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan4 - > $PL/logs/deps_plan4.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan4.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan4 "$env" > $PL/logs/build_utl_$n.log 2>&1)
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD9_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round24 arms: $ARMS"; ./dsb_warm_ab2.sh results/round24 3 $ARMS > logs/round24.log 2>&1
python3 summarize_ab.py results/round24/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] traces"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_${n}nop $L dsb-deps-g results/trace_${n}nop 0.9 2>&1 | tail -1; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_$n $L dsb-deps-g results/trace_$n 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_${n}nop results/trace_$n > results/target_analysis_$n.txt 2>&1; head -14 results/target_analysis_$n.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD9_DONE"
