#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# finagle-chirper A/B: stock vs V4 entry-burst vs gated V4, interleaved.
# Each run: renaissance -r 30 with --json; steady-state = last 20 iters.
# A mid-run 15s perf window records L2I MPKI.
set -e
JAR="${REN}"
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/chirper_ab.csv}
REPS=${2:-3}
BENCH=finagle-chirper
echo "config,rep,steady_mean_ms,mpki,ipc" > "$OUT"

run_one() {
  local cfg=$1 rep=$2; shift 2
  local flags="$*"
  local json=/tmp/chirper_${cfg}_${rep}.json
  $JDK/bin/java $flags -jar $JAR -r 30 --json $json $BENCH \
    > /tmp/chirper_${cfg}_${rep}.log 2>&1 &
  local jpid=$!
  sleep 60
  if kill -0 $jpid 2>/dev/null; then
    sudo perf stat -p $jpid \
      -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles' \
      -o /tmp/chirper_perf.txt -- sleep 15 2>/dev/null || true
  fi
  wait $jpid || true
  local miss insn cyc mpki ipc mean
  miss=$(grep -oP '[\d,]+(?=\s+L2I_CODE_RD_MISS)' /tmp/chirper_perf.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/chirper_perf.txt | tr -d ,)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/chirper_perf.txt | tr -d ,)
  mean=$(python3 - $json << 'PY'
import json, sys
d = json.load(open(sys.argv[1]))
times = [r['duration_ns'] for r in d['data']['finagle-chirper']['results']][-20:]
print(f"{sum(times)/len(times)/1e6:.1f}")
PY
)
  mpki=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
  ipc=$(python3 -c "print(f'{$insn/$cyc:.3f}')" 2>/dev/null || echo NA)
  echo "$cfg,$rep,$mean,$mpki,$ipc" >> "$OUT"
  echo "$cfg r$rep steady ${mean}ms mpki=$mpki ipc=$ipc"
}

for rep in $(seq 1 $REPS); do
  run_one stock $rep ""
  run_one v4_g512 $rep "-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=16 -XX:PrefetchEntryMinBytecode=512"
  run_one v4_g256_ret $rep "-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256 -XX:+PrefetchRetTarget"
  run_one ret_only $rep "-XX:+PrefetchRetTarget -XX:PrefetchRetTargetLines=2"
done
echo DONE
