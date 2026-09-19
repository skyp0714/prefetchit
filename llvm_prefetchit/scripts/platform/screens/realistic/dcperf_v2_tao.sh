#!/usr/bin/env bash
# TaoBench (DCPerf v2) pinned: servers under taskset on CORES (job auto-sizes to the affinity), client commands parsed from benchpress.log
# and run locally on 60-67; server user-mode L2I MPKI / IPC at two points. Usage: dcperf_v2_tao.sh CORES
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; OUT=$R/dcperf_v2.csv; CORES=$1
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))"); EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'
[[ -f $OUT ]] || echo "job,config,group,cores,delay_s,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
cd $V; L0=$(wc -l < benchpress.log)
(echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages taskset -c $CORES python3 ./benchpress_cli.py run tao_bench_standalone > $R/logs/v2_run_tao_default.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/v2_run_tao_default.log) & JP=$!
for i in $(seq 1 60); do tail -n +$L0 benchpress.log | grep -q "tao_bench_custom -r client" && break; sleep 3; done
tail -n +$L0 benchpress.log | grep -oE "\./benchpress_cli\.py run tao_bench_custom -r client -i '[^']*'" | sort -u > /tmp/tao_v2_clients.txt; echo "client commands: $(wc -l < /tmp/tao_v2_clients.txt)"; cat /tmp/tao_v2_clients.txt | cut -c1-200
n=0; while read -r cmd; do n=$((n+1)); (cd $V && eval "taskset -c 60-67 $cmd" > $R/logs/v2_tao_client$n.log 2>&1) & sleep 1; done < /tmp/tao_v2_clients.txt
for delay in 240 480; do sleep $((delay - (n>0 ? 0 : 0) )); kill -0 $JP 2>/dev/null || { echo "job ended before ${delay}s"; break; }
  sp=$(pgrep -f "^$V/benchmarks/tao_bench/" | tr '\n' ',' | sed 's/,$//'); [[ -z $sp ]] && sp=$(pgrep -f "^memcached" | tr '\n' ',' | sed 's/,$//'); [[ -z $sp ]] && { echo "no server pids"; ps -eo pid,pcpu,args --sort=-pcpu | head -6 | cut -c1-120; continue; }
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/v2_tao.csv -e $EV -p $sp -- sleep 30 > /dev/null 2>&1
  python3 - $CORES $NC $delay $OUT <<'PY'
import csv,sys
cores,nc,delay,out=sys.argv[1:5]; v={}
for r in csv.reader(open('/tmp/v2_tao.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(30000*int(nc))
open(out,'a').write(f"tao_bench_standalone,default,server,{cores},{delay},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"tao_bench_standalone [default] server @{delay}s: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
done; wait $JP; grep -E "total_qps|fast_qps|hit_ratio|JOB_EXIT" $R/logs/v2_run_tao_default.log | head -4 | tr -d '\t' | tr '\n' ' '; echo; echo "V2_TAO_DONE"
