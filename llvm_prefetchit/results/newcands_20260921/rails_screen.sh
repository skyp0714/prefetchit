#!/usr/bin/env bash
# Rails (CRuby 3.2, YJIT off) API service screen: puma with 4 workers x 8 threads pinned to CORES, production env, MySQL 8 on 4-7;
# wrk2 from the client cores at several rates. Nothing else runs on CORES, so the counters are taken system-wide on those cores (:u).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921; OUT=$R/services.csv; APP=/home/hnpark2/prefetchit/benchmarks/railsapp
CORES=${CORES:-0-3}; CLCORES=${CLCORES:-60-67}; WIN=${WIN:-20}; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
export PATH=$HOME/.local/share/gem/ruby/3.2.0/bin:$PATH RAILS_ENV=production RAILS_MAX_THREADS=8 WEB_CONCURRENCY=4
export SECRET_KEY_BASE=$(grep -o 'SECRET_KEY_BASE=.*' /tmp/rails_env | cut -d= -f2)
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pg() { pgrep -f "$1" | grep -vw -e $$ -e $BASHPID; }
trap 'cst 0; [[ -n $PP ]] && { kill -TERM -$PP 2>/dev/null; sleep 2; kill -9 -$PP 2>/dev/null; }' EXIT; cst 1
cd $APP; setsid taskset -c $CORES bundle exec puma -w 4 -t 8:8 -b tcp://0.0.0.0:3010 -e production > $R/logs/puma.log 2>&1 & PP=$!
for i in $(seq 1 30); do sleep 4; curl -sf "http://127.0.0.1:3010/posts?min=10" > /dev/null 2>&1 && { echo "puma up after $((i*4))s ($(pg 'puma: cluster worker' | wc -l) workers)"; break; }; done
curl -sf "http://127.0.0.1:3010/posts?min=10" > /dev/null || { echo "puma did not answer"; tail -5 $R/logs/puma.log | cut -c1-140; exit 1; }
for rate in "$@"; do
  echo "[$(date +%T)] rails rate=$rate"
  taskset -c $CLCORES $W -D exp -t 8 -c 64 -d 60 -L -R $rate "http://127.0.0.1:3010/posts?min=10" > $R/logs/rails_$rate.log 2>&1 & WP=$!
  sleep 20; echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/rails_perf.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -e task-clock -- sleep $WIN > /dev/null 2>&1
  python3 - $CORES $NC $rate $WIN /tmp/rails_perf.csv $OUT <<'PY'
import csv,sys
cores,nc,rate,win,f,out=sys.argv[1:7]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u','task-clock'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0)
util=100*c/(float(win)*int(nc)*2.0e9)   # system-wide task-clock is elapsed x ncpus even when idle; use user cycles at the frozen 2 GHz clock
open(out,'a').write(f"rails_puma,noC6,{cores},{rate},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},Rails 8 API + puma 4 workers x 8 threads (CRuby 3.2 no YJIT) production; MySQL 8 on 4-7\n")
print(f"  rails rate={rate}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
  timeout 90 tail --pid=$WP -f /dev/null; grep -E "Requests/sec|Non-2xx" $R/logs/rails_$rate.log | head -2 | cut -c1-60
done
cst 0; echo "[$(date +%T)] RAILS_SCREEN_DONE"
