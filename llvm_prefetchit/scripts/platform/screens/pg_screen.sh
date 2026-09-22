#!/usr/bin/env bash
# PostgreSQL server-side L2I MPKI screen: server pinned to SERVER_CORES, pgbench (TPC-B-like or select-only) on CLIENT_CORES,
# perf stat system-wide on the server cores during the steady-state window.
#   PGBIN=.../install_base/bin SCALE=100 CLIENTS=8 DURATION=60 MODE=tpcb|select ./pg_screen.sh LABEL
set -euo pipefail
LABEL="${1:-pg_base}"
PGBIN="${PGBIN:-/home/hnpark2/prefetchit/benchmarks/pg/install_base/bin}"
DATA="${DATA:-/home/hnpark2/prefetchit/benchmarks/pg/data_scale${SCALE:-100}}"
PORT="${PORT:-55700}"; SCALE="${SCALE:-100}"; CLIENTS="${CLIENTS:-8}"; DURATION="${DURATION:-60}"; MODE="${MODE:-tpcb}"
SERVER_CORES="${SERVER_CORES:-40-47}"; CLIENT_CORES="${CLIENT_CORES:-60-67}"
OUT="${OUT:-/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/pg_${LABEL}}"; mkdir -p "$OUT"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
if [[ ! -d "$DATA" ]]; then
  "$PGBIN/initdb" -D "$DATA" > "$OUT/initdb.log" 2>&1
  cat >> "$DATA/postgresql.conf" <<C
shared_buffers = 4GB
max_connections = 64
fsync = off
synchronous_commit = off
full_page_writes = off
checkpoint_timeout = 30min
max_wal_size = 8GB
autovacuum = off
C
fi
taskset -c "$SERVER_CORES" "$PGBIN/pg_ctl" -D "$DATA" -o "-p $PORT -k /tmp" -l "$OUT/server.log" start > /dev/null
sleep 3
"$PGBIN/psql" -h /tmp -p "$PORT" -d postgres -tc "select 1 from pg_database where datname='bench'" | grep -q 1 || {
  "$PGBIN/createdb" -h /tmp -p "$PORT" bench; taskset -c "$CLIENT_CORES" "$PGBIN/pgbench" -h /tmp -p "$PORT" -i -s "$SCALE" bench > "$OUT/init.log" 2>&1; }
opt=""; [[ "$MODE" == select ]] && opt="-S"
# warm-up
taskset -c "$CLIENT_CORES" "$PGBIN/pgbench" -h /tmp -p "$PORT" -c "$CLIENTS" -j "$CLIENTS" -T 15 -M prepared $opt bench > "$OUT/warmup.log" 2>&1
# measured window: perf stat on the server cores only (client cores excluded), pgbench in parallel
perf stat -x, -o "$OUT/perf.csv" -e instructions,cycles,"$EVENT" -a -C "$SERVER_CORES" -- \
  taskset -c "$CLIENT_CORES" "$PGBIN/pgbench" -h /tmp -p "$PORT" -c "$CLIENTS" -j "$CLIENTS" -T "$DURATION" -M prepared $opt bench > "$OUT/pgbench.log" 2>&1
"$PGBIN/pg_ctl" -D "$DATA" stop -m fast > /dev/null
python3 - "$OUT/perf.csv" "$OUT/pgbench.log" "$LABEL" "$MODE" <<'PY'
import csv, re, sys
perf, log, label, mode = sys.argv[1:]
ev = {}
for row in csv.reader(open(perf)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins, cyc, miss = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
tps = re.search(r"tps = ([0-9.]+)", open(log).read())
print(f"{label} ({mode}): tps={tps.group(1) if tps else 'n/a'} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G (server cores)")
PY
