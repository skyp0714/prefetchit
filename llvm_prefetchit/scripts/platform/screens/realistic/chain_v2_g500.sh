#!/usr/bin/env bash
# graph500 rerun: benchpress runs as root and Open MPI refuses root without OMPI_ALLOW_RUN_AS_ROOT*. After the cdn_bench screen (cores 8-11).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN3_DONE $R/logs/chain_cdn3.log 2>/dev/null; do sleep 60; done
EXTRA_ENV="OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 TMPDIR=/tmp" WIN=15 timeout 1800 bash $R/dcperf_v2_batch.sh graph500_omp_csr 8-11 20 60 -i '{"scale": "24"}'
echo "[$(date +%T)] G500_DONE"
