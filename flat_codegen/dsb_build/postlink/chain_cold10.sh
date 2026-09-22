#!/usr/bin/env bash
# Round 25: (a) plan v4 without libc/GOT targets (cold8n), (b) the regular sequential-lookahead static mode restricted to the functions
# that miss (seqA + twin) as a mixing candidate. 3 reps each against gs.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD9_DONE logs/chain_cold9.log 2>/dev/null; do sleep 15; done
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v4n.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20 --no-got 2>&1 | tee results/trace_gs_lbr/plan_stats_v4n.txt | head -2 | cut -c1-250
build_arm() { local n=$1 env=$2
  echo "[$(date +%T)] deps image dsb-deps-$n"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-$n - > $PL/logs/deps_$n.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_$n.log | tail -1
  echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-$n "$env" > $PL/logs/build_utl_$n.log 2>&1)
  local f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; return 1; }
  echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
}
build_arm cold8n "PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v4n.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
build_arm seqA "PREFETCHIT_SEQ_DISTANCE=1024 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_FUNCTIONS_FILE=/dsb/plans/cold_funcs_gs.txt"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0"
[[ -f $DB/out_utl_cold8n/UserTimelineService ]] && ARMS="$ARMS cold8n=$DB/out_utl_cold8n:$L:dsb-deps-g:-:-:64:0:20000:0"
f=$DB/out_utl_seqA/UserTimelineService; if [[ -f $f.nop ]]; then mkdir -p $DB/out_utl_seqAnop; cp $f.nop $DB/out_utl_seqAnop/UserTimelineService; ARMS="$ARMS seqA=$DB/out_utl_seqA:$L:dsb-deps-g:-:-:64:0:20000:0 seqA_nop=$DB/out_utl_seqAnop:$L:dsb-deps-g:-:-:64:0:20000:0"; fi
echo "[$(date +%T)] round25 arms: $ARMS"; ./dsb_warm_ab2.sh results/round25 3 $ARMS > logs/round25.log 2>&1
python3 summarize_ab.py results/round25/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD10_DONE"
