#!/usr/bin/env bash
# After the Router A/B: measure the Verilator prefetchit arms (built by build_verilator_variant.sh) against base and the prefetcht1 arm.
R=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; L=/home/hnpark2/prefetchit/llvm_prefetchit; O=$L/results/static_overhaul_20260916
until grep -q AB_DONE /home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink/logs/round16.log 2>/dev/null; do sleep 20; done
until [[ -f $O/bin/simulator-DualMegaBoomAndSingleRocketConfig-seq_d4096_k20_b4_auto_it1_nop && -f $O/bin/simulator-DualMegaBoomAndSingleRocketConfig-seq_d4096_k20_b4_auto_it0_nop ]]; do sleep 30; done
V="seq_d4096_k20_b4_auto seq_d4096_k20_b4_auto_it1 seq_d4096_k20_b4_auto_it1_nop seq_d4096_k20_b4_auto_it0 seq_d4096_k20_b4_auto_it0_nop"
echo "[$(date +%T)] verilator prefetchit measure"
cd $L && BASELINE_BINARY=/home/hnpark2/prefetchit/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig CONFIG=DualMegaBoomAndSingleRocketConfig BINS=$O/bin VARIANTS="$V" REPS=3 MAX_CYCLES=100000 CORE=35 OUT_CSV=$O/measure_prefetchit/runs.csv scripts/static/measure_verilator_variants.sh > $R/verilator_it.log 2>&1
grep -A8 "| variant" $R/verilator_it.log | head -10; echo "[$(date +%T)] VERILATOR_IT_DONE"
