#!/usr/bin/env bash
# Interleaving check for the Rails tier: puma (4 workers) and ScyllaDB share one 4-core cpuset, each driven at a rate that alone
# leaves it well below saturation. Rails is measured by pid (its worker processes), Scylla by cgroup.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921; OUT=$R/services.csv; APP=/home/hnpark2/prefetchit/benchmarks/railsapp
POOL=${POOL:-8-11}; WIN=${WIN:-20}; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
export PATH=$HOME/.local/share/gem/ruby/3.2.0/bin:$PATH RAILS_ENV=production RAILS_MAX_THREADS=8 WEB_CONCURRENCY=4
export SECRET_KEY_BASE=$(grep -o 'SECRET_KEY_BASE=.*' /tmp/rails_env | cut -d= -f2)
SIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cs-scylla); NC=4
CL=$(python3 -c "import re;s='$POOL';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pg() { pgrep -f "$1" | grep -vw -e $$ -e $BASHPID; }
trap 'cst 0; [[ -n $PP ]] && { kill -TERM -$PP 2>/dev/null; sleep 2; kill -9 -$PP 2>/dev/null; }' EXIT; cst 1
cd $APP; setsid taskset -c $POOL bundle exec puma -w 4 -t 8:8 -b tcp://0.0.0.0:3011 -e production > $R/logs/puma_coloc.log 2>&1 & PP=$!
for i in $(seq 1 30); do sleep 4; curl -sf "http://127.0.0.1:3011/posts?min=10" > /dev/null 2>&1 && break; done
curl -sf "http://127.0.0.1:3011/posts?min=10" > /dev/null || { echo "puma did not answer"; exit 1; }
echo "[$(date +%T)] rails + scylla both on $POOL"
taskset -c 60-63 $W -D exp -t 4 -c 32 -d 120 -L -R 800 "http://127.0.0.1:3011/posts?min=10" > $R/logs/coloc_rails_wrk.log 2>&1 & WP=$!
timeout 180 docker run --rm --net cs_net --cpuset-cpus 64-67 --entrypoint /ycsb/bin/ycsb.sh cloudsuite/data-serving:client run cassandra-cql -p hosts=$SIP -P /ycsb/workloads/workloada -p recordcount=1000000 -p operationcount=100000000 -p maxexecutiontime=110 -s -threads 8 -target 20000 > $R/logs/coloc_rails_ycsb.log 2>&1 & YP=$!
sleep 35; PIDS=$(pg 'puma: cluster worker' | tr '\n' ',' | sed 's/,$//'); echo "  puma worker pids: $PIDS"
echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/cr_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -p "$PIDS" -- sleep $WIN > /dev/null 2>&1
python3 - $POOL $NC $WIN /tmp/cr_perf.csv $OUT <<'PY'
import csv,sys
pool,nc,win,f,out=sys.argv[1:6]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); util=100*c/(float(win)*int(nc)*2.0e9)
open(out,'a').write(f"rails_puma,interleaved_noC6,{pool},coloc,{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},rails 800 rps + scylla YCSB 20k on the same 4 cores\n")
print(f"  rails [interleaved]: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
ID=$(docker inspect -f '{{.Id}}' cs-scylla); docker stats --no-stream --format '{{.CPUPerc}}' cs-scylla > /tmp/cr_cpu.txt 2>/dev/null & DS=$!
echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/cr_perf2.csv -a -C $POOL -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$ID.scope,system.slice/docker-$ID.scope,system.slice/docker-$ID.scope -- sleep $WIN > /dev/null 2>&1; wait $DS
python3 - $POOL $NC /tmp/cr_perf2.csv /tmp/cr_cpu.txt $OUT <<'PY'
import csv,sys
pool,nc,pf,cf,out=sys.argv[1:6]; v={}
for r in csv.reader(open(pf)):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
try: cpu=float(open(cf).read().strip().rstrip('%'))
except: cpu=0.0
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0)
open(out,'a').write(f"scylla,interleaved_noC6,{pool},coloc_rails,{cpu/int(nc):.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},scylla YCSB 20k + rails 800 rps on the same 4 cores\n")
print(f"  scylla [interleaved w/ rails]: util={cpu/int(nc):.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f}")
PY
timeout 200 tail --pid=$WP -f /dev/null; grep -E "Requests/sec" $R/logs/coloc_rails_wrk.log | head -1 | cut -c1-50
cst 0; echo "[$(date +%T)] COLOC_RAILS_DONE"
