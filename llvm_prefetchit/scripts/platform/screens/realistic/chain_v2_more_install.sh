#!/usr/bin/env bash
# Install the remaining DCPerf v2 packages (root, cores 12-35), one job per package: adsim, cdn_bench(deser_b), gapbs, xsbench, schbench,
# syscall, liblinear, graph500, ucache_bench, silo (if a job exists). Job names/config files are derived from the yml files.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
python3 - > /tmp/v2_more_jobs.txt <<'PY'
import yaml,glob,os
want={'adsim':None,'cdn_bench':None,'gapbs':None,'xsbench':None,'schbench':None,'syscall':None,'liblinear':None,'graph500':None,'ucache_bench':None,'silo':None,'ai_wdl':None}
for jf in glob.glob('benchpress/config/jobs*.yml'):
    bf=jf.replace('jobs','benchmarks')
    try: jobs=yaml.safe_load(open(jf))
    except Exception: continue
    for j in jobs or []:
        b=str(j.get('benchmark',''))
        for w in want:
            if want[w] is None and (b==w or b.startswith(w+'_') or w in b): want[w]=(j['name'],jf,bf if os.path.exists(bf) else 'benchpress/config/benchmarks.yml')
for w,v in want.items(): print(w, *(v if v else ('-', '-', '-')))
PY
cat /tmp/v2_more_jobs.txt
while read -r pkg job jf bf; do [[ $job == - ]] && { echo "[$(date +%T)] $pkg: no job"; continue; }
  echo "[$(date +%T)] install $pkg ($job via $jf)"
  echo ps101899 | sudo -S -p '' env PATH=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918/shim:$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages DEBIAN_FRONTEND=noninteractive timeout 5400 taskset -c 12-35 python3 ./benchpress_cli.py -b $bf -j $jf install $job > $R/logs/v2_install_$pkg.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
  grep -vE "^\+ |^\s*$|Traceback|File \"|raise |invoke_main|main\(\)|\^\^\^" $R/logs/v2_install_$pkg.log | grep -iE "error:|Error [0-9]|fatal|No such|undefined reference|E: " | tail -2 | cut -c1-180
done < /tmp/v2_more_jobs.txt
echo ps101899 | sudo -S -p '' chown -R hnpark2:hnpark2 $V /home/hnpark2/prefetchit/benchmarks/dcperf/.git/worktrees 2>/dev/null; cat $V/benchmark_installs.txt; echo "[$(date +%T)] V2_MORE_INSTALL_DONE"
