#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# C1 arc grid round 3: DMB s4la16, mb stride variants at la16, +64 base
# offset variant. Includes the known winner mb_s4la16 (old binary) as the
# in-session reference cell. 5-rep interleaved NOP-pair A/B on core 44.
set -e
cd "$(dirname "$0")/.."
OUT=${1:-results/grid_round3.csv}
NOPTOOL=${PREFETCHIT_ROOT}/llvm_prefetchit/tools/make_nop_control_binary.py
INJ=scripts/inject_callsite_prefetch.py

# name base stride lookahead lines base_offset
VARIANTS="
dmb_s4la16 dmb 4 16 1 0
mb_s3la16 mb 3 16 1 0
mb_s5la16 mb 5 16 1 0
mb_s4la16o64 mb 4 16 1 64
"

echo "variant,rep,arm,elapsed,mpki" > "$OUT"

build_variant() {
  local name=$1 base=$2 s=$3 la=$4 l=$5 bo=$6
  local bin=work/${base}_arc_${name#${base}_}
  [[ -x $bin && -x $bin.nop ]] && return 0
  python3 $INJ work/${base}.ll work/${name}.ll --stride $s --lookahead $la \
    --lines $l --cache-type 1 --base-offset $bo
  clang-19 -O2 work/${name}.ll work/driver_${base}.c -o $bin 2> work/build_${name}.err
  python3 $NOPTOOL --input $bin --output $bin.nop --mnemonics prefetcht1 \
    2>/dev/null | tail -1
}

measure() {
  local name=$1 rep=$2 arm=$3 bin=$4
  local el pcsv=/tmp/grid3_perf.csv
  el=$(sudo /usr/bin/time -f '%e' taskset -c 44 \
    perf stat --no-big-num -x, \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions' \
    -o "$pcsv" -- "$bin" 2>&1 > /dev/null | tail -1)
  local miss insn mpki
  miss=$(awk -F, '/L2I_CODE_RD_MISS/{print $1}' "$pcsv")
  insn=$(awk -F, '/instructions/{print $1}' "$pcsv")
  mpki=$(python3 -c "print(f'{1000*$miss/$insn:.1f}')" 2>/dev/null || echo NA)
  echo "$name,$rep,$arm,$el,$mpki" >> "$OUT"
  echo "$name r$rep $arm ${el}s mpki=$mpki"
}

sudo true   # cache credentials for sudo -n

set -- $VARIANTS
while [[ $# -ge 6 ]]; do
  name=$1 base=$2 s=$3 la=$4 l=$5 bo=$6; shift 6
  echo "== build $name"
  build_variant $name $base $s $la $l $bo
done

for rep in 1 2 3 4 5; do
  # reference cell: the standing winner
  measure mb_s4la16ref $rep nop work/mb_arc_s4la16.nop
  measure mb_s4la16ref $rep pf work/mb_arc_s4la16
  set -- $VARIANTS
  while [[ $# -ge 6 ]]; do
    name=$1 base=$2; shift 6
    bin=work/${base}_arc_${name#${base}_}
    measure $name $rep nop ${bin}.nop
    measure $name $rep pf ${bin}
  done
done
echo DONE
