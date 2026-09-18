#!/usr/bin/env bash
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; cd $PL/coldscreen
true
echo "[$(date +%T)] pg trace"; STEP=trace $PL/pg_wake_pipeline.sh > pg_trace.log 2>&1; tail -7 pg_trace.log
echo "[$(date +%T)] pg ab"; STEP=ab REPS=3 $PL/pg_wake_pipeline.sh > pg_ab.log 2>&1; grep -E " r[0-9]:" pg_ab.log
echo "[$(date +%T)] PG_CHAIN_DONE"
