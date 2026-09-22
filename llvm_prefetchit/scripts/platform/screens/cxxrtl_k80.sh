#!/usr/bin/env bash
set -u
ROOT=/home/hnpark2/prefetchit; LLVM=$ROOT/llvm_prefetchit; SRC=/tmp/screen_inputs/cxxrtl; OUT=$LLVM/results/pgo_static_20260916/cxxrtl; CORE=44; CYC=300000; PLUGIN=$LLVM/build/PrefetchITPass.so; YINC=/usr/share/yosys/include
log(){ echo "[$(date '+%T')] [cxxrtl-k80] $*" | tee -a $OUT/run.log; }
( cd $SRC && env PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=80 PREFETCHIT_SEQ_FUNCTIONS='.*' clang++-19 -O2 -g -std=c++17 -I$YINC -I$YINC/backends/cxxrtl/runtime -fpass-plugin=$PLUGIN main.cc -o $OUT/bin/seq_d4096_k80 2> $OUT/build_seq_d4096_k80.err )
log "seq_d4096_k80: $(llvm-objdump-19 -d $OUT/bin/seq_d4096_k80 | grep -cE 'prefetcht[012]') prefetches"; python3 $LLVM/tools/make_nop_control_binary.py --input $OUT/bin/seq_d4096_k80 --output $OUT/bin/seq_d4096_k80_nop > /dev/null 2>&1
while pgrep -x clang++-19 >/dev/null || pgrep -x clang-19 >/dev/null || pgrep -f "runcpu.*action=build" >/dev/null; do sleep 30; done; exec 9>/tmp/measure.lock; flock 9
CSV=$OUT/measure/runs.csv
run1(){ local v=$1 rep=$2 b=$OUT/bin/$1; local s e; s=$(date +%s.%N); (cd $SRC && taskset -c $CORE perf stat -x, -o $OUT/measure/${v}_r$rep.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- $b $CYC > $OUT/measure/${v}_r$rep.log 2>&1); e=$(date +%s.%N)
  python3 - $CSV $v $rep $s $e $OUT/measure/${v}_r$rep.csv <<'PY'
import csv,sys
out,v,rep,s,e,p=sys.argv[1:]; ev={}
for row in csv.reader(open(p)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0); el=float(e)-float(s)
csv.writer(open(out,"a",newline="")).writerow([v,rep,f"{el:.3f}",int(i),int(c),int(m),f"{1000*m/i if i else 0:.3f}",f"{i/c if c else 0:.3f}"])
print(f"{v} rep{rep}: {el:.2f}s MPKI={1000*m/i if i else 0:.2f}")
PY
}
for rep in 4 5 6; do for v in base seq_d4096_k80 seq_d4096_k80_nop; do run1 $v $rep | tee -a $OUT/run.log; done; done
python3 $LLVM/results/pgo_static_20260916/summarize.py | grep -E "CXXRTL|workload"
echo CXXRTL_K80_DONE
