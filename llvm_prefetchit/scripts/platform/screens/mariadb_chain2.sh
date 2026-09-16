#!/usr/bin/env bash
set -u
P=/home/hnpark2/prefetchit/benchmarks/mariadb/mariadb_pipeline.sh
export SERVER_CORES=64-67 CLIENT_CORES=68-71
$P trace 2>&1 | tail -12
COV=90 $P plan 2>&1 | tail -2
/home/hnpark2/prefetchit/benchmarks/mariadb/mariadb_split.sh 2>&1 | grep -E "tps=|SPLIT"
echo MARIADB_CHAIN2_DONE
