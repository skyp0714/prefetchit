#!/usr/bin/env bash
# MariaDB durable config (user MPKI 3.2): traces → PGO plan + static plan → builds → A/B (tps) with the durable server flags
set -u
P=/home/hnpark2/prefetchit/benchmarks/mariadb/mariadb_pipeline.sh; R=/home/hnpark2/prefetchit/llvm_prefetchit/results/mariadb_20260916; M=/home/hnpark2/prefetchit/benchmarks/mariadb
export SERVER_CORES=64-67 CLIENT_CORES=68-71 OUT=$R/durable
export SERVER_EXTRA_ARGS="--innodb-flush-log-at-trx-commit=1 --log-bin=mariadb-bin --sync-binlog=1 --innodb-flush-method=fsync"
$P trace 2>&1 | grep -E "samples|'RET'|'COND'|cumulative" | cut -c1-160
COV=90 $P plan 2>&1 | tail -1
python3 /home/hnpark2/prefetchit/static_prefetch/tools/static_plan.py --binary $M/install_base/bin/mariadbd --kinds ret,cond --out-dir $OUT/plans/static_work --output $OUT/plans/static_retcond.plan.json --label static_retcond > $OUT/plans/static.log 2>&1 || tail -2 $OUT/plans/static.log
echo "static plan: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']))" $OUT/plans/static_retcond.plan.json 2>/dev/null) injections"
VARIANT=pgo_cov90 PLAN=$OUT/plans/pgo_cov90.plan.json $P build 2>&1 | tail -2
VARIANT=static_retcond PLAN=$OUT/plans/static_retcond.plan.json $P build 2>&1 | tail -2
VARIANTS="pgo_cov90 static_retcond" REPS=3 DUR=40 $P measure 2>&1 | tail -10
echo MARIADB_DURABLE_DONE
