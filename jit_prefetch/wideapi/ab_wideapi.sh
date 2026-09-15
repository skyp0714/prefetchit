#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# WideApi A/B: stock vs V4 entry-burst configs. Each run: fresh server,
# in-process warmup + 15s load warm, then 60s measured load (QPS + p50)
# with a mid-run perf window (L2I MPKI).
set -e
cd "$(dirname "$0")"
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/wideapi_ab.csv}
REPS=${2:-3}
echo "config,rep,qps,p50_ms,p99_ms,mpki,ipc" > "$OUT"

run_one() {
  local cfg=$1 rep=$2; shift 2
  local flags="$*"
  pkill -f 'classes WideApi$' 2>/dev/null || true
  sleep 2
  rm -f /tmp/wideapi.log
  taskset -c 40-43 $JDK/bin/java -Xmx8G -Dwideapi.chain=512 $flags -cp classes WideApi > /tmp/wideapi.log 2>&1 &
  local spid=$!
  until grep -q READY /tmp/wideapi.log 2>/dev/null; do sleep 2; done
  python3 load_wideapi.py --procs 12 --threads 8 --duration 15 --tag w > /dev/null 2>&1
  python3 load_wideapi.py --procs 12 --threads 8 --duration 60 --tag m > /tmp/wa_m.log 2>&1 &
  local lpid=$!
  sleep 15
  sudo perf stat -p $spid \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles' \
    -o /tmp/wa_perf.txt -- sleep 20 2>/dev/null || true
  wait $lpid || true
  local line qps p50 p99 miss insn cyc mpki ipc
  line=$(cat /tmp/wa_m.log)
  qps=$(echo "$line" | grep -oP 'qps \K[\d.]+')
  p50=$(echo "$line" | grep -oP 'p50 \K[\d.]+')
  p99=$(echo "$line" | grep -oP 'p99 \K[\d.]+')
  miss=$(grep -oP '[\d,]+(?=\s+L2I_CODE_RD_MISS)' /tmp/wa_perf.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/wa_perf.txt | tr -d ,)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/wa_perf.txt | tr -d ,)
  mpki=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
  ipc=$(python3 -c "print(f'{$insn/$cyc:.3f}')" 2>/dev/null || echo NA)
  kill $spid 2>/dev/null || true; wait $spid 2>/dev/null || true
  echo "$cfg,$rep,$qps,$p50,$p99,$mpki,$ipc" >> "$OUT"
  echo "$cfg r$rep qps=$qps p50=${p50}ms mpki=$mpki ipc=$ipc"
}

for rep in $(seq 1 $REPS); do
  run_one stock $rep ""

  run_one v4_g256 $rep "-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"

done
pkill -f 'classes WideApi$' 2>/dev/null || true
echo DONE
