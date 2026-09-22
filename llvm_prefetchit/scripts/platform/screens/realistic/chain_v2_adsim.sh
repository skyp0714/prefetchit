#!/usr/bin/env bash
# adsim retry after disabling folly's io_uring (host liburing/kernel headers lack zcrx). Waits for the gapbs/graph500 reinstall to finish.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
until grep -q V2_FIX2_DONE $R/logs/chain_v2_fix2.log 2>/dev/null; do sleep 30; done
read -r _ job jf bf < <(grep "^adsim " /tmp/v2_more_jobs.txt); echo "[$(date +%T)] install adsim ($job via $jf)"
echo ps101899 | sudo -S -p '' env PATH=$R/shim:$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages DEBIAN_FRONTEND=noninteractive timeout 9000 taskset -c 12-35 python3 ./benchpress_cli.py -b $bf -j $jf install $job > $R/logs/v2_install_adsim_retry8.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
grep -vE "^\+ |^\s*$|Traceback|File \"|raise |invoke_main|main\(\)|\^\^\^|^W: " $R/logs/v2_install_adsim_retry8.log | grep -iE "error:|Error [0-9]|fatal|No such|undefined reference|E: " | tail -3 | cut -c1-180
echo ps101899 | sudo -S -p '' chown -R hnpark2:hnpark2 $V 2>/dev/null; ls $V/benchmarks/adsim 2>&1 | head -6; echo "[$(date +%T)] V2_ADSIM7_DONE"
