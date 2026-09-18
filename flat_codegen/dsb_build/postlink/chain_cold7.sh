#!/usr/bin/env bash
# Round 22: plan v2 (fallback attribution, own line 0 dropped) with and without libc/GOT targets.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD6_DONE logs/chain_cold6.log 2>/dev/null; do sleep 15; done
build_arm() { # name plan.json
  local n=$1 p=$2; local env="PREFETCHIT_COLD_PLAN=/dsb/plans/$p PREFETCHIT_COLD_DIRECT_IN_PIC=1"
  echo "[$(date +%T)] deps image dsb-deps-$n"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-$n - > $PL/logs/deps_$n.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_$n.log | tail -1
  echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-$n "$env" > $PL/logs/build_utl_$n.log 2>&1)
  local f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; return 1; }
  echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
}
build_arm cold6 cold_plan_v2.json; build_arm cold6n cold_plan_v2n.json
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0"
f=$DB/out_utl_cold6/UserTimelineService; if [[ -f $f.nop ]]; then mkdir -p $DB/out_utl_cold6nop; cp $f.nop $DB/out_utl_cold6nop/UserTimelineService; ARMS="$ARMS cold6=$DB/out_utl_cold6:$L:dsb-deps-g:-:-:64:0:20000:0 cold6_nop=$DB/out_utl_cold6nop:$L:dsb-deps-g:-:-:64:0:20000:0"; fi
[[ -f $DB/out_utl_cold6n/UserTimelineService ]] && ARMS="$ARMS cold6n=$DB/out_utl_cold6n:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round22 arms: $ARMS"; ./dsb_warm_ab2.sh results/round22 3 $ARMS > logs/round22.log 2>&1
python3 summarize_ab.py results/round22/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] traces cold6 twin + cold6"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold6nop $L dsb-deps-g results/trace_cold6nop 0.9 2>&1 | tail -1; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold6 $L dsb-deps-g results/trace_cold6 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_cold6nop results/trace_cold6 > results/target_analysis_cold6.txt 2>&1; head -14 results/target_analysis_cold6.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD7_DONE"
