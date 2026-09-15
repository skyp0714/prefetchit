#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# DaCapo cassandra A/B: stock vs V4-gated, interleaved reps.
# Metric: mean of last 10 warmup-iteration times (msec) from DaCapo log.
set -e
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/cassandra_ab.csv}
REPS=${2:-5}
echo "config,rep,steady_ms,mpki" > "$OUT"

run_one() {
  local cfg=$1 rep=$2; shift 2
  local flags="$*"
  local log=/tmp/cass_${cfg}_${rep}.log
  $JDK/bin/java -Djava.security.manager=allow $flags -jar $DACAPO cassandra \
    -n 25 --scratch-directory /tmp/dcscratch_ab > $log 2>&1 &
  local jpid=$!
  sleep 60
  local mpki=NA
  if kill -0 $jpid 2>/dev/null; then
    sudo perf stat -p $jpid \
      -e 'cpu/event=0x24,umask=0x24,name=L2I_MISS/,instructions' \
      -o /tmp/cass_perf.txt -- sleep 12 2>/dev/null || true
    local miss insn
    miss=$(grep -oP '[\d,]+(?=\s+L2I_MISS)' /tmp/cass_perf.txt | tr -d ,)
    insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/cass_perf.txt | tr -d ,)
    mpki=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
  fi
  wait $jpid || true
  local mean
  mean=$(grep -oP 'completed warmup \d+ in \K\d+' $log | tail -10 | \
    python3 -c "import sys; v=[int(x) for x in sys.stdin]; print(f'{sum(v)/len(v):.0f}')" 2>/dev/null || echo NA)
  echo "$cfg,$rep,$mean,$mpki" >> "$OUT"
  echo "$cfg r$rep steady=${mean}ms mpki=$mpki"
}

for rep in $(seq 1 $REPS); do
  run_one stock $rep ""
  run_one v4_gated $rep "-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"
done
echo DONE
