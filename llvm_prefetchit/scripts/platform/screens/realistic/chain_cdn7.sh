#!/usr/bin/env bash
# cdn_bench on non-default ports (9082/9081): run.sh's startup sweep kills any listener on 8081/8082, which killed our co-located server.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN6_DONE $R/logs/chain_cdn6.log 2>/dev/null; do sleep 30; done
BHOST=127.0.0.1 CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN7_DONE"
