#!/usr/bin/env bash
# Install the DCPerf benchmarks that were never installed (tao_bench, video_transcode_bench, wdl_bench); builds on cores 12-35.
# spark_standalone is skipped (needs >= 500 GB of data-node storage).
D=/home/hnpark2/prefetchit/benchmarks/dcperf; L=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918/logs; cd $D; export PATH=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918/shim:$PATH DEBIAN_FRONTEND=noninteractive
inst() { local b=$1; shift; echo "[$(date +%T)] install $b"; taskset -c 12-35 python3 ./benchpress_cli.py "$@" > $L/install_$b.log 2>&1; echo "  exit=$? dir=$(ls -d benchmarks/$b 2>/dev/null) free=$(df --output=avail -BG / | tail -1)"; }
ac_cv_func_arc4random=no ac_cv_func_arc4random_buf=no ac_cv_func_arc4random_addrandom=no inst tao_bench install tao_bench_standalone
inst video_transcode_bench install video_transcode_bench_svt
inst wdl_bench -b benchpress/config/benchmarks_wdl.yml -j benchpress/config/jobs_wdl.yml install folly_single_core
echo "[$(date +%T)] DCPERF_INSTALL_DONE"
