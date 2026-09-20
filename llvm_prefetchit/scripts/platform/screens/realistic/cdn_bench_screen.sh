#!/usr/bin/env bash
# DCPerf v2 cdn_bench (proxygen reverse proxy): content server, proxy and client all on this host. The proxy is the SUT on CORES (C6 off),
# the content server on CSCORES, the client on CLCORES. Ports 9082/9081: every run.sh invocation kills whatever listens on its
# default ports 8082/8081 at startup ("stale process" sweep), so co-located server/proxy/client must avoid those. RPS sweep; user-mode L2I MPKI / IPC of proxy_server and content_server at DELAY s.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; RUN=$V/packages/cdn_bench/run.sh; OUT=$R/dcperf_v2.csv
BHOST=${BHOST:-127.0.0.1}; CPORT=${CPORT:-9082}; PPORT=${PPORT:-9081}; CCONN=${CCONN:-4}; CSTREAMS=${CSTREAMS:-100}; CTHR=${CTHR:-2}; CORES=${CORES:-8-11}; CSCORES=${CSCORES:-16-19}; CLCORES=${CLCORES:-60-67}; NC=4; DUR=${DUR:-150}; DELAY=${DELAY:-60}; WIN=${WIN:-20}
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cstate() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pg() { pgrep -f "$1" | grep -vw -e $$ -e $BASHPID; }
killall3() { local p; for p in $(pg "proxy_server|content_server|traffic_client"); do kill -9 $p 2>/dev/null; done; }
trap 'cstate 0; killall3' EXIT; cstate 1; [[ -f $OUT ]] || echo "job,config,group,cores,delay_s,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
rec() { local cfg=$1 grp=$2 pid=$3 f=/tmp/cdn_$grp.csv; echo ps101899 | sudo -S -p '' perf stat -x, -o $f -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -e task-clock -p $pid -- sleep $WIN > /dev/null 2>&1
  python3 - "$cfg" $grp $CORES $NC $DELAY $WIN $f $OUT <<'PY'
import csv,sys
cfg,grp,cores,nc,delay,win,f,out=sys.argv[1:9]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u','task-clock'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(float(win)*1000*int(nc))
open(out,'a').write(f"cdn_bench,{cfg},{grp},{cores},{delay},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"  cdn_bench [{cfg}] {grp:8s}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
}
for rps in ${RPS_LIST:-1000 4000 12000}; do killall3; echo "[$(date +%T)] cdn_bench rps=$rps (proxy on $CORES, content on $CSCORES, client on $CLCORES)"
  taskset -c $CSCORES bash $RUN -m server -P $CPORT -p h2 -d $((DUR+40)) -I 2 > $R/logs/cdn_server_r$rps.log 2>&1 & sleep 4
  taskset -c $CORES bash $RUN -m proxy -B $BHOST -b $CPORT -P $PPORT -p h2 -d $((DUR+30)) -I 4 > $R/logs/cdn_proxy_r$rps.log 2>&1 & sleep 4
  taskset -c $CLCORES bash $RUN -m client -T $BHOST:$PPORT -d $DUR -r $rps -c $CCONN -S $CSTREAMS -t $CTHR > $R/logs/cdn_client_r$rps.log 2>&1 & CP=$!
  sleep $DELAY; pp=$(pg "proxy_server" | head -1); sp=$(pg "content_server" | head -1)
  [[ -z $pp ]] && { echo "  proxy not running"; tail -3 $R/logs/cdn_proxy_r$rps.log | cut -c1-140; tail -2 $R/logs/cdn_client_r$rps.log | cut -c1-140; killall3; continue; }
  rec noC6_rps$rps proxy $pp; [[ -n $sp ]] && rec noC6_rps$rps content $sp
  timeout $((DUR+60)) tail --pid=$CP -f /dev/null; grep -aiE "rps|latency|p99|throughput|error" $R/logs/cdn_client_r$rps.log | tail -3 | cut -c1-150; killall3; sleep 3
done
cstate 0; echo "[$(date +%T)] CDN_SCREEN_DONE"
