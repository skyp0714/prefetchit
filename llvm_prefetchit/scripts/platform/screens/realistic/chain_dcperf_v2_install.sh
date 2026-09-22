#!/usr/bin/env bash
# DCPerf v2 installs (worktree benchmarks/dcperf_v2 = origin/v2-beta b109b09). v2 installers call apt / write /usr/local and /data
# directly (they assume root), so each install runs under sudo -E; the tree is chown'ed back afterwards. Builds on cores 12-35.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
for job in feedsim_dlrm tao_bench_standalone; do
  echo "[$(date +%T)] install $job"
  echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages DEBIAN_FRONTEND=noninteractive taskset -c 12-35 python3 ./benchpress_cli.py install $job > $R/logs/v2_install_$job.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
  grep -vE "^\+ |^\s*$|Traceback|File \"|raise |invoke_main|main\(\)|\^\^\^" $R/logs/v2_install_$job.log | grep -iE "error|fail|not found|No such" | tail -3 | cut -c1-200
done
echo ps101899 | sudo -S -p '' chown -R hnpark2:hnpark2 $V /home/hnpark2/prefetchit/benchmarks/dcperf/.git/worktrees 2>/dev/null
cat $V/benchmark_installs.txt 2>/dev/null; echo "[$(date +%T)] V2_INSTALL_DONE"
