#!/usr/bin/env bash
# Chain v13: redis-plus-plus 1.2.3 (C++14 ABI, DSB patch) layer -> deps g/b3/seq images -> service builds -> round4
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $DB
docker build -f Dockerfile.deps4 -t dsb-deps-jammy . > $PL/logs/deps4_build.log 2>&1; echo "[$(date +%T)] deps4 layer exit $?"
rm -rf $PL/results/round4 out_utl_* libs_utl_*
bash $PL/chain_night10.sh
echo "[$(date +%T)] CHAIN13_DONE"
