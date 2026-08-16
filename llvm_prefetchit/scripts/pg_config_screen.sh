#!/usr/bin/env bash
# Screen PostgreSQL configs for frontend-boundness: base binary only, one
# short pgbench run per config, MPKI/IPC on the server cores.
# Configs axis: clients x query-mode x builtin script (tpcb vs select-only).
set -uo pipefail

ROOT=/home/hnpark2/prefetchit
LLVM="${ROOT}/llvm_prefetchit"
PREFIX="${PREFIX:-${LLVM}/work/datacenter_goal_20260708/postgres/install_base}"
PG_CTL="${PREFIX}/bin/pg_ctl"
PGBENCH="${PREFIX}/bin/pgbench"
INITDB="${PREFIX}/bin/initdb"
OUT="${OUT:?set OUT}"
PORT="${PORT:-55655}"
DURATION="${DURATION:-30}"
WARMUP="${WARMUP:-10}"
SCALE="${SCALE:-100}"
SERVER_CORES="${SERVER_CORES:-1-30}"
CLIENT_CORES="${CLIENT_CORES:-31-70}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'

mkdir -p "${OUT}"
DATA="${OUT}/pgdata"
SOCK="${OUT}/sock"
mkdir -p "${SOCK}"
CSV="${OUT}/screen.csv"
[[ -s "${CSV}" ]] || echo 'config,tps,instructions,cycles,l2i_misses,l2i_mpki,ipc' > "${CSV}"

if [[ ! -d "${DATA}" ]]; then
  "${INITDB}" -D "${DATA}" -A trust > "${OUT}/initdb.log" 2>&1
  {
    echo "unix_socket_directories = '${SOCK}'"
    echo "listen_addresses = ''"
    echo "port = ${PORT}"
    echo "shared_buffers = 4GB"
    echo "max_connections = 200"
  } >> "${DATA}/postgresql.conf"
fi

taskset -c "${SERVER_CORES}" "${PG_CTL}" -D "${DATA}" -l "${OUT}/server.log" start
sleep 3
"${PREFIX}/bin/createdb" -h "${SOCK}" -p "${PORT}" pgscreen 2>/dev/null
"${PGBENCH}" -h "${SOCK}" -p "${PORT}" -i -s "${SCALE}" pgscreen > "${OUT}/init_bench.log" 2>&1

run_cfg() {
  local name="$1"; shift
  grep -q "^${name}," "${CSV}" && { echo "[skip] ${name}"; return; }
  taskset -c "${CLIENT_CORES}" "${PGBENCH}" -h "${SOCK}" -p "${PORT}" "$@" \
    -T "${WARMUP}" pgscreen > /dev/null 2>&1
  taskset -c "${CLIENT_CORES}" "${PGBENCH}" -h "${SOCK}" -p "${PORT}" "$@" \
    -T "${DURATION}" pgscreen > "${OUT}/${name}.pgbench.log" 2>&1 &
  local bpid=$!
  sleep 2
  perf stat -x, -o "${OUT}/${name}.perf.csv" -C "${SERVER_CORES}" \
    -e instructions,cycles,"${EVENT}" -- sleep "$((DURATION - 5))"
  wait "${bpid}"
  local tps
  tps="$(grep -oP 'tps = \K[\d.]+' "${OUT}/${name}.pgbench.log" | tail -1)"
  python3 - "${CSV}" "${name}" "${tps:-0}" "${OUT}/${name}.perf.csv" <<'PY'
import csv, sys
out, name, tps, pf = sys.argv[1:]
ev = {}
for row in csv.reader(open(pf)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
i, c, m = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
csv.writer(open(out, "a", newline="")).writerow(
    [name, tps, int(i), int(c), int(m),
     f"{1000*m/i if i else 0:.4f}", f"{i/c if c else 0:.4f}"])
PY
  echo "[done] ${name} tps=${tps}"
}

run_cfg c8_simple_tpcb    -c 8  -j 8  -M simple
run_cfg c32_simple_tpcb   -c 32 -j 32 -M simple
run_cfg c64_simple_tpcb   -c 64 -j 40 -M simple
run_cfg c8_simple_select  -c 8  -j 8  -M simple -S
run_cfg c32_simple_select -c 32 -j 32 -M simple -S
run_cfg c32_prepared_tpcb -c 32 -j 32 -M prepared

"${PG_CTL}" -D "${DATA}" stop
column -t -s, "${CSV}"
