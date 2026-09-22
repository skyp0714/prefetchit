#!/usr/bin/env bash
# clean MariaDB pass on quiet cores: user/kernel split → fresh traces → PGO plan → pass build → A/B
set -u
until grep -q DSBDSO_DONE /tmp/dsb_dso2.log; do sleep 15; done
while docker ps --format '{{.Names}}' | grep -q '^socialnetwork-'; do sleep 10; done
P=/home/hnpark2/prefetchit/benchmarks/mariadb/mariadb_pipeline.sh; M=/home/hnpark2/prefetchit/benchmarks/mariadb; R=/home/hnpark2/prefetchit/llvm_prefetchit/results/mariadb_20260916
export SERVER_CORES=64-67 CLIENT_CORES=68-71
$M/mariadb_split.sh 2>&1 | grep -E "tps=|SPLIT"
rm -rf $R/traces $R/plans $R/diag
$P trace 2>&1 | grep -E "samples|'RET'|'COND'|cumulative" | cut -c1-200
COV=90 $P plan 2>&1 | tail -1
VARIANT=pgo_cov90 PLAN=$R/plans/pgo_cov90.plan.json $P build 2>&1 | tail -3
VARIANTS="pgo_cov90" REPS=3 DUR=40 $P measure 2>&1 | tail -8
echo MARIADB_FINAL_DONE
