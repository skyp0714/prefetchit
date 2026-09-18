#!/usr/bin/env bash
# Lean round 20: traces of cold3_nop (baseline misses in the prefetch layout → function list + target analysis) and cold3 (residual misses),
# trace-guided cold4 (functions covering 90% of exe misses), measurement gs / cold4 / cold4_nop × 2 reps, then the target analysis.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
echo "[$(date +%T)] trace cold3_nop"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold3nop $DB/libs_utl_g dsb-deps-g results/trace_cold3nop 0.9 2>&1 | tail -3
echo "[$(date +%T)] trace cold3"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_cold3 $DB/libs_utl_g dsb-deps-g results/trace_cold3 0.9 2>&1 | tail -3
cp results/trace_cold3nop/funcs.txt $DB/plans/cold_funcs_gs.txt || exit 1; echo "functions listed: $(wc -l < $DB/plans/cold_funcs_gs.txt)"
COLD="PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24 PREFETCHIT_COLD_DIRECT_SYMS=/dsb/plans/cold_direct_syms.txt PREFETCHIT_SEQ_FUNCTIONS_FILE=/dsb/plans/cold_funcs_gs.txt"
echo "[$(date +%T)] cold4 build"; (cd $DB && rm -rf out_utl_cold4 libs_utl_cold4 libs_utl_cold4nop; FATSTATIC=1 bash build_utl_variant.sh cold4 dsb-deps-cold3 "$COLD" > $PL/logs/build_utl_cold4.log 2>&1)
grep -h "prefetchit-cold:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | tail -1 | cut -c1-200
f=$DB/out_utl_cold4/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED cold4"; grep -m3 -E "error|Error" $PL/logs/build_utl_cold4.log | cut -c1-200; }
echo "cold4: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0"
if [[ -f $f.nop ]]; then mkdir -p $DB/out_utl_cold4nop; cp $f.nop $DB/out_utl_cold4nop/UserTimelineService
  ARMS="$ARMS cold4=$DB/out_utl_cold4:$L:dsb-deps-g:-:-:64:0:20000:0 cold4_nop=$DB/out_utl_cold4nop:$L:dsb-deps-g:-:-:64:0:20000:0"; fi
echo "[$(date +%T)] round20 arms: $ARMS"; ./dsb_warm_ab2.sh results/round20 2 $ARMS > logs/round20.log 2>&1
python3 summarize_ab.py results/round20/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] target analysis"; python3 cold_target_analysis.py $DB/out_utl_cold3/UserTimelineService results/trace_cold3nop results/trace_cold3 > results/target_analysis_cold3.txt 2>&1; cat results/target_analysis_cold3.txt
echo "[$(date +%T)] CHAIN_COLD4_DONE" | tee -a logs/chain_cold4.log
