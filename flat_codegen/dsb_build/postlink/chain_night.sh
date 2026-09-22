#!/usr/bin/env bash
# Overnight chain: wait for round1 -> round2 (in-place PLT, eager binding) -> Verilator post-link cost check -> fat-static builds.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; cd $PL
until grep -q AB_DONE logs/round1.log; do sleep 10; done
echo "[$(date +%T)] round2 start"
./dsb_postlink_ab2.sh results/round2 3 base=arms/base pli_svc=arms/pli_svc pli_svc_nop=arms/pli_svc_nop pli_all=arms/pli_all pli_all_nop=arms/pli_all_nop > logs/round2.log 2>&1
echo "[$(date +%T)] round2 done; verilator post-link measure start"
cd /home/hnpark2/prefetchit/llvm_prefetchit && BASELINE_BINARY=/home/hnpark2/prefetchit/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig CONFIG=DualMegaBoomAndSingleRocketConfig BINS=$PWD/results/static_overhaul_20260916/postlink VARIANTS="pl_b4 pl_b4_nop pl_b4plt pl_b4plt_nop pl_b4r2 pl_b4r2_nop" REPS=3 MAX_CYCLES=100000 CORE=44 OUT_CSV=$PWD/results/static_overhaul_20260916/postlink/measure_qsort/runs.csv scripts/static/measure_verilator_variants.sh > $PL/logs/verilator_postlink.log 2>&1
echo "[$(date +%T)] verilator done; deps rebuild (clang-19 base) start"
cd /home/hnpark2/prefetchit/flat_codegen/dsb_build && bash rebuild_deps_env.sh dsb-deps-g - > $PL/logs/deps_g.log 2>&1
bash build_utl_variant.sh g dsb-deps-g "" > $PL/logs/build_utl_g.log 2>&1
echo "[$(date +%T)] base rebuild done; burst rebuild start"
EXTRA_PASS_ENV="PREFETCHIT_CALLEE_BURST_LINES=3" bash rebuild_deps_env.sh dsb-deps-b3 - > $PL/logs/deps_b3.log 2>&1
bash build_utl_variant.sh b3 dsb-deps-b3 "PREFETCHIT_CALLEE_BURST_LINES=3" > $PL/logs/build_utl_b3.log 2>&1
echo "[$(date +%T)] CHAIN_DONE"
