#!/usr/bin/env bash
set -u
until grep -q "ROCKS BUILD DONE" /tmp/rocksdb_build.log; do sleep 20; done
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
DB=benchmarks/third_party/rocksdb/db_bench; [[ -x $DB ]] || { echo "no db_bench"; exit 0; }
rm -rf /tmp/rocksdb_data; $DB --benchmarks=fillrandom --num=5000000 --db=/tmp/rocksdb_data --value_size=100 > /tmp/rocks_fill.log 2>&1
CORE=46 bash $S rocksdb_readrandom_5M $PWD "$DB --benchmarks=readrandom,readwhilewriting --use_existing_db=1 --num=5000000 --reads=20000000 --db=/tmp/rocksdb_data --threads=1 --cache_size=268435456" 150
echo ROCKS_CHAIN_DONE
