#!/usr/bin/env bash
# cdn_bench with IPv6 loopback targets: content_server/proxy_server only answer on ::1 (run.sh's nc check on 127.0.0.1 fails).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN5_DONE $R/logs/chain_cdn5.log 2>/dev/null; do sleep 30; done
BHOST=::1 CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN6_DONE"
