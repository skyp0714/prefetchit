#!/usr/bin/env bash
# Retry the DCPerf v2 installs that failed in chain_v2_more_install (gapbs/graph500: dnf guard patched; adsim: /usr/bin/clang{,++} symlinks;
# cdn_bench: asBodyEv shim for the pinned proxygen). Waits for V2_MORE_INSTALL_DONE so benchmark_installs.txt is not written concurrently.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
until grep -q V2_MORE_INSTALL_DONE $R/logs/chain_v2_more_install.log; do sleep 60; done
for pkg in gapbs graph500 adsim cdn_bench; do read -r _ job jf bf < <(grep "^$pkg " /tmp/v2_more_jobs.txt); [[ -z $job || $job == - ]] && { echo "$pkg: no job row"; continue; }
  echo "[$(date +%T)] install $pkg ($job via $jf)"
  echo ps101899 | sudo -S -p '' env PATH=$R/shim:$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages DEBIAN_FRONTEND=noninteractive timeout 7200 taskset -c 12-35 python3 ./benchpress_cli.py -b $bf -j $jf install $job > $R/logs/v2_install_${pkg}_retry.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
  grep -vE "^\+ |^\s*$|Traceback|File \"|raise |invoke_main|main\(\)|\^\^\^" $R/logs/v2_install_${pkg}_retry.log | grep -iE "error:|Error [0-9]|fatal|No such|undefined reference|E: " | tail -2 | cut -c1-180
done
echo ps101899 | sudo -S -p '' chown -R hnpark2:hnpark2 $V /home/hnpark2/prefetchit/benchmarks/dcperf/.git/worktrees 2>/dev/null; cat $V/benchmark_installs.txt; echo "[$(date +%T)] V2_FIX_INSTALL_DONE"
