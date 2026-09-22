#!/usr/bin/env bash
# FleetBench (Google): build the proto/swissmap/hashing/compression/rpc/libc/stl/tcmalloc benchmarks with Bazel (cores 12-35, after the
# DCPerf installs), then screen each pinned to one core (C6 off) with user-mode L2I MPKI over a 20 s window.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; F=/home/hnpark2/prefetchit/benchmarks/fleetbench; export PATH=/home/hnpark2/.local/bin:$PATH
until grep -q V2_MORE_INSTALL_DONE $R/logs/chain_v2_more_install.log 2>/dev/null; do sleep 60; done
cd $F; echo "[$(date +%T)] bazel build"; timeout 5400 taskset -c 12-35 bazel build -c opt --jobs=24 //fleetbench/proto:proto_benchmark //fleetbench/swissmap:swissmap_benchmark //fleetbench/hashing:hashing_benchmark //fleetbench/compression:compression_benchmark //fleetbench/libc:mem_benchmark //fleetbench/stl:cord_benchmark //fleetbench/rpc:rpc_benchmark //fleetbench/tcmalloc:empirical_driver > $R/logs/fleetbench_build.log 2>&1; echo "  build exit=$?"; grep -E "ERROR|error:" $R/logs/fleetbench_build.log | head -3 | cut -c1-200
OUT=$R/fleetbench.csv; [[ -f $OUT ]] || echo "bench,cores,config,l2i,instr,cycles,mpki,ipc" > $OUT
cst() { local mode=$1; for st in /sys/devices/system/cpu/cpu36/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; }
cst 1; for b in proto/proto_benchmark swissmap/swissmap_benchmark hashing/hashing_benchmark compression/compression_benchmark libc/mem_benchmark stl/cord_benchmark rpc/rpc_benchmark tcmalloc/empirical_driver; do
  bin=$F/bazel-bin/fleetbench/$b; [[ -x $bin ]] || { echo "$b: not built"; continue; }
  taskset -c 36 $bin --benchmark_min_time=60s > /tmp/fb_$(basename $b).log 2>&1 & bp=$!; sleep 15; kill -0 $bp 2>/dev/null || { echo "$b ended early"; tail -2 /tmp/fb_$(basename $b).log | cut -c1-120; continue; }
  perf stat -x, -o /tmp/fb_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u' -p $bp -- sleep 20 > /dev/null 2>&1; kill $bp 2>/dev/null; sleep 1; kill -9 $bp 2>/dev/null
  python3 - $b $OUT <<'PY'
import csv,sys; v={}
for r in csv.reader(open('/tmp/fb_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0)
open(sys.argv[2],'a').write(f"fleetbench/{sys.argv[1]},36,1core_C6off,{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"fleetbench/{sys.argv[1]}: MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
done; cst 0; echo "[$(date +%T)] FLEETBENCH_DONE"
