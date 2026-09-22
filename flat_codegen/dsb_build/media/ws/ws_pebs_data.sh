#!/usr/bin/env bash
# PEBS load-latency sampling of the service under the interleaved load: data addresses + latency per sample, plus /proc maps, for the
# "what data is cold after a wake" analysis. Usage: ws_pebs_data.sh ARM OUT_DIR [LDLAT=64] [DUR=10]
set -u
export SVC_CORES=${SVC_CORES:-0-7} POOL=${POOL:-0-7} CL_CORES=${CL_CORES:-32-35} RATE=${RATE:-600}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
ARM=$1; OUT=$2; LD=${3:-64}; DUR=${4:-10}; mkdir -p $OUT; WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws
bash $WS/ws_recreate.sh $ARM - - > /dev/null; pid=$(svc_pid)
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 12 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 40 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk.log 2>&1 & WP=$!; sleep 8
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
for t in /proc/$pid/task/*; do echo "$(basename $t) $(echo ps101899 | sudo -S -p '' cat $t/comm 2>/dev/null)"; done > $OUT/threads.txt 2>/dev/null
echo ps101899 | sudo -S -p '' perf record -e cpu/mem-loads,ldlat=$LD/upp -d -W -c 61 --switch-events -p $pid -o $OUT/pebs.data -- sleep $DUR > $OUT/perf_record.log 2>&1
wait $WP; echo ps101899 | sudo -S -p '' chmod a+r $OUT/pebs.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/pebs.data --symfs=/proc/$pid/root -F tid,time,ip,sym,addr,weight,dso 2>/dev/null > $OUT/samples.txt
echo ps101899 | sudo -S -p '' perf script -i $OUT/pebs.data --show-switch-events --no-itrace -F tid,time 2>/dev/null | grep SWITCH > $OUT/switch.txt
echo "pebs samples: $(wc -l < $OUT/samples.txt), switches: $(wc -l < $OUT/switch.txt)"; head -3 $OUT/samples.txt | cut -c1-160
echo "PEBS_DONE"
