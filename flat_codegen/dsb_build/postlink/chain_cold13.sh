#!/usr/bin/env bash
# Round 28: the regular sequential-lookahead static mode restricted to the functions that miss (seqa + twin), as a mixing candidate.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD12_DONE logs/chain_cold12.log 2>/dev/null; do sleep 15; done
n=seqa; env="PREFETCHIT_SEQ_DISTANCE=1024 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_FUNCTIONS_FILE=/dsb/plans/cold_funcs_gs.txt"
echo "[$(date +%T)] deps image dsb-deps-$n"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-$n - > $PL/logs/deps_$n.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_$n.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-$n "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-$n > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; tail -3 $PL/logs/build_utl_$n.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD13_DONE"; exit 1; }
echo "$n: prefetches=$(objdump -d $f | grep -c 'prefetcht1') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round28 arms: $ARMS"; ./dsb_warm_ab2.sh results/round28 3 $ARMS > logs/round28.log 2>&1
python3 summarize_ab.py results/round28/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] CHAIN_COLD13_DONE"
