#!/usr/bin/env bash
# Round 26: plan v5 = cost-aware v4 selection with epoch gating (each site fires once per request per thread; epoch++ at ReadUserTimeline),
# rate capped at 6000/s in the cost model so hot sites become admissible. Arms gs / cold9 / cold9_nop, 3 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD10_DONE logs/chain_cold10.log 2>/dev/null; do sleep 15; done
EPFN=_ZN14social_network19UserTimelineHandler16ReadUserTimelineERSt6vectorINS_4PostESaIS2_EElliiRKSt3mapINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESC_St4lessISC_ESaISt4pairIKSC_SC_EEE
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v5.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --rate-cap 6000 --max-cost 20 --epoch-gate --epoch-fn $EPFN 2>&1 | tee results/trace_gs_lbr/plan_stats_v5.txt | head -3 | cut -c1-250
n=cold9; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v5.json PREFETCHIT_COLD_DIRECT_IN_PIC=1 PREFETCHIT_COLD_EPOCH=1 PREFETCHIT_COLD_EPOCH_FN=$EPFN"
echo "[$(date +%T)] deps image dsb-deps-plan5"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan5 - > $PL/logs/deps_plan5.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan5.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan5 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan5 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD11_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') gated=$(objdump -d $f | grep -c 'cmp.*%r11d,%fs') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round26 arms: $ARMS"; ./dsb_warm_ab2.sh results/round26 3 $ARMS > logs/round26.log 2>&1
python3 summarize_ab.py results/round26/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] traces"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_${n}nop $L dsb-deps-g results/trace_${n}nop 0.9 2>&1 | tail -1; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_$n $L dsb-deps-g results/trace_$n 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_${n}nop results/trace_$n > results/target_analysis_$n.txt 2>&1; head -14 results/target_analysis_$n.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD11_DONE"
