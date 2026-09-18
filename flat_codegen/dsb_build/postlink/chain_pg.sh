#!/usr/bin/env bash
# Test 2b — generalization to PostgreSQL 16 (C, multi-process, one PIE link unit + libc; screened 6.0 → 0.1 MPKI shared → isolated).
# LBR + rate traces of the base backends → plan v4 (local functions via file-qualified sites/aliases) → build → instr profile → v10 → A/B.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; PGD=/home/hnpark2/prefetchit/benchmarks/pg; cd $PL
until grep -q CHAIN_CPS_DONE logs/chain_cps.log 2>/dev/null; do sleep 15; done
BASE=$PGD/install_base/bin/postgres
echo "[$(date +%T)] PG traces (base)"; MODE=lbr $PGD/pg_cold_trace.sh $BASE results/pg_trace_lbr 2>&1 | grep -E "lbr:|tps=" | cut -c1-200; MODE=rate $PGD/pg_cold_trace.sh $BASE results/pg_trace_rate 2>&1 | grep -E "rate:|tps=" | cut -c1-200
TPS=$(cut -d= -f2 results/pg_trace_rate/tps.txt); HZ=$(python3 -c "print(int(7*float('$TPS' or 0)))"); echo "ref hz (7 statements x tps): $HZ"
nm --defined-only $BASE | awk '$2 ~ /^[TtWw]$/ {print $3}' | sort -u > $DB/plans/pg_instrumentable.txt
COMMON="results/pg_trace_lbr $BASE /lib/x86_64-linux-gnu/libc.so.6 $DB/plans/pg_instrumentable.txt"; OPTS="--fallback --drop-own-line0 --rates results/pg_trace_rate/rates.txt --rate-ref-pattern exec_execute_message --rate-ref-hz $HZ --max-cost 20 --exe-suffix /bin/postgres --local-aliases"
python3 cold_plan.py $COMMON $DB/plans/pg_plan_v4.json $OPTS 2>&1 | tee results/pg_trace_lbr/plan_stats_v4.txt | grep -E "samples=|local|cost|drop" | cut -c1-220
echo "[$(date +%T)] PG build plan4"; $PGD/build_pg_variant.sh plan4 "PREFETCHIT_COLD_PLAN=$DB/plans/pg_plan_v4.json" 2>&1 | tail -4 | cut -c1-200
[[ -f $PGD/install_plan4/bin/postgres.nop ]] || { echo "PLAN4 BUILD FAILED"; echo "[$(date +%T)] CHAIN_PG_DONE"; exit 1; }
echo "[$(date +%T)] PG instruction profile of plan4"; MODE=instr $PGD/pg_cold_trace.sh $PGD/install_plan4/bin/postgres results/pg_prof_plan4 2>&1 | grep -E "instr:" | cut -c1-200
python3 cold_plan.py $COMMON $DB/plans/pg_plan_v10.json $OPTS --site-exec results/pg_prof_plan4/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/pg_trace_lbr/plan_stats_v10.txt | grep -E "samples=|measured" | cut -c1-220
echo "[$(date +%T)] PG build plan10"; $PGD/build_pg_variant.sh plan10 "PREFETCHIT_COLD_PLAN=$DB/plans/pg_plan_v10.json" 2>&1 | tail -3 | cut -c1-200
rm -rf $PGD/install_plan10_nop; cp -a $PGD/install_plan10 $PGD/install_plan10_nop; mv $PGD/install_plan10_nop/bin/postgres.nop $PGD/install_plan10_nop/bin/postgres
ARMS="base=$BASE plan4=$PGD/install_plan4/bin/postgres plan10=$PGD/install_plan10/bin/postgres plan10_nop=$PGD/install_plan10_nop/bin/postgres"
echo "[$(date +%T)] PG A/B arms: $ARMS"; rm -rf results/pg_round1; $PGD/pg_ab.sh results/pg_round1 3 $ARMS > logs/pg_round1.log 2>&1; grep -E " r[0-9]:" logs/pg_round1.log | cut -c1-160
echo "[$(date +%T)] PG miss profile of plan10 vs twin"; MODE=miss $PGD/pg_cold_trace.sh $PGD/install_plan10_nop/bin/postgres results/pg_miss_plan10nop 2>&1 | grep "miss:" | cut -c1-200; MODE=miss $PGD/pg_cold_trace.sh $PGD/install_plan10/bin/postgres results/pg_miss_plan10 2>&1 | grep "miss:" | cut -c1-200
EXE_SUFFIX=/bin/postgres python3 cold_target_analysis.py $PGD/install_plan10/bin/postgres results/pg_miss_plan10nop results/pg_miss_plan10 > results/target_analysis_pg_plan10.txt 2>&1; sed -n 1,4p results/target_analysis_pg_plan10.txt | cut -c1-200; grep -E "residual|waste" results/target_analysis_pg_plan10.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_PG_DONE"
