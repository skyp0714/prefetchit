#!/usr/bin/env bash
# Overnight chain v2: round2 (running) -> LBR trace -> round3 (post-link seq stubs) -> Verilator stub-cost check
#   -> clang-19 userland rebuilds (base / callee-burst / seq) -> round4 (rebuilt arms)
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q AB_DONE logs/round2.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] round2 done; trace"
./dsb_utl_trace.sh results/trace_utl 40 2003 > logs/trace.log 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); echo ps101899 | sudo -S cat /proc/$pid/maps > results/trace_utl/maps.txt 2>/dev/null
python3 lbr_sites.py results/trace_utl/lbr_raw.txt results/trace_utl/maps.txt > results/trace_utl/sites.txt 2>&1
echo "[$(date +%T)] round3 start"
./dsb_postlink_ab2.sh results/round3 3 base=arms/base seq2k=arms/seq2k seq2k_nop=arms/seq2k_nop > logs/round3.log 2>&1
echo "[$(date +%T)] round3 done; verilator post-link measure start"
cd /home/hnpark2/prefetchit/llvm_prefetchit && BASELINE_BINARY=/home/hnpark2/prefetchit/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig CONFIG=DualMegaBoomAndSingleRocketConfig BINS=$PWD/results/static_overhaul_20260916/postlink VARIANTS="pl_b4 pl_b4_nop pl_b4plt pl_b4plt_nop pl_b4r2 pl_b4r2_nop" REPS=3 MAX_CYCLES=100000 CORE=44 OUT_CSV=$PWD/results/static_overhaul_20260916/postlink/measure_qsort/runs.csv scripts/static/measure_verilator_variants.sh > $PL/logs/verilator_postlink.log 2>&1
echo "[$(date +%T)] verilator done; deps rebuilds start"
cd $DB
bash rebuild_deps_env.sh dsb-deps-g - > $PL/logs/deps_g.log 2>&1; bash build_utl_variant.sh g dsb-deps-g "" > $PL/logs/build_utl_g.log 2>&1
echo "[$(date +%T)] g done"
EXTRA_PASS_ENV="PREFETCHIT_CALLEE_BURST_LINES=3" bash rebuild_deps_env.sh dsb-deps-b3 - > $PL/logs/deps_b3.log 2>&1; bash build_utl_variant.sh b3 dsb-deps-b3 "PREFETCHIT_CALLEE_BURST_LINES=3" > $PL/logs/build_utl_b3.log 2>&1
echo "[$(date +%T)] b3 done"
EXTRA_PASS_ENV="PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=3" bash rebuild_deps_env.sh dsb-deps-seq - > $PL/logs/deps_seq.log 2>&1; bash build_utl_variant.sh seq dsb-deps-seq "PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=3" > $PL/logs/build_utl_seq.log 2>&1
echo "[$(date +%T)] seq done; round4"
cd $PL; ARMS="g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g"
for v in b3 seq; do if [[ -f $DB/out_utl_$v/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_${v}nop; cp $DB/out_utl_$v/UserTimelineService.nop $DB/out_utl_${v}nop/UserTimelineService; ARMS="$ARMS $v=$DB/out_utl_$v:$DB/libs_utl_$v:dsb-deps-$v ${v}_nop=$DB/out_utl_${v}nop:$DB/libs_utl_${v}nop:dsb-deps-$v"; fi; done
echo "round4 arms: $ARMS"
./dsb_g_ab.sh results/round4 3 $ARMS > logs/round4.log 2>&1
echo "[$(date +%T)] CHAIN2_DONE"
