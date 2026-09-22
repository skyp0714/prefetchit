#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# cassandra 4-arm combo A/B under current cache config: stock / v4 /
# v4+v2(call-target) / v4+v2+v1(ret-target). Body-level coverage attack.
set -e
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/cassandra_combo.csv}
REPS=${2:-3}
echo "config,rep,steady_ms,mpki" > "$OUT"
run_one() {
  local cfg=$1 rep=$2; shift 2
  local flags="$*"
  local log=/tmp/casscombo_${cfg}_${rep}.log
  taskset -c 8-15 $JDK/bin/java -Djava.security.manager=allow $flags -jar $DACAPO cassandra \
    -n 25 --scratch-directory /tmp/dcscratch_combo > $log 2>&1 &
  local jpid=$!
  sleep 60
  local mpki=NA
  if kill -0 $jpid 2>/dev/null; then
    local realpid
    realpid=$(pgrep -P $jpid -f java | head -1); realpid=${realpid:-$jpid}
    sudo perf stat -p $realpid \
      -e 'cpu/event=0x24,umask=0x24,name=L2I_MISS/,instructions' \
      -o /tmp/casscombo_perf.txt -- sleep 12 2>/dev/null || true
    local miss insn
    miss=$(grep -oP '[\d,]+(?=\s+L2I_MISS)' /tmp/casscombo_perf.txt | tr -d ,)
    insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/casscombo_perf.txt | tr -d ,)
    mpki=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
  fi
  wait $jpid || true
  local mean
  mean=$(grep -oP 'completed warmup \d+ in \K\d+' $log | tail -10 | \
    python3 -c "import sys; v=[int(x) for x in sys.stdin]; print(f'{sum(v)/len(v):.0f}')" 2>/dev/null || echo NA)
  echo "$cfg,$rep,$mean,$mpki" >> "$OUT"
  echo "$cfg r$rep steady=${mean}ms mpki=$mpki"
}
V4="-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"
V2="-XX:+PrefetchCallTarget"
V1="-XX:+PrefetchRetTarget -XX:PrefetchRetTargetLines=2"
for rep in $(seq 1 $REPS); do
  run_one stock $rep ""
  run_one v4 $rep "$V4"
  run_one v4v2 $rep "$V4 $V2"
  run_one v4v2v1 $rep "$V4 $V2 $V1"
done
echo COMBO_DONE
