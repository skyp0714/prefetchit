#!/usr/bin/env bash
# screen every built SPEC2026 benchmark (ref input, first command line) for L2I MPKI; idempotent (skips screened ones)
set -u
cd /home/hnpark2/prefetchit/benchmarks/spec2026; source shrc
export OUT_DIR=/home/hnpark2/prefetchit/llvm_prefetchit/results/spec2026_20260916; mkdir -p $OUT_DIR
S=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screen_one.sh
for d in benchspec/CPU/[0-9]*; do
  b=$(basename $d); ls $d/exe/*clangbase >/dev/null 2>&1 || continue
  grep -q "^spec2026_${b}," $OUT_DIR/runs.csv 2>/dev/null && continue
  runcpu --config=prefetchit-clang-2026 --size=ref --action=setup --noreportable $b > /tmp/screen_inputs/spec2026_setup_$b.log 2>&1
  rd=$(ls -d $d/run/run_base_refrate_clangbase.0000 $d/run/run_base_refspeed_clangbase.0000 2>/dev/null | head -1); [[ -n "$rd" ]] || { echo "$b: no run dir"; continue; }
  cmd=$(cd $rd && specinvoke -n 2>/dev/null | grep -v '^#' | grep -v '^$' | head -1)
  [[ -n "$cmd" ]] || { echo "$b: no command"; continue; }
  echo "$b: $cmd" | cut -c1-160
  bash $S spec2026_${b} "$rd" "$cmd" 150
done
echo SPEC2026_SCREEN_PASS_DONE
