#!/usr/bin/env bash
# Round 23: plan v3 = v2 + sites in the GOT-form libraries (hiredis/mongoc/bson/redis++), 3 reps, then twin/prefetch traces + analysis.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD7_DONE logs/chain_cold7.log 2>/dev/null; do sleep 15; done
n=cold7; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v3.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-plan3"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan3 - > $PL/logs/deps_plan3.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan3.log | tail -1
grep -h "prefetchit-cold-plan:" $DB/dep_make_mongo-c-driver-1.15.0.log 2>/dev/null | awk '{for(i=1;i<=NF;i++){split($i,a,"="); if(a[1]=="sites")s+=a[2]; if(a[1]=="got")g+=a[2]}} END{print "mongoc plan: sites="s" got="g}'
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan3 "$env" > $PL/logs/build_utl_$n.log 2>&1)
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD8_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round23 arms: $ARMS"; ./dsb_warm_ab2.sh results/round23 3 $ARMS > logs/round23.log 2>&1
python3 summarize_ab.py results/round23/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] traces"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_${n}nop $L dsb-deps-g results/trace_${n}nop 0.9 2>&1 | tail -1; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_$n $L dsb-deps-g results/trace_$n 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_${n}nop results/trace_$n > results/target_analysis_$n.txt 2>&1; head -14 results/target_analysis_$n.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD8_DONE"
