#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# Interleaved A/B for PostStorageService binary variants on live DSB stack.
# Usage: dsb_ab.sh <outdir> <reps> <armA_name>=<armA_binary> <armB_name>=<armB_binary> [...]
# Each rep runs every arm once (order as given). Arm binary is copied into
# bin_active/, post-storage container restarted, 15s warmup, 75s measured
# load (4x16), with a 20s perf-stat window (L2I miss + IPC) mid-run.
set -e
cd "$(dirname "$0")"
OUT=$1; REPS=$2; shift 2
mkdir -p "$OUT"
ARMS=("$@")

measure_arm() {
  local name=$1 bin=$2 rep=$3
  rm -f bin_active/PostStorageService
  cp "$bin" bin_active/PostStorageService
  sudo docker restart socialnetwork-post-storage-service-1 > /dev/null 2>&1
  sleep 5
  python3 dsb_load2.py --procs "${LOAD_PROCS:-4}" --threads "${LOAD_THREADS:-16}" --duration 15 --tag warmup > /dev/null 2>&1
  python3 dsb_load2.py --procs "${LOAD_PROCS:-4}" --threads "${LOAD_THREADS:-16}" --duration 75 \
    --tag "${name}_r${rep}" >> "$OUT/qps.log" 2>&1 &
  local loadpid=$!
  sleep 25
  local pid
  pid=$(pgrep -f '^/custom/PostStorageService' | head -1)
  sudo perf stat -p "$pid" \
    -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles' \
    -o "$OUT/perf_${name}_r${rep}.txt" -- sleep 20 2>/dev/null || true
  wait $loadpid
  tail -1 "$OUT/qps.log"
}

for rep in $(seq 1 "$REPS"); do
  for arm in "${ARMS[@]}"; do
    name=${arm%%=*}; bin=${arm#*=}
    measure_arm "$name" "$bin" "$rep"
  done
done
echo DONE
