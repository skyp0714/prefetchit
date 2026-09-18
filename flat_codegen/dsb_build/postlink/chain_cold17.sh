#!/usr/bin/env bash
# Round 32: measured-overhead pruning. Instruction-sample the best plan binary (cold8) to count executed prefetches per site, drop sites
# whose executions exceed 10x the misses they save, regenerate (v10), build cold14 (+twin), measure gs / cold8 / cold14 / cold14_nop.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD16_DONE logs/chain_cold16.log 2>/dev/null; do sleep 15; done
L=$DB/libs_utl_g; echo "[$(date +%T)] instruction profile of cold8"; SHARED_CORES=0-35 ./cold_site_profile.sh $DB/out_utl_cold8 $L dsb-deps-g results/prof_cold8 2>&1 | tail -2 | cut -c1-300
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v10.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20 --site-exec results/prof_cold8/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/trace_gs_lbr/plan_stats_v10.txt | head -3 | cut -c1-250
n=cold14; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v10.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-plan10"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan10 - > $PL/logs/deps_plan10.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan10.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan10 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan10 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m3 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD17_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold8=$DB/out_utl_cold8:$L:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round32 arms: $ARMS"; ./dsb_warm_ab2.sh results/round32 3 $ARMS > logs/round32.log 2>&1
python3 summarize_ab.py results/round32/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD17_DONE"
