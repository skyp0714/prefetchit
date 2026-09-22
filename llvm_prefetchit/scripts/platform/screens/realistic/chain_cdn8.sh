#!/usr/bin/env bash
# cdn_bench at realistic proxy utilization: the default client (4 conns x 100 streams, 2 threads) left the proxy at 1-4% of 4 cores.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN7_DONE $R/logs/chain_cdn7.log 2>/dev/null; do sleep 30; done
RPS_LIST="40000 120000 300000" CCONN=32 CSTREAMS=100 CTHR=8 BHOST=127.0.0.1 CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN8_DONE"
