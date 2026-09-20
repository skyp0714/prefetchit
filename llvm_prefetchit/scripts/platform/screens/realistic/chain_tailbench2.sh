#!/usr/bin/env bash
# TailBench recovery: the first extraction ran into the full disk (sphinx 61 and xapian 6 zero-length files → DatabaseCorruptError /
# decoder abort). Re-download the inputs, re-extract only sphinx and xapian, then screen silo (lz4 shim), sphinx and xapian on 0-3.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; TB=/home/hnpark2/prefetchit/benchmarks/tailbench; cd $TB
rm -rf tailbench.inputs/sphinx tailbench.inputs/xapian; df -h / | awk 'NR==2{print "free before download",$4}'
timeout 7200 curl -sSL -o tailbench.inputs.tgz https://tailbench.csail.mit.edu/tailbench.inputs.tgz; echo "download rc=$? size=$(stat -c %s tailbench.inputs.tgz 2>/dev/null)"
tar xzf tailbench.inputs.tgz tailbench.inputs/sphinx tailbench.inputs/xapian; echo "extract rc=$?"; rm -f tailbench.inputs.tgz
echo "sphinx zero=$(find tailbench.inputs/sphinx -type f -size 0 | wc -l) xapian zero=$(find tailbench.inputs/xapian -type f -size 0 | wc -l)"; df -h / | awk 'NR==2{print "free after",$4}'
ONLY="silo sphinx xapian" CORES=0-3 timeout 5400 bash $R/tailbench_screen.sh; echo "[$(date +%T)] TB2_DONE"
