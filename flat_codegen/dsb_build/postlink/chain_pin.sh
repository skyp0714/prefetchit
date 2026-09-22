#!/usr/bin/env bash
# Test 1 — does the strategy still help under core pinning?
# Round 40: existing binaries (gs = fat-static base, cold14 = plan v10, twin) under (a) main core + thread pool (36:37-40) and (b) a 4-core
#           cpuset (36-39), 3 reps each.  Round 41: plan regenerated from a *pinned* trace (main:pool) → cold20 (+twin), measured pinned.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until [[ -f results/STACK_READY ]]; do sleep 15; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; S=":-:-:64:0:20000:0"
G="$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g$S"; C="$DB/out_utl_cold14:$L:dsb-deps-g$S"; N="$DB/out_utl_cold14nop:$L:dsb-deps-g$S"
ARMS="gs=$G@36:37-40 cold14=$C@36:37-40 cold14_nop=$N@36:37-40 gsC=$G@36-39 cold14C=$C@36-39 cold14C_nop=$N@36-39"
echo "[$(date +%T)] round40 (pinned) arms: $ARMS"; rm -rf results/round40; ./dsb_warm_ab2.sh results/round40 3 $ARMS > logs/round40.log 2>&1
python3 summarize_ab.py results/round40/runs.csv gs 2>/dev/null | sed -n 3,9p
echo "[$(date +%T)] pinned traces of gs"; PIN=36:37-40 ./cold_trace_lbr.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_pin_lbr 0.9 2>&1 | tail -2 | cut -c1-200
PIN=36:37-40 ./cold_trace_rate.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_pin_rate 2>&1 | tail -1 | cut -c1-200
python3 cold_plan.py results/trace_gs_pin_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_pin.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_pin_rate/rates.txt --max-cost 20 --site-exec results/prof_cold8/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/trace_gs_pin_lbr/plan_stats.txt | grep -E "samples=|measured|cost" | cut -c1-220
n=cold20; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_pin.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-planpin"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-planpin - > $PL/logs/deps_planpin.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_planpin.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-planpin "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-planpin > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f.nop ]] || { echo "BUILD FAILED $n"; echo "[$(date +%T)] CHAIN_PIN_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)')"; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService; rm -rf $DB/libs_utl_$n $DB/libs_utl_${n}nop
ARMS="gs=$G@36:37-40 cold14=$C@36:37-40 $n=$DB/out_utl_$n:$L:dsb-deps-g$S@36:37-40 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g$S@36:37-40"
echo "[$(date +%T)] round41 (pinned-trace plan) arms: $ARMS"; rm -rf results/round41; ./dsb_warm_ab2.sh results/round41 3 $ARMS > logs/round41.log 2>&1
python3 summarize_ab.py results/round41/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_PIN_DONE"
