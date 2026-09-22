#!/usr/bin/env bash
# DCPerf rerun: django_workload_default and feedsim_default (now registered as installed), and tao_bench_standalone with its client
# commands executed locally (parsed from benchpress.log: "./benchpress_cli.py run tao_bench_custom -r client -i '{...}'").
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; D=/home/hnpark2/prefetchit/benchmarks/dcperf; OUT=$R/dcperf_default.csv; export PATH=$R/shim:$PATH
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u'
rec() { local job=$1 scope=$2 delay=$3 f=$4 note=$5; python3 - $job $scope $delay $f "$note" $OUT <<'PY'
import csv,sys
job,scope,delay,f,note,out=sys.argv[1:7]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0)
open(out,'a').write(f"{job},{scope},{delay},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{note}\n")
print(f"{job} [{scope} @{delay}s]: MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G {note}")
PY
}
measure() { local job=$1 pat=$2 delay=$3 jp=$4; kill -0 $jp 2>/dev/null || { echo "  $job ended before ${delay}s"; return 1; }
  perf stat -x, -o /tmp/dc_sys.csv -e $EV -a -- sleep 30 > /dev/null 2>&1 & local P1=$!; local pids=""
  if [[ -n $pat ]]; then pids=$(pgrep -f "$pat" | tr '\n' ',' | sed 's/,$//'); [[ -n $pids ]] && perf stat -x, -o /tmp/dc_proc.csv -e $EV -p $pids -- sleep 30 > /dev/null 2>&1; fi; wait $P1
  rec $job system $delay /tmp/dc_sys.csv "all cores :u"; [[ -n $pids ]] && rec $job process $delay /tmp/dc_proc.csv "pids matching $pat"; return 0; }
cd $D
for spec in "django_workload_default:uwsgi:150:400" "feedsim_default:LeafNodeService|feedsim|ParentNode|Ranking:400:1000"; do IFS=: read -r job pat d1 d2 <<< "$spec"; echo "[$(date +%T)] $job"
  (python3 ./benchpress_cli.py run $job > $R/logs/dcperf2_$job.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/dcperf2_$job.log) & JP=$!
  sleep $d1; measure $job "$pat" $d1 $JP && { sleep $((d2-d1-30)); measure $job "$pat" $d2 $JP; }
  wait $JP; grep -E "JOB_EXIT|score|Score|Throughput|throughput|QPS|qps|rps|not installed" $R/logs/dcperf2_$job.log | tail -4 | cut -c1-160
done
echo "[$(date +%T)] tao_bench_standalone with local clients"; L0=$(wc -l < benchpress.log)
(python3 ./benchpress_cli.py run tao_bench_standalone > $R/logs/dcperf2_tao.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/dcperf2_tao.log) & JP=$!
for i in $(seq 1 30); do tail -n +$L0 benchpress.log | grep -q "tao_bench_custom -r client" && break; sleep 3; done
tail -n +$L0 benchpress.log | grep -oE "\./benchpress_cli\.py run tao_bench_custom -r client -i '[^']*'" | sort -u > /tmp/tao_clients.txt; echo "client commands: $(wc -l < /tmp/tao_clients.txt)"
n=0; while read -r cmd; do n=$((n+1)); (eval "$cmd" > $R/logs/dcperf2_tao_client$n.log 2>&1) & sleep 1; done < /tmp/tao_clients.txt
sleep 240; measure tao_bench_standalone "memcached|tao_bench_server" 240 $JP; sleep 200; measure tao_bench_standalone "memcached|tao_bench_server" 470 $JP
wait $JP; grep -E "total_qps|fast_qps|hit_ratio|JOB_EXIT" $R/logs/dcperf2_tao.log | head -4 | tr -d '\t' | tr '\n' ' '; echo; grep -iE "qps|error" $R/logs/dcperf2_tao_client1.log 2>/dev/null | tail -2 | cut -c1-160
echo "[$(date +%T)] DCPERF2_DONE"
