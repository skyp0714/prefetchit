#!/usr/bin/env bash
# wake-stream campaign: bring the media stack up in the INTERLEAVED regime (whole stack on cores 0-7, C6 off there, MODE=2ghz)
# with movie-id running arm $1 (default gs), load the dataset. Usage: ws_up.sh [ARM]
set -u
export SVC_CORES=${SVC_CORES:-0-7} POOL=${POOL:-0-7} CL_CORES=${CL_CORES:-32-35} RATE=${RATE:-900}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
ARM=${1:-gs}
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up $ARM; bash $MD/media_stack.sh init; cstate 1
echo "[$(date +%T)] smoke at R=$RATE:"; bash $MD/media_stack.sh smoke
echo "[$(date +%T)] WS_UP_DONE arm=$ARM pid=$(svc_pid)"
