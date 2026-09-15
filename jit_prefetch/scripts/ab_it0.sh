#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# it0 test: tomcat + cassandra, stock vs V4-t1-gated vs V4-it0-gated.
# Also captures an L1I-miss window per config (does it0 actually fill L1I?).
set -e
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/it0_ab.csv}
REPS=${2:-5}
GATED="-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"
echo "bench,config,rep,steady_ms,l2i_mpki,l1i_mpki" > "$OUT"

run_one() {
  local bench=$1 cfg=$2 rep=$3; shift 3
  local flags="$*"
  local log=/tmp/it0_${bench}_${cfg}_${rep}.log
  local extra=""
  [[ $bench == cassandra ]] && extra="-Djava.security.manager=allow"
  $JDK/bin/java $extra $flags -jar $DACAPO $bench -n 22 \
    --scratch-directory /tmp/dcscratch_it0 > $log 2>&1 &
  local jpid=$!
  sleep 55
  local l2m=NA l1m=NA
  if kill -0 $jpid 2>/dev/null; then
    sudo perf stat -p $jpid \
      -e 'cpu/event=0x24,umask=0x24,name=L2I_MISS/,cpu/event=0x80,umask=0x84,name=L1I_MISS/,instructions' \
      -o /tmp/it0_perf.txt -- sleep 10 2>/dev/null || true
    local miss l1 insn
    miss=$(grep -oP '[\d,]+(?=\s+L2I_MISS)' /tmp/it0_perf.txt | tr -d ,)
    l1=$(grep -oP '[\d,]+(?=\s+L1I_MISS)' /tmp/it0_perf.txt | tr -d ,)
    insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/it0_perf.txt | tr -d ,)
    l2m=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
    l1m=$(python3 -c "print(f'{1000*$l1/$insn:.2f}')" 2>/dev/null || echo NA)
  fi
  wait $jpid || true
  local mean
  mean=$(grep -oP 'completed warmup \d+ in \K\d+' $log | tail -8 | \
    python3 -c "import sys; v=[int(x) for x in sys.stdin]; print(f'{sum(v)/len(v):.0f}')" 2>/dev/null || echo NA)
  echo "$bench,$cfg,$rep,$mean,$l2m,$l1m" >> "$OUT"
  echo "$bench $cfg r$rep steady=${mean}ms l2i=$l2m l1i=$l1m"
}

for rep in $(seq 1 $REPS); do
  for bench in tomcat cassandra; do
    run_one $bench stock $rep ""
    run_one $bench t1_gated $rep "$GATED"
    run_one $bench it0_gated $rep "$GATED -XX:+PrefetchEntryIT0"
  done
done
echo DONE
