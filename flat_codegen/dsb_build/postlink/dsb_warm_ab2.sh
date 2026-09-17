#!/usr/bin/env bash
# Interleaved A/B of post-link-patched UserTimelineService arms inside the stock DSB stack.
# Arm spec: name=BINDIR:LIBSDIR:IMAGE:PRELOAD:LIST:N:STAGE:MINCYC[@CPUS]  (PRELOAD/LIST are container paths, "-" = none)
# Usage: dsb_postlink_ab.sh OUTDIR REPS name=dir [...]
# Metrics per arm/rep: service-process perf stat (instructions, cycles, L2I misses, task-clock) over
# a 30 s window of a fixed-rate wrk2 mixed load (R req/s), plus wrk2 latency p50/p99 and non-2xx count.
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; export PL
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
mkdir -p $1; OUT=$(readlink -f $1); REPS=$2; shift 2; ARMS=("$@")
R=${R:-6000}; DUR=${DUR:-60}; PWIN=${PWIN:-30}; CLIENT_CORES=${CLIENT_CORES:-60-67}
FILES="UserTimelineService libthrift.so.0.12.0 libjaegertracing.so.0 libmongoc-1.0.so.0 libbson-1.0.so.0 libstdc++.so.6.0.21 libc-2.23.so"
CSV=$OUT/runs.csv; [[ -f $CSV ]] || echo "arm,rep,rps,non2xx,p50_ms,p99_ms,instructions,cycles,l2i_miss,task_clock_ms" > $CSV
set_arm() { export UTL_BIN=$1 UTL_LIBS=$2 UTL_IMG=$3; }
cd $SN
for rep in $(seq 1 $REPS); do for arm in "${ARMS[@]}"; do
  name=${arm%%=*}; spec=${arm#*=}; cpus=; [[ $spec == *@* ]] && { cpus=${spec#*@}; spec=${spec%@*}; }; IFS=: read -r bindir libsdir img preload list wn wstage wmin wpace <<< "$spec"; [[ $preload == - ]] && preload=; [[ $list == - ]] && list=; export WARM_PRELOAD=$preload WARM_LIST=$list WARM_N=${wn:-64} WARM_STAGE=${wstage:-0} WARM_MIN=${wmin:-20000} WARM_PACE=${wpace:-0}
  set_arm $bindir $libsdir $img
  docker compose -f docker-compose.yml -f $PL/compose-override-utl-warm.yml up -d --force-recreate --no-deps user-timeline-service > $OUT/up_${name}_r${rep}.log 2>&1
  sleep 6
  PINPID=; if [[ $cpus == *:* ]]; then echo ps101899 | sudo -S nohup $PL/pin_threads.sh socialnetwork-user-timeline-service-1 ${cpus%%:*} ${cpus#*:} > /dev/null 2>&1 & PINPID=$!; sleep 1; elif [[ -n $cpus ]]; then docker update --cpuset-cpus $cpus socialnetwork-user-timeline-service-1 > /dev/null; fi
  pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1)
  if [[ -z "$pid" || "$pid" == 0 ]]; then echo "$name r$rep: service did not start" | tee -a $OUT/errors.log; docker logs socialnetwork-user-timeline-service-1 2>&1 | tail -3 >> $OUT/errors.log; continue; fi
  taskset -c $CLIENT_CORES $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > /dev/null 2>&1
  taskset -c $CLIENT_CORES $W -D exp -t 8 -c 64 -d $DUR -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2_${name}_r${rep}.log 2>&1 &
  WP=$!; sleep 15
  echo ps101899 | sudo -S perf stat -x, -o $OUT/perf_${name}_r${rep}.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/',task-clock -p $pid -- sleep $PWIN > /dev/null 2>&1
  wait $WP
  if [[ -n $PINPID ]]; then echo ps101899 | sudo -S pkill -P $PINPID > /dev/null 2>&1; echo ps101899 | sudo -S kill $PINPID > /dev/null 2>&1; fi
  python3 - $OUT $name $rep $CSV <<'PY'
import csv,re,sys
out,name,rep,csvp=sys.argv[1:5]
ev={}
for row in csv.reader(open(f"{out}/perf_{name}_r{rep}.csv")):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
w=open(f"{out}/wrk2_{name}_r{rep}.log").read()
def g(rx,d='0'):
    m=re.search(rx,w); return m.group(1) if m else d
rps=g(r"Requests/sec:\s+([0-9.]+)"); bad=g(r"Non-2xx or 3xx responses:\s+(\d+)")
p50=g(r"\n\s+50.000%\s+([0-9.]+)(ms|s|us)"); p99=g(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)")
def ms(rx):
    m=re.search(rx,w)
    if not m: return 0
    v=float(m.group(1)); u=m.group(2); return v*(1000 if u=='s' else 0.001 if u=='us' else 1)
p50=ms(r"\n\s+50.000%\s+([0-9.]+)(ms|s|us)"); p99=ms(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)")
i=ev.get('instructions',0); c=ev.get('cycles',0); m=ev.get('L2I_CODE_RD_MISS',0); t=ev.get('task-clock',0)
open(csvp,'a').write(f"{name},{rep},{rps},{bad},{p50:.2f},{p99:.2f},{i:.0f},{c:.0f},{m:.0f},{t:.1f}\n")
print(f"{name} r{rep}: rps={rps} non2xx={bad} p50={p50:.1f}ms p99={p99:.1f}ms MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} cycles={c/1e9:.2f}G cpu={t/1000:.1f}s")
PY
done; done
:
echo AB_DONE
