#!/usr/bin/env bash
# DCPerf v2 adsim (ads ranking service, C++/thrift): server role pinned to CORES (thread counts derive from the cpuset via
# sched_getaffinity), client role (treadmill QPS search toward the P95 target) on CLCORES. User-mode L2I MPKI / IPC of the server
# process group at DELAY1/DELAY2 s. Rows → dcperf_v2.csv (job=adsim, group=server|client).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; OUT=$R/dcperf_v2.csv
CORES=${CORES:-8-11}; CLCORES=${CLCORES:-60-67}; NC=4; D1=${D1:-60}; D2=${D2:-150}; WIN=${WIN:-20}; RUNTIME=${RUNTIME:-200}; WORKERS=${WORKERS:-8}
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cstate() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pg() { pgrep -f "$1" | grep -vw -e $$ -e $BASHPID; }
killall2() { local p; for p in $(pg "adsim_server --config_file|treadmill_adsim|qps_search.sh"); do echo ps101899 | sudo -S -p '' kill -9 $p 2>/dev/null; done; }
trap 'cstate 0; killall2' EXIT; cstate 1; [[ -f $OUT ]] || echo "job,config,group,cores,delay_s,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
SUDO="sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages"
cd $V; killall2; echo "[$(date +%T)] adsim server on $CORES (C6 off), client on $CLCORES (workers=$WORKERS runtime=$RUNTIME)"
echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages taskset -c $CORES python3 ./benchpress_cli.py -b benchpress/config/benchmarks_ai.yml -j benchpress/config/jobs_ai.yml run adsim -r server -i "{\"cfg_file\": \"default\", \"timeout\": \"$((RUNTIME+120))\"}" > $R/logs/adsim_server.log 2>&1 & SP=$!
sleep 40; sp=$(pg "adsim_server --config_file" | head -1); [[ -z $sp ]] && { echo "  adsim_server not running"; tail -5 $R/logs/adsim_server.log | cut -c1-160; exit 1; }
echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages taskset -c $CLCORES python3 ./benchpress_cli.py -b benchpress/config/benchmarks_ai.yml -j benchpress/config/jobs_ai.yml run adsim -r client -i "{\"server_ip\": \"::1\", \"num_workers\": \"$WORKERS\", \"runtime\": \"$RUNTIME\"}" > $R/logs/adsim_client.log 2>&1 & CP=$!
T0=$(date +%s)
for delay in $D1 $D2; do while (( $(date +%s)-T0 < delay )); do sleep 2; done; kill -0 $sp 2>/dev/null || { echo "  server gone before ${delay}s"; break; }
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/adsim_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -e task-clock -p $sp -- sleep $WIN > /dev/null 2>&1
  python3 - $CORES $NC $delay $WIN /tmp/adsim_perf.csv $OUT <<'PY'
import csv,sys
cores,nc,delay,win,f,out=sys.argv[1:7]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u','task-clock'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(float(win)*1000*int(nc))
open(out,'a').write(f"adsim,noC6,server,{cores},{delay},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"  adsim [noC6] server @{delay}s: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
done
timeout 300 tail --pid=$CP -f /dev/null; grep -aiE "qps|latency|p95|p99|result" $R/logs/adsim_client.log | tail -4 | cut -c1-150; killall2; cstate 0; echo "[$(date +%T)] ADSIM_SCREEN_DONE"
