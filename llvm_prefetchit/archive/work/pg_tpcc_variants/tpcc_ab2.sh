#!/bin/bash
# TPC-C A/B v2: per-arm fresh DB from template (kills state drift), fresh
# server, 30s warm + 120s measured. Requires tpcc_master template db.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCHIT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BASE="${SCRIPT_DIR}"
TPCC="${LLVM_PREFETCHIT_ROOT}/work/sysbench-tpcc"
DATA=/tmp/pgdata_tpcc
OUT=${1:-$BASE/tpcc_ab2.csv}
REPS=${2:-3}
ARMS="${ARMS:-install_base install_nop2 install_inj2 install_pgo}"
echo "arm,rep,tps,lat95,mpki,ipc" > "$OUT"

stop_pg() {
  for d in install_base install_pgo install_inj install_nop install_inj2 install_nop2 install_injT install_nopT install_injB install_nopB; do
    $BASE/$d/bin/pg_ctl -D $DATA stop -m fast > /dev/null 2>&1 || true
  done
  sleep 2
}

run_tpcc() {
  (cd $TPCC && ./tpcc.lua --db-driver=pgsql --pgsql-host=localhost \
    --pgsql-port=5433 --pgsql-user=hnpark2 --pgsql-db=tpcc --threads=16 \
    --tables=1 --scale=5 --time=$1 run > $2 2>&1)
}

measure_arm() {
  local arm=$1 rep=$2
  stop_pg
  $BASE/$arm/bin/pg_ctl -D $DATA \
    -o '-p 5433 -c shared_buffers=4GB -c max_connections=100' \
    -l /tmp/pg_$arm.log start > /dev/null 2>&1
  sleep 3
  $BASE/install_base/bin/dropdb -p 5433 --if-exists tpcc > /dev/null 2>&1
  $BASE/install_base/bin/createdb -p 5433 -T tpcc_master tpcc
  run_tpcc 30 /tmp/tpcc_warm.log
  run_tpcc 120 /tmp/tpcc_m_$arm.log &
  local lpid=$!
  sleep 30
  local pids
  pids=$(pgrep -f 'postgres.*tpcc' | head -16 | paste -sd,)
  sudo perf stat -p "$pids" \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles' \
    -o /tmp/tpcc_perf.txt -- sleep 15 2>/dev/null || true
  wait $lpid || true
  local tps lat miss insn cyc mpki ipc
  tps=$(grep -oP 'transactions:\s+\d+\s+\(\K[\d.]+' /tmp/tpcc_m_$arm.log)
  lat=$(grep -oP '95th percentile:\s+\K[\d.]+' /tmp/tpcc_m_$arm.log)
  miss=$(grep -oP '[\d,]+(?=\s+L2I_CODE_RD_MISS)' /tmp/tpcc_perf.txt | tr -d ,)
  insn=$(grep -oP '[\d,]+(?=\s+instructions)' /tmp/tpcc_perf.txt | tr -d ,)
  cyc=$(grep -oP '[\d,]+(?=\s+cycles)' /tmp/tpcc_perf.txt | tr -d ,)
  mpki=$(python3 -c "print(f'{1000*$miss/$insn:.2f}')" 2>/dev/null || echo NA)
  ipc=$(python3 -c "print(f'{$insn/$cyc:.3f}')" 2>/dev/null || echo NA)
  echo "$arm,$rep,$tps,$lat,$mpki,$ipc" >> "$OUT"
  echo "$arm r$rep tps=$tps lat95=$lat mpki=$mpki ipc=$ipc"
}

for rep in $(seq 1 $REPS); do
  for arm in $ARMS; do
    measure_arm $arm $rep
  done
done
stop_pg
echo DONE
