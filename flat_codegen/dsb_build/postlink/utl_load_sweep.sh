#!/usr/bin/env bash
# Find a realistic 4-core baseline: user-timeline (fat-static gs) on cpuset CORES, read-only load at increasing rates; per step:
# CPU utilization of the 4 cores, threads alive/running, MPKI, IPC, p50/p99, non-2xx, nginx/post-storage CPU%. Stops at saturation.
# Usage: utl_load_sweep.sh OUT [rates...]
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
OUT=$1; shift; mkdir -p $OUT; OUT=$(readlink -f $OUT); RATES=${@:-5000 10000 15000 20000 30000 40000 50000}; CORES=${CORES:-36-39}; NC=${NC:-4}; CONN=${CONN:-256}
export UTL_BIN=${UTL_BIN:-$DB/out_utl_gs} UTL_LIBS=${UTL_LIBS:-$DB/libs_utl_gs} UTL_IMG=dsb-deps-g WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
cd $SN; docker compose -f docker-compose.yml -f $PL/compose-override-user-timeline-service-warm.yml up -d --force-recreate --no-deps user-timeline-service > $OUT/up.log 2>&1; sleep 6
docker update --cpuset-cpus $CORES socialnetwork-user-timeline-service-1 > /dev/null; pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); echo "utl pid=$pid cpuset=$CORES bin=$UTL_BIN"
CSV=$OUT/sweep.csv; echo "rate,rps,non2xx,p50_ms,p99_ms,util_pct,threads_alive,threads_running,instr,cycles,l2i,cs,mpki,ipc,nginx_cpu,poststorage_cpu,shared_busy_pct" > $CSV
for R in $RATES; do
  taskset -c 60-67 $W -D exp -t 8 -c $CONN -d 15 -L -s $PL/utl_read.lua http://localhost:8080 -R $R > /dev/null 2>&1
  taskset -c 60-67 $W -D exp -t 8 -c $CONN -d 45 -L -s $PL/utl_read.lua http://localhost:8080 -R $R > $OUT/wrk2_$R.log 2>&1 & WP=$!; sleep 8
  ( for i in $(seq 1 40); do a=$(ls /proc/$pid/task 2>/dev/null | wc -l); r=$(grep -l "^State:\s*R" /proc/$pid/task/*/status 2>/dev/null | wc -l); echo "$a $r"; sleep 0.5; done > $OUT/threads_$R.txt ) &
  ( mpstat -P 0-35 28 1 2>/dev/null | awk '/Average/ && $2!="CPU"{s+=100-$NF; n++} END{printf "%.1f\n", s/n}' > $OUT/shared_$R.txt ) &
  ( docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' socialnetwork-nginx-thrift-1 socialnetwork-post-storage-service-1 > $OUT/stats_$R.txt 2>/dev/null ) &
  echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/perf_$R.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I/',task-clock,context-switches -p $pid -- sleep 30 > /dev/null 2>&1
  wait $WP
  python3 - $OUT $R $CSV $NC <<'PY'
import csv,re,sys,statistics
out,R,csvp,nc=sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4]); ev={}
for row in csv.reader(open(f"{out}/perf_{R}.csv")):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
w=open(f"{out}/wrk2_{R}.log").read()
def ms(rx):
    m=re.search(rx,w)
    if not m: return 0.0
    v=float(m.group(1)); u=m.group(2); return v*(1000 if u=='s' else 0.001 if u=='us' else 1)
rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(rps.group(1)) if rps else 0; bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w); bad=int(bad.group(1)) if bad else 0
p50=ms(r"\n\s+50.000%\s+([0-9.]+)(ms|s|us)"); p99=ms(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)")
th=[l.split() for l in open(f"{out}/threads_{R}.txt") if l.strip()]; alive=statistics.mean(int(a) for a,r in th) if th else 0; run=statistics.mean(int(r) for a,r in th) if th else 0
st={l.split()[0]:l.split()[1] for l in open(f"{out}/stats_{R}.txt") if l.strip()}
try: shared=open(f"{out}/shared_{R}.txt").read().strip()
except FileNotFoundError: shared='?'
i=ev.get('instructions',0); c=ev.get('cycles',0); m=ev.get('L2I',0); t=ev.get('task-clock',0); cs=ev.get('context-switches',0)
util=100*t/(30000*nc)
open(csvp,'a').write(f"{R},{rps:.0f},{bad},{p50:.2f},{p99:.2f},{util:.1f},{alive:.0f},{run:.1f},{i:.0f},{c:.0f},{m:.0f},{cs:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{st.get('socialnetwork-nginx-thrift-1','?')},{st.get('socialnetwork-post-storage-service-1','?')},{shared}\n")
print(f"R={R}: rps={rps:.0f} non2xx={bad} p50={p50:.1f}ms p99={p99:.1f}ms util={util:.0f}% threads alive={alive:.0f} running={run:.1f} MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} cs/s={cs/30:.0f} shared0-35={shared}% nginx={st.get('socialnetwork-nginx-thrift-1','?')} poststorage={st.get('socialnetwork-post-storage-service-1','?')}")
sys.exit(1 if (bad>0 or p99>1000) else 0)
PY
  [[ $? -ne 0 ]] && { echo "saturated at R=$R"; break; }
done
echo SWEEP_DONE
