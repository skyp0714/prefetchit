#!/usr/bin/env bash
# arcilator DualMegaBoom: base + sequential-lookahead variants through the PrefetchIT pass (+ NOP twins)
set -euo pipefail
cd "$(dirname "$0")"
PLUGIN=/home/hnpark2/prefetchit/llvm_prefetchit/build/PrefetchITPass.so
NOP=/home/hnpark2/prefetchit/llvm_prefetchit/tools/make_nop_control_binary.py
log(){ echo "[$(date '+%F %T')] $*"; }
if [[ ! -x dmb2_base ]]; then log "build base"; /usr/bin/time -f 'base %e s %M KB' clang-19 -O2 -g dmb.ll driver_dmb2.c -o dmb2_base; fi
for spec in ${ARC_SPECS:-"d4096_k40:4096:40" "d4096_k20:4096:20" "d2048_k20:2048:20" "d8192_k40:8192:40"}; do
  IFS=: read -r l d k <<< "$spec"
  [[ -x dmb2_seq_$l ]] && continue
  log "build seq $l"
  PREFETCHIT_SEQ_DISTANCE=$d PREFETCHIT_SEQ_STRIDE_INSNS=$k PREFETCHIT_SEQ_FUNCTIONS='.*' \
    /usr/bin/time -f "seq_$l %e s %M KB" clang-19 -O2 -g -fpass-plugin=$PLUGIN dmb.ll driver_dmb2.c -o dmb2_seq_$l 2> build_seq_$l.err || { tail -3 build_seq_$l.err; exit 1; }
  grep prefetchit-seq build_seq_$l.err | tail -1
  python3 $NOP --input dmb2_seq_$l --output dmb2_seq_${l}_nop --mnemonics prefetcht1 | tail -1
  log "$l: $(llvm-objdump-19 -d dmb2_seq_$l | grep -c prefetcht1) prefetches; twin $(llvm-objdump-19 -d dmb2_seq_${l}_nop | grep -c prefetcht1) left"
done
log "smoke: $(taskset -c 50 ./dmb2_base 200)"
log done
