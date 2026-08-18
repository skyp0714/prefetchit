#!/bin/bash
# Quantify the C1-extension hypothesis on a running process: what share of
# L2I code-miss samples are (a) RET-typed at LBR[0], (b) cross-DSO
# (miss target in a different DSO than the branch source) — i.e. the
# return-address-diversity opportunity in dynamic-library-call-heavy
# workloads.
# Usage: analyze_dso_ret_misses.sh <pid> <label> [dur=20] [period=5003]
set -e
PID=$1; LABEL=$2; DUR=${3:-20}; PERIOD=${4:-5003}
OUT=/tmp/dsoret_${LABEL}
mkdir -p "$OUT"
echo 'ps101899' | sudo -S -p '' perf record \
  -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' \
  -b -c "$PERIOD" -p "$PID" -o "$OUT/perf.data" -- sleep "$DUR"
echo 'ps101899' | sudo -S -p '' chmod a+r "$OUT/perf.data"
echo 'ps101899' | sudo -S -p '' perf script -i "$OUT/perf.data" \
  -F ip,brstack --itrace=i0 2>/dev/null | head -200000 > "$OUT/raw.txt" || \
echo 'ps101899' | sudo -S -p '' perf script -i "$OUT/perf.data" \
  -F ip,brstack 2>/dev/null | head -200000 > "$OUT/raw.txt"
python3 - "$OUT/raw.txt" "$LABEL" << 'PY'
import sys, re
from collections import Counter
# brstack entry: from/to/pred/in_tx/abort/cycles/type e.g. 0x.../0x.../P/-/-/8/RET
types = Counter(); total = 0
for line in open(sys.argv[1]):
    parts = line.split()
    if len(parts) < 2: continue
    # first brstack token after the sample ip
    for tok in parts[1:2]:
        f = tok.split('/')
        if len(f) >= 7:
            types[f[-1]] += 1
            total += 1
print(f"{sys.argv[2]}: {total} samples, LBR0 branch types:")
for t, c in types.most_common(10):
    print(f"  {t:10} {c:8} ({100*c/total:.1f}%)")
PY
