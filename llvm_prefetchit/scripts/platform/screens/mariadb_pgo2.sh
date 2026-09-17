#!/usr/bin/env bash
set -u
P=/home/hnpark2/prefetchit/benchmarks/mariadb/mariadb_pipeline.sh; R=/home/hnpark2/prefetchit/llvm_prefetchit/results/mariadb_20260916
export SERVER_CORES=64-67 CLIENT_CORES=68-71 OUT=$R/durable
export SERVER_EXTRA_ARGS="--innodb-flush-log-at-trx-commit=1 --log-bin=mariadb-bin --sync-binlog=1 --innodb-flush-method=fsync"
PREFETCHIT_SKIP_PIC=1 VARIANT=pgo_cov90 PLAN=$OUT/plans/pgo_cov90f.plan.json $P build 2>&1 | grep -vE "^\[sudo" | tail -3
ls /home/hnpark2/prefetchit/benchmarks/mariadb/install_pgo_cov90/bin/mariadbd || { echo "BUILD FAILED"; grep -B4 -m1 "linker command failed" /home/hnpark2/prefetchit/benchmarks/mariadb/build_pgo_cov90/make.log | cut -c1-200; echo MARIADB_PGO2_DONE; exit 0; }
rm -f $OUT/measure/runs.csv
VARIANTS="pgo_cov90" REPS=3 DUR=40 $P measure 2>&1 | grep -vE "^\[sudo" | tail -14
echo MARIADB_PGO2_DONE
