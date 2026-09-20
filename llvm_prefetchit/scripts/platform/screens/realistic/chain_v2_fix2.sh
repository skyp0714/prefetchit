#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
for pkg in gapbs graph500; do read -r _ job jf bf < <(grep "^$pkg " /tmp/v2_more_jobs.txt); echo "[$(date +%T)] install $pkg ($job via $jf)"
  echo ps101899 | sudo -S -p '' env PATH=$R/shim:$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages DEBIAN_FRONTEND=noninteractive timeout 3600 taskset -c 12-35 python3 ./benchpress_cli.py -b $bf -j $jf install $job > $R/logs/v2_install_${pkg}_retry2.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
  grep -vE "^\+ |^\s*$|Traceback|File \"|raise |invoke_main|main\(\)|\^\^\^|^W: " $R/logs/v2_install_${pkg}_retry2.log | grep -iE "error:|Error [0-9]|fatal|No such|undefined reference|E: " | tail -2 | cut -c1-180
done
echo ps101899 | sudo -S -p '' chown -R hnpark2:hnpark2 $V 2>/dev/null; ls $V/benchmarks/gapbs_bc $V/benchmarks/graph500_omp_csr 2>&1 | head -8; echo "[$(date +%T)] V2_FIX2_DONE"
