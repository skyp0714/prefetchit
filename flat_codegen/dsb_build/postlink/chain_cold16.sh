#!/usr/bin/env bash
# Round 31: plan v4 selection with (a) a longer minimum lead (200 cycles: sites further from the miss) and (b) a single site per line
# (fewer duplicate prefetches). Arms gs / cold8 / cold12 / cold13, 3 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD15_DONE logs/chain_cold15.log 2>/dev/null; do sleep 15; done
COMMON="results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt"
OPTS="--fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20"
python3 cold_plan.py $COMMON $DB/plans/cold_plan_v8.json $OPTS --min-lead 200 2>&1 | tee results/trace_gs_lbr/plan_stats_v8.txt | head -2 | cut -c1-200
python3 cold_plan.py $COMMON $DB/plans/cold_plan_v9.json $OPTS --max-sites-per-line 1 2>&1 | tee results/trace_gs_lbr/plan_stats_v9.txt | head -2 | cut -c1-200
build_arm() { local n=$1 p=$2; local env="PREFETCHIT_COLD_PLAN=/dsb/plans/$p PREFETCHIT_COLD_DIRECT_IN_PIC=1"
  echo "[$(date +%T)] deps image dsb-deps-$n"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-$n - > $PL/logs/deps_$n.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_$n.log | tail -1
  echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-$n "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-$n > /dev/null 2>&1
  local f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m3 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; return 1; }
  echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)')"
}
build_arm cold12 cold_plan_v8.json; build_arm cold13 cold_plan_v9.json
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold8=$DB/out_utl_cold8:$L:dsb-deps-g:-:-:64:0:20000:0"
for n in cold12 cold13; do [[ -f $DB/out_utl_$n/UserTimelineService ]] && ARMS="$ARMS $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0"; done
echo "[$(date +%T)] round31 arms: $ARMS"; ./dsb_warm_ab2.sh results/round31 3 $ARMS > logs/round31.log 2>&1
python3 summarize_ab.py results/round31/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD16_DONE"
