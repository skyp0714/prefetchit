#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
echo ps101899 | sudo -S -p '' env DEBIAN_FRONTEND=noninteractive apt-get install -y libdb5.3++t64 > /dev/null 2>&1; ls /usr/lib/x86_64-linux-gnu/ | grep -c "libdb_cxx-5.3.so"
CORES=0-3 timeout 7200 bash $R/tailbench_screen.sh; echo "[$(date +%T)] TB_CHAIN_DONE"
