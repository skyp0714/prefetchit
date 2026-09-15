#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# L2I MPKI screen of Renaissance benchmarks under the stock jdk17u build.
# Runs each benchmark with enough reps for steady state, samples a perf
# window mid-run on the java process.
set -e
JAR="${REN}"
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/renaissance_screen.csv}
BENCHES=${2:-"dotty finagle-http finagle-chirper akka-uct reactors"}
echo "bench,l2i_miss,insns,cycles,mpki,ipc" > "$OUT"
for b in $BENCHES; do
  echo "== $b"
  $JDK/bin/java -jar $JAR -r 20 "$b" > /tmp/ren_${b}.log 2>&1 &
  JPID=$!
  sleep 45   # skip JIT warmup
  if ! kill -0 $JPID 2>/dev/null; then echo "$b finished too fast"; wait $JPID || true; continue; fi
  sudo perf stat -p $JPID \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles' \
    -o /tmp/ren_perf.txt -- sleep 15 2>/dev/null || true
  kill $JPID 2>/dev/null || true; wait $JPID 2>/dev/null || true
  miss=$(grep -oP '[\d,]+(?=\s+L2I_CODE_RD_MISS)' /tmp/ren_perf.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/ren_perf.txt | tr -d ,)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/ren_perf.txt | tr -d ,)
  python3 - "$b" "$miss" "$insn" "$cyc" >> "$OUT" << 'PY'
import sys
b, miss, insn, cyc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
print(f"{b},{miss},{insn},{cyc},{1000*miss/insn:.2f},{insn/cyc:.3f}")
PY
  tail -1 "$OUT"
done
echo DONE
