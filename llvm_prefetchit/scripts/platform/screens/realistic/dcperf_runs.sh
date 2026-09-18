#!/usr/bin/env bash
# DCPerf default jobs, as shipped (whole machine, nproc-scaled threads): django_workload_default, feedsim_default, tao_bench_standalone,
# video_transcode_bench_svt, folly (wdl), health_check. During the steady phase: system-wide user-mode L2I MPKI / IPC (all cores) and,
# where the server processes are identifiable, per-process counts. Results: dcperf_default.csv (+ benchpress's own results dir).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; D=/home/hnpark2/prefetchit/benchmarks/dcperf; OUT=$R/dcperf_default.csv
[[ -f $OUT ]] || echo "job,scope,delay_s,l2i,instr,cycles,mpki,ipc,note" > $OUT
export PATH=$R/shim:$PATH
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
run_job() { local job=$1 pat=$2 d1=$3 d2=$4; echo "[$(date +%T)] $job"; cd $D
  (python3 ./benchpress_cli.py run $job > $R/logs/dcperf_$job.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/dcperf_$job.log) & JP=$!
  for delay in $d1 $d2; do sleep $delay; kill -0 $JP 2>/dev/null || { echo "  job ended before ${delay}s"; break; }
    perf stat -x, -o /tmp/dc_sys.csv -e $EV -a -- sleep 30 > /dev/null 2>&1 & P1=$!
    if [[ -n $pat ]]; then pids=$(pgrep -f "$pat" | tr '\n' ',' | sed 's/,$//'); [[ -n $pids ]] && perf stat -x, -o /tmp/dc_proc.csv -e $EV -p $pids -- sleep 30 > /dev/null 2>&1; fi; wait $P1
    rec $job system $delay /tmp/dc_sys.csv "all cores :u"; [[ -n $pat && -n ${pids:-} ]] && rec $job process $delay /tmp/dc_proc.csv "pids matching $pat"
  done; wait $JP; grep -E "JOB_EXIT|score|Score|Throughput|throughput|QPS|qps" $R/logs/dcperf_$job.log | tail -4 | cut -c1-160; }
run_job health_check "" 20 0
run_job django_workload_default "uwsgi" 120 240
run_job feedsim_default "LeafNodeService|feedsim|ParentNode" 300 900
run_job tao_bench_standalone "memcached|tao_bench_server" 180 420
run_job video_transcode_bench_svt "ffmpeg|SvtAv1" 120 300
cd $D; echo "[$(date +%T)] folly_single_core (wdl)"; (python3 ./benchpress_cli.py -b benchpress/config/benchmarks_wdl.yml -j benchpress/config/jobs_wdl.yml run folly_single_core > $R/logs/dcperf_folly.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/dcperf_folly.log) & JP=$!; sleep 60
perf stat -x, -o /tmp/dc_sys.csv -e $EV -a -- sleep 30 > /dev/null 2>&1; rec folly_single_core system 60 /tmp/dc_sys.csv "all cores :u"; wait $JP; tail -3 $R/logs/dcperf_folly.log | cut -c1-160
echo "[$(date +%T)] DCPERF_RUNS_DONE"
