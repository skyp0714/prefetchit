#!/usr/bin/env bash
# Build Router leaf + mid-tier with clang-19 and the PrefetchIT pass plan-free modes; variants: base, seq_t1, seq_it1 (+ NOP twins).
# Output: MicroSuite/variants/<variant>/{lookup_server,mid_tier_server}
set -u
S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; V=/home/hnpark2/prefetchit/benchmarks/MicroSuite/variants; P=/home/hnpark2/prefetchit/llvm_prefetchit/build/PrefetchITPass.so
NOP=/home/hnpark2/prefetchit/llvm_prefetchit/tools/make_nop_control_binary.py; CLANG="/opt/llvm-19.1.7/bin/clang++ -I/usr/lib/gcc/x86_64-linux-gnu/11/include -fopenmp=libgomp"
SEQ="PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=20 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=4 PREFETCHIT_CALLEE_BURST_LEAD=40"
build(){ local var=$1 envs=$2 pf=$3; mkdir -p $V/$var
  for t in lookup_service/service:lookup_server mid_tier_service/service:mid_tier_server; do d=${t%%:*}; b=${t#*:}
    (cd $S/Router/$d && make clean > /dev/null 2>&1; env $envs make -j8 CXX="$CLANG -g $pf" > $V/$var.$b.log 2>&1 && cp $b $V/$var/$b) || { echo "$var/$b FAILED: $(grep -m1 error $V/$var.$b.log | cut -c1-120)"; continue; }
    n=$(objdump -d $V/$var/$b | grep -cE "prefetcht1|prefetchit"); echo "$var/$b: $n prefetches"
    if [[ $n -gt 0 ]]; then mkdir -p $V/${var}_nop; python3 $NOP --input $V/$var/$b --output $V/${var}_nop/$b > /dev/null && chmod +x $V/${var}_nop/$b; fi
  done; }
# (base, seq_t1, seq_it1, seq_it0 already built)



COLD="PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24"
build cold "$COLD" "-fpass-plugin=$P"
build cold_seq "$COLD $SEQ PREFETCHIT_SEQ_MNEMONIC=prefetcht1" "-fpass-plugin=$P"
(cd $S/Router/lookup_service/service && make clean > /dev/null 2>&1; make -j8 > /dev/null 2>&1); (cd $S/Router/mid_tier_service/service && make clean > /dev/null 2>&1; make -j8 > /dev/null 2>&1)
echo ROUTER_VARIANTS_DONE
