#!/usr/bin/env bash
# ARM core-benchmarks "frontend" synthetic generators: build two benchmarks whose code footprint is a few multiples of the 2 MB L2:
#   ipc3000 = inst_pointer_chase, 3000 chains x depth 20 = 60k one-line functions called in random order (~4 MB of code)
#   dfs16   = dfs_chase, full binary call tree of depth 16 = 131k functions, one random root->leaf path per iteration (~8 MB)
# Also a prefetch-enabled twin of each (the generator's own --insert_code_prefetches) for reference.
F=/home/hnpark2/prefetchit/benchmarks/core-benchmarks/frontend; R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921
export PYTHONPATH=$F/src; cd $F
gen() { local name=$1 kind=$2; shift 2
  echo "[$(date +%T)] generate $name"; timeout 1800 taskset -c 12-35 python3 -m frontend.cfg_generator.generate_benchmark $kind "$@" /tmp/cb_$name.pb > /dev/null 2>&1 || { echo "  gen failed"; return 1; }
  rm -rf $F/out_$name; mkdir -p $F/out_$name; timeout 1800 taskset -c 12-35 python3 -m frontend.code_generator.driver --num-files=24 /tmp/cb_$name.pb $F/out_$name > /dev/null 2>&1 || { echo "  codegen failed"; return 1; }
  echo "[$(date +%T)] compile $name ($(du -sh $F/out_$name | cut -f1) of C)"; (cd $F/out_$name && timeout 3600 taskset -c 12-35 make -j12 > $R/logs/make_$name.log 2>&1); echo "  make rc=$?"
  ls -la $F/out_$name/benchmark 2>/dev/null | awk '{print "  binary bytes",$5}'; size $F/out_$name/benchmark 2>/dev/null | tail -1 | awk '{printf "  .text %.1f MB\n",$1/1048576}' 
  rm -f /tmp/cb_$name.pb; }
gen ipc3000 inst_pointer_chase_gen --depth=20 --num_callchains=3000
gen dfs16 dfs_chase_gen --depth=16
echo "[$(date +%T)] ARMFE_BUILD_DONE"
