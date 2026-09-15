#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# Collect an L2I-code-miss LBR trace of PostStorageService under load and
# produce the planner-format dumps (lbr_raw/lbr_symbolic).
# Usage: collect_l2i_trace.sh <outdir> [duration_sec=60] [period=101]
set -e
cd "$(dirname "$0")"
OUT=$1; DUR=${2:-60}; PERIOD=${3:-5003}
mkdir -p "$OUT"

# load in background for trace duration + margin
python3 dsb_load2.py --procs 4 --threads 16 --duration $((DUR + 30)) \
  --tag trace_load > "$OUT/load.log" 2>&1 &
LOADPID=$!
sleep 10
PID=$(pgrep -f '^/custom/PostStorageService' | head -1)
echo "tracing pid $PID for ${DUR}s period ${PERIOD}"
sudo perf record \
  -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' \
  -b -c "$PERIOD" -p "$PID" -o "$OUT/l2miss_profile.data" -- sleep "$DUR"
sudo chmod a+r "$OUT/l2miss_profile.data"
wait $LOADPID || true
sudo perf script -i "$OUT/l2miss_profile.data" \
  -F ip,sym,brstack,weight \
  > "$OUT/lbr_raw_dump.txt" 2> "$OUT/perf_script_raw.err" || \
  sudo perf script -i "$OUT/l2miss_profile.data" \
  -F ip,sym,brstack > "$OUT/lbr_raw_dump.txt"
sudo perf script -i "$OUT/l2miss_profile.data" \
  -F ip,sym,brstacksym,weight \
  > "$OUT/lbr_symbolic_dump.txt" 2> "$OUT/perf_script_sym.err" || \
  sudo perf script -i "$OUT/l2miss_profile.data" \
  -F ip,sym,brstacksym > "$OUT/lbr_symbolic_dump.txt"
wc -l "$OUT/lbr_symbolic_dump.txt" "$OUT/lbr_raw_dump.txt"
tail -1 "$OUT/load.log"
