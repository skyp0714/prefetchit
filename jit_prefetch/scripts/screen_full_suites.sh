#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"
# Full L2I screen of unscreened DaCapo + Renaissance benchmarks under the
# stock jdk17u build. Also records L1I misses for the hierarchy check
# (L1I>>L2I => L2-resident => t1-unreachable).
set -e
OUT=${1:-${PREFETCHIT_ROOT}/jit_prefetch/results/full_suite_screen.csv}
echo "suite,bench,l2i_miss,l1i_miss,insns,cycles,l2i_mpki,l1i_mpki,ipc" > "$OUT"

measure_pid() {  # pid outfile
  sudo perf stat -p "$1" \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,cpu/event=0x80,umask=0x04,name=ICACHE_DATA_STALL/,cpu/event=0xc0,umask=0x00,name=INST_RETIRED/,cycles,cpu/event=0x24,umask=0xe4,name=L2_CODE_RD_ALL/' \
    -o "$2" -- sleep 12 2>/dev/null || true
}

screen_one() {  # suite cmdname full-cmd...
  local suite=$1 bench=$2; shift 2
  echo "== $suite $bench"
  "$@" > /tmp/fs_${bench}.log 2>&1 &
  local jpid=$!
  sleep 40
  if ! kill -0 $jpid 2>/dev/null; then echo "  (finished before window)"; wait $jpid || true; return; fi
  sudo perf stat -p $jpid \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_MISS/,cpu/frontend_retired.l1i_miss,name=L1I_MISS/,instructions,cycles' \
    -o /tmp/fs_perf.txt -- sleep 12 2>/dev/null || \
  sudo perf stat -p $jpid \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_MISS/,cpu/event=0x80,umask=0x84,name=L1I_MISS/,instructions,cycles' \
    -o /tmp/fs_perf.txt -- sleep 12 2>/dev/null || true
  kill $jpid 2>/dev/null || true; wait $jpid 2>/dev/null || true
  local l2 l1 insn cyc
  l2=$(grep -oP '[\d,]+(?=\s+L2I_MISS)' /tmp/fs_perf.txt | tr -d ,)
  l1=$(grep -oP '[\d,]+(?=\s+L1I_MISS)' /tmp/fs_perf.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/fs_perf.txt | tr -d ,)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/fs_perf.txt | tr -d ,)
  python3 - "$suite" "$bench" "$l2" "${l1:-0}" "$insn" "$cyc" >> "$OUT" << 'PY'
import sys
s,b = sys.argv[1], sys.argv[2]
l2,l1,insn,cyc = (int(x) for x in sys.argv[3:7])
print(f"{s},{b},{l2},{l1},{insn},{cyc},{1000*l2/insn:.2f},{1000*l1/insn:.2f},{insn/cyc:.3f}")
PY
  tail -1 "$OUT"
}

JD="$JDK/bin/java -jar"
for b in eclipse xalan fop batik sunflow zxing graphchi cassandra kafka; do
  screen_one dacapo $b $JDK/bin/java -jar $DACAPO $b -n 20 --scratch-directory /tmp/dcscratch_$b
done
for b in neo4j-analytics db-shootout scala-stm-bench7 movie-lens page-rank als dec-tree log-regression naive-bayes chi-square gauss-mix fj-kmeans scrabble rx-scrabble future-genetic philosophers scala-doku mnemonics par-mnemonics scala-kmeans; do
  screen_one renaissance $b $JDK/bin/java -jar $REN -r 40 $b
done
echo DONE
