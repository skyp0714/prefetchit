#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# Interleaved A/B for PostStorageService arms that swap BOTH the main binary
# and the /usr/local/lib DSO set (libs_active mount, see
# compose-override-libs.yml). Arm spec: <name>=<binary>:<libsdir>
# Usage: dsb_ab_libs.sh <outdir> <reps> name=bin:libsdir [...]
set -e
cd "$(dirname "$0")"
OUT=$1; REPS=$2; shift 2
mkdir -p "$OUT" libs_active
ARMS=("$@")

measure_arm() {
  local name=$1 bin=$2 libs=$3 rep=$4
  rm -f bin_active/PostStorageService
  cp "$bin" bin_active/PostStorageService
  rsync -a --delete "$libs"/ libs_active/
  sudo docker restart socialnetwork-post-storage-service-1 > /dev/null 2>&1
  sleep 5
  if [ -n "${PIN_CORES:-}" ]; then
    local ppid
    ppid=$(pgrep -f '^/custom/PostStorageService' | head -1)
    sudo taskset -acp "$PIN_CORES" "$ppid" > /dev/null 2>&1
  fi
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
    name=${arm%%=*}; rest=${arm#*=}
    bin=${rest%%:*}; libs=${rest#*:}
    measure_arm "$name" "$bin" "$libs" "$rep"
  done
done
echo DONE
