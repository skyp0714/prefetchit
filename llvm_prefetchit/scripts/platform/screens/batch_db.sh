#!/usr/bin/env bash
set -u
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
CORE=44 bash $S clickhouse_local_analytics /tmp/screen_inputs/ch "$PWD/benchmarks/tools/clickhouse/clickhouse local --queries-file q.sql --max_threads=1" 150
CORE=44 bash $S duckdb_tpch_sf2 /tmp/screen_inputs/duck "python3 tpch.py" 150
CORE=44 bash $S ghdl_neorv32_tb /home/hnpark2/prefetchit/benchmarks/neorv32/sim "bash ghdl.sh --stop-time=20ms" 150
echo BATCH_DB_DONE
