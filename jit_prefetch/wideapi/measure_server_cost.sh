#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# Server-side cost quantification at FIXED offered load (unpinned server):
# for each config, fresh server + warm, then 60s fixed 4x8 client load with
# a 40s perf window on the server process. Reports cycles/request and
# cores consumed at equal QPS.
set -e
cd "$(dirname "$0")"
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/wideapi_servercost.csv}
REPS=${2:-3}
echo "config,rep,qps,cycles,insns,l2i_miss,win_s" > "$OUT"

run_one() {
  local cfg=$1 rep=$2; shift 2
  local flags="$*"
  pkill -f 'classes WideApi$' 2>/dev/null || true
  sleep 2
  rm -f /tmp/wideapi.log
  $JDK/bin/java -Xmx8G -Dwideapi.chain=512 $flags -cp classes WideApi > /tmp/wideapi.log 2>&1 &
  local spid=$!
  until grep -q READY /tmp/wideapi.log 2>/dev/null; do sleep 2; done
  python3 load_wideapi.py --procs 4 --threads 8 --duration 15 --tag w > /dev/null 2>&1
  python3 load_wideapi.py --procs 4 --threads 8 --duration 60 --tag m > /tmp/wa_m.log 2>&1 &
  local lpid=$!
  sleep 10
  sudo perf stat -p $spid \
    -e 'cycles,instructions,cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' \
    -o /tmp/wa_sc.txt -- sleep 40 2>/dev/null || true
  wait $lpid || true
  local qps cyc insn miss
  qps=$(grep -oP 'qps \K[\d.]+' /tmp/wa_m.log)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/wa_sc.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/wa_sc.txt | tr -d ,)
  miss=$(grep -oP '[\d,]+(?=\s+L2I_CODE_RD_MISS)' /tmp/wa_sc.txt | tr -d ,)
  kill $spid 2>/dev/null || true; wait $spid 2>/dev/null || true
  echo "$cfg,$rep,$qps,$cyc,$insn,$miss,40" >> "$OUT"
  echo "$cfg r$rep qps=$qps cyc=$cyc"
}

for rep in $(seq 1 $REPS); do
  run_one stock $rep ""
  run_one v4_g256 $rep "-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"
done
pkill -f 'classes WideApi$' 2>/dev/null || true
echo DONE
