#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# C1 arc grid round 2: LargeBoom callsite variants + MegaBoom peak neighbors.
# Builds injected .ll variants, NOP pairs, then interleaved 5-rep A/B.
# Usage: run_grid_round2.sh <results_csv>
set -e
cd "$(dirname "$0")/.."
OUT=${1:-results/grid_round2.csv}
NOPTOOL=${PREFETCHIT_ROOT}/llvm_prefetchit/tools/make_nop_control_binary.py
INJ=scripts/inject_callsite_prefetch.py

# variant table: name base stride lookahead lines
VARIANTS="
lb_s4la16 lb 4 16 1
lb_s4la8 lb 4 8 1
lb_s8la16 lb 8 16 1
mb_s4la14 mb 4 14 1
mb_s4la18 mb 4 18 1
"

echo "variant,rep,arm,elapsed,mpki" > "$OUT"

build_variant() {
  local name=$1 base=$2 s=$3 la=$4 l=$5
  [[ -x work/${base}_arc_${name#${base}_} ]] && return 0
  python3 $INJ work/${base}.ll work/${name}.ll --stride $s --lookahead $la \
    --lines $l --cache-type 1
  clang-19 -O2 work/${name}.ll work/driver_${base}.c -o work/${base}_arc_${name#${base}_} \
    2> work/build_${name}.err
  python3 $NOPTOOL --input work/${base}_arc_${name#${base}_} \
    --output work/${base}_arc_${name#${base}_}.nop --mnemonics prefetcht1 \
    2>/dev/null | tail -1
}

measure() {
  local name=$1 base=$2 rep=$3 arm=$4 bin=$5
  local el miss insn mpki pcsv=/tmp/grid2_perf_$$.csv
  el=$(sudo /usr/bin/time -f '%e' taskset -c 44 \
    perf stat --no-big-num -x, \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions' \
    -o "$pcsv" -- "$bin" 2>&1 > /dev/null | tail -1)
  miss=$(awk -F, '/L2I_CODE_RD_MISS/{print $1}' "$pcsv")
  insn=$(awk -F, '/instructions/{print $1}' "$pcsv")
  mpki=$(python3 -c "print(f'{1000*$miss/$insn:.1f}')" 2>/dev/null || echo NA)
  echo "$name,$rep,$arm,$el,$mpki" >> "$OUT"
  echo "$name r$rep $arm ${el}s mpki=$mpki"
}

set -- $VARIANTS
while [[ $# -ge 5 ]]; do
  name=$1 base=$2 s=$3 la=$4 l=$5; shift 5
  echo "== build $name"
  build_variant $name $base $s $la $l
done

set -- $VARIANTS
for rep in 1 2 3 4 5; do
  set -- $VARIANTS
  while [[ $# -ge 5 ]]; do
    name=$1 base=$2; shift 5
    bin=work/${base}_arc_${name#${base}_}
    measure $name $base $rep nop ${bin}.nop
    measure $name $base $rep pf ${bin}
  done
done
echo DONE
