#!/usr/bin/env bash
# PEBS+LBR L2I-miss trace of PostgreSQL backends under pgbench load (server cores only), then symbolize + miss-stream diagnosis.
set -euo pipefail
LABEL="${1:-pg_base}"; MODE="${MODE:-tpcb}"
PGBIN="${PGBIN:-/home/hnpark2/prefetchit/benchmarks/pg/install_base/bin}"; BIN="$PGBIN/postgres"
SCALE="${SCALE:-100}"; DATA="${DATA:-/home/hnpark2/prefetchit/benchmarks/pg/data_scale${SCALE}}"
PORT="${PORT:-55700}"; CLIENTS="${CLIENTS:-8}"; DUR="${DUR:-40}"
SERVER_CORES="${SERVER_CORES:-50-57}"; CLIENT_CORES="${CLIENT_CORES:-60-67}"
OUT="${OUT:-/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/pg_trace_${LABEL}_${MODE}}"; TD="$OUT/l2_miss"; mkdir -p "$TD"
cd /home/hnpark2/prefetchit
taskset -c "$SERVER_CORES" "$PGBIN/pg_ctl" -D "$DATA" -o "-p $PORT -k /tmp" -l "$OUT/server.log" start > /dev/null; sleep 3
opt=""; [[ "$MODE" == select ]] && opt="-S"
taskset -c "$CLIENT_CORES" "$PGBIN/pgbench" -h /tmp -p "$PORT" -c "$CLIENTS" -j "$CLIENTS" -T 10 -M prepared $opt bench > "$OUT/warmup.log" 2>&1
taskset -c "$CLIENT_CORES" "$PGBIN/pgbench" -h /tmp -p "$PORT" -c "$CLIENTS" -j "$CLIENTS" -T $((DUR + 10)) -M prepared $opt bench > "$OUT/pgbench.log" 2>&1 &
sleep 3
perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 20000 -o "$TD/l2miss_profile.data" -a -C "$SERVER_CORES" -- sleep "$DUR" > "$TD/record.log" 2>&1 || true
wait
"$PGBIN/pg_ctl" -D "$DATA" stop -m fast > /dev/null
bash profiling/analyze_pebs_trace.sh --data "$TD/l2miss_profile.data" --out-dir "$TD" --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary "$BIN" > "$TD/analyze.log" 2>&1 || true
echo "samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' "$TD/trace_summary.md" 2>/dev/null)"
grep -E "Top miss target function|Top branch type" "$TD/trace_summary.md" 2>/dev/null
head -20 "$TD/branch_type_distribution.csv" 2>/dev/null
python3 static_prefetch/tools/ret/miss_stream_characterization.py --binary "$BIN" --trace-dir "$TD" --out-dir "$OUT/diag" 2>&1 | grep -E "^\{'type'|cumulative|load base" | cut -c1-220
