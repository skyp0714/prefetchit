#!/usr/bin/env bash
# Intel PT trace of the running movie-id service under the interleaved load: user-mode control flow of every service thread,
# context-switch events (run boundaries) and syscall exits (which blocking call woke the thread).
# Usage: ws_pt_trace.sh OUT_DIR ARM [DUR_S=0.3]   (stack must be up via ws_up.sh; RATE from env, default 900)
set -u
export SVC_CORES=0-7 POOL=0-7 CL_CORES=32-35 RATE=${RATE:-900}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
OUT=$1; ARM=$2; DUR=${3:-0.3}; CORES=${CORES:-$SVC_CORES}; AUXMM=${AUXMM:-256M}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
BIN=$DB/out_${OUTPFX}_$ARM/$SVCBIN; pid=$(svc_pid); echo "pt trace on $CONT pid=$pid arm=$ARM dur=${DUR}s R=$RATE mode=${PT_MODE:-pid} cores=$CORES aux=$AUXMM"
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 12 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 30 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk2.log 2>&1 & WP=$!; sleep 10
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
if [[ ${PT_MODE:-pid} == cpu ]]; then REC="-a -C $CORES"; else REC="-p $pid"; fi   # pid mode: only the service's threads (inherit), no tracepoint flood
echo ps101899 | sudo -S -p '' perf record -e intel_pt//u --switch-events -m 64M,$AUXMM $REC -o $OUT/pt.data -- sleep $DUR > $OUT/perf_record.log 2>&1
wait $WP; grep -E "Requests/sec|Non-2xx" $OUT/wrk2.log; grep -iE "lost|aux" $OUT/perf_record.log | head -3
echo ps101899 | sudo -S -p '' chmod a+r $OUT/pt.data
# decode: branches (ip => addr with flags), switch events, syscall exits. symfs = the container's root so perf can read the code images.
echo ps101899 | sudo -S -p '' perf script -i $OUT/pt.data --symfs=/proc/$pid/root --pid=$pid --itrace=b --show-switch-events -F tid,time,ip,addr,flags 2> $OUT/decode.err > $OUT/branches.txt
echo ps101899 | sudo -S -p '' perf script -i $OUT/pt.data --no-itrace --pid=$pid 2>/dev/null | grep -F "raw_syscalls:sys_exit" > $OUT/syscalls.txt
# copy the container's mapped images (exe + system libs of the jammy image) for offline symbolization
SYMFS=$OUT/../symfs_$ARM; mkdir -p $SYMFS
for f in $(awk '$6 ~ /^\// {print $6}' $OUT/maps.txt | sort -u); do [[ -f $SYMFS$f ]] && continue; mkdir -p $SYMFS$(dirname $f); echo ps101899 | sudo -S -p '' cp /proc/$pid/root$f $SYMFS$f 2>/dev/null; done
echo ps101899 | sudo -S -p '' chown -R $USER $SYMFS
echo "branches: $(wc -l < $OUT/branches.txt) lines, syscalls: $(wc -l < $OUT/syscalls.txt), decode errors: $(grep -c . $OUT/decode.err)"; head -3 $OUT/decode.err
echo "PT_TRACE_DONE"
