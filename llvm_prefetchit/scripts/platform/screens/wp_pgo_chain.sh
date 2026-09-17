#!/usr/bin/env bash
set -u
until grep -q "rc=0" /tmp/php_build_base.log; do grep -q "rc=[1-9]" /tmp/php_build_base.log && { echo "PHP BASE BUILD FAILED"; echo WP_PGO_DONE; exit 0; }; sleep 30; done
W=/home/hnpark2/prefetchit/benchmarks/php/wp_pipeline.sh; O=/home/hnpark2/prefetchit/llvm_prefetchit/results/pgo_static_20260916/wordpress
$W trace 2>&1 | tail -6
$W plan 2>&1 | tail -2
VARIANT=pgo_cov90 PLAN=$O/plans/pgo_cov90.plan.json $W build 2>&1 | tail -3
VARIANTS="pgo_cov90" $W measure 2>&1 | tail -12
echo WP_PGO_DONE
