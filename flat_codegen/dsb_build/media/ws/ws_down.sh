#!/usr/bin/env bash
# End of the wake-stream session: C6 back on for cores 0-7, stack down, clocks restored.
set -u
export SVC_CORES=0-7 POOL=0-7 CL_CORES=32-35
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh show | head -2; echo "[$(date +%T)] WS_DOWN_DONE"
