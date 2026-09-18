#!/usr/bin/env bash
# End of campaign: socialNetwork again with a 43-core pool (0-42) so nginx is not the limiter; fresh stack via reset_sn_stack.sh.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink
until grep -q DCPERF_CHAIN_DONE $R/logs/chain_dcperf.log 2>/dev/null; do sleep 60; done
echo "[$(date +%T)] socialNetwork up (fresh)"; $PL/reset_sn_stack.sh > $R/logs/sn2_reset.log 2>&1; tail -2 $R/logs/sn2_reset.log | cut -c1-120
POOL=0-42 FECAP=20 R0=6000 $R/dsb_realistic_screen_v2.sh $R/dsb_social_pool43.csv 6000 8000 10000 12000 14000 2>&1 | grep -vE "^\s*$"
echo "[$(date +%T)] SN2_CHAIN_DONE"
