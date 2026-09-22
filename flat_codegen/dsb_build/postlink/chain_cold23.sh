#!/usr/bin/env bash
# Round 37: re-attribution without the hot sites (functions with >= 100 instruction samples on prefetches in cold8's profile are removed
# from the candidate set, so their lines move to colder sites instead of being dropped) + measured pruning (v14, cold18 + twin).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD22_DONE logs/chain_cold22.log 2>/dev/null; do sleep 15; done
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v14.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20 --exclude-sites $DB/plans/cold_hot_sites.txt --site-exec results/prof_cold8/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/trace_gs_lbr/plan_stats_v14.txt | grep -E "excluded|measured|samples=" | cut -c1-200
n=cold18; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v14.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-plan14"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan14 - > $PL/logs/deps_plan14.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan14.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan14 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan14 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; echo "[$(date +%T)] CHAIN_COLD23_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold14=$DB/out_utl_cold14:$L:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round37 arms: $ARMS"; ./dsb_warm_ab2.sh results/round37 3 $ARMS > logs/round37.log 2>&1
python3 summarize_ab.py results/round37/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD23_DONE"
