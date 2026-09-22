#!/usr/bin/env bash
# Trace the target media service (already running as arm $ARM) under the standard load.
# MODE=lbr|rate|instr|miss  Usage: MODE=lbr media_trace.sh OUT_DIR ARM
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
OUT=$1; ARM=$2; MODE=${MODE:-lbr}; WIN=${WIN:-25}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
BIN=$DB/out_${OUTPFX}_$ARM/$SVCBIN; [[ -x $BIN ]] || { echo "missing $BIN"; exit 1; }
pid=$(svc_pid); echo "trace $MODE on $CONT pid=$pid arm=$ARM"
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 15 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 60 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk2.log 2>&1 & WP=$!; sleep 10
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
case $MODE in
  lbr)   REC="-e cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp -b -c 1000"; FLD="ip,dso,brstack";;
  rate)  REC="-e cycles:u -b -c 400000"; FLD="ip,dso,brstack";;
  instr) REC="-e instructions:u -c 200000"; FLD="ip,dso";;
  miss)  REC="-e cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp -c 1000"; FLD="ip,dso";;
esac
echo ps101899 | sudo -S -p '' perf record $REC -p $pid -o $OUT/perf.data -- sleep $WIN > $OUT/perf_record.log 2>&1
wait $WP; grep -E "Requests/sec|Non-2xx" $OUT/wrk2.log
echo ps101899 | sudo -S -p '' chmod a+r $OUT/perf.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/perf.data -F $FLD 2>/dev/null | sed -E 's#\(/[^)]*/([^/)]*)\)#(\1)#g' > $OUT/samples_raw.txt; rm -f $OUT/perf.data
python3 /home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919/parse_trace.py $OUT $BIN $MODE
echo "TRACE_DONE $MODE"
