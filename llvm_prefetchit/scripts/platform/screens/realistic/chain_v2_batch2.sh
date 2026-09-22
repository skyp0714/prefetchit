#!/usr/bin/env bash
# Second batch pass: jobs that live in jobs_mem.yml / jobs_system.yml need -b/-j (benchpress only loads jobs.yml by default).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; S=$R/dcperf_v2_batch.sh
until grep -q V2_BATCH_DONE $R/logs/chain_v2_batch.log 2>/dev/null; do sleep 20; done
grep -q 'CFG=()' $S || sed -i 's|^JOB=\$1; CORES=\$2; D1=\$3; D2=\$4; shift 4; EXTRA=("\$@"); WIN=\${WIN:-20}$|JOB=$1; CORES=$2; D1=$3; D2=$4; shift 4; EXTRA=("$@"); WIN=${WIN:-20}; CFG=(); [[ -n $JY ]] \&\& CFG=(-b benchpress/config/$BY -j benchpress/config/$JY)|; s|python3 ./benchpress_cli.py run \$JOB|python3 ./benchpress_cli.py "${CFG[@]}" run $JOB|' $S
bash -n $S || { echo "batch script broken"; exit 1; }
JY=jobs_mem.yml BY=benchmarks_mem.yml timeout 1500 bash $S xsbench 8-11 20 60 -i '{"thread_cnt": "4"}'
JY=jobs_system.yml BY=benchmarks_system.yml timeout 900 bash $S syscall_single_core 8-11 15 40
JY=jobs_system.yml BY=benchmarks_system.yml timeout 900 bash $S schbench_default 8-11 10 30
echo "[$(date +%T)] V2_BATCH2_DONE"
