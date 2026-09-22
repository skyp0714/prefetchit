#!/usr/bin/env bash
# Recreate movie-id with binary arm $1 and the wake-stream preload: ws_recreate.sh ARM [PRELOAD.so|-] [LIST|-] [N0] [QM] [MIN_CYCLES]
# PRELOAD/LIST are host paths under flat_codegen/dsb_build (mounted at /dsb inside the container).
set -u
export SVC_CORES=${SVC_CORES:-0-7} POOL=${POOL:-0-7} CL_CORES=${CL_CORES:-32-35}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
ARM=$1; PRE=${2:--}; LIST=${3:--}; export WS_N0=${4:-32} WS_QM=${5:-32} WS_MIN=${6:-20000}
tocont() { [[ $1 == - ]] && echo "" || echo "/dsb/${1#$DB/}"; }
export SVC_IMG=${SVC_IMG:-dsb-deps-jammy} SVC_BIN=$DB/out_${OUTPFX}_$ARM SVC_LIBS=$DB/libs_${OUTPFX}_$ARM WS_PRELOAD=$(tocont $PRE) WS_LISTF=$(tocont $LIST)
[[ -x $SVC_BIN/$SVCBIN ]] || { echo "missing $SVC_BIN/$SVCBIN"; exit 1; }
cd $MM && docker compose -f docker-compose.yml -f $MD/compose-override-movie-id-service-ws.yml up -d --force-recreate --no-deps $SVC > $MD/ws/logs/recreate.log 2>&1
sleep 6; pin_all; echo "$SVC -> arm $ARM preload=${WS_PRELOAD:-none} list=${WS_LISTF:-none} N0=$WS_N0 QM=$WS_QM (pid $(svc_pid))"
