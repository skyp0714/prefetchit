#!/usr/bin/env bash
# DaCapo 23.11 Chopin + Renaissance 0.16.1 on N pinned cores (JVM sizes its pools from the affinity mask), fixed heap, JDK 21.
# Per benchmark: user-mode L2I MPKI / IPC over a 20 s window after DELAY s (steady state), then the run is stopped.
# Usage: CORES=8-11 HEAP=8g jvm_realistic_screen.sh OUT.csv [dacapo|renaissance|both]
CORES=${CORES:-8-11}; HEAP=${HEAP:-8g}; ONLY=${ONLY:-}; JVMFLAGS=${JVMFLAGS:-}; DELAY=${DELAY:-40}; WIN=${WIN:-20}; WHICH=${2:-both}; OUT=$1
JDK=/usr/lib/jvm/java-21-openjdk-amd64; DACAPO=/home/hnpark2/prefetchit/benchmarks/tools/dacapo/dacapo-23.11-MR2-chopin.jar; REN=/home/hnpark2/prefetchit/benchmarks/tools/renaissance/renaissance-gpl.jar
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u'; SCR=/tmp/jvm_scr; mkdir -p $SCR $(dirname $OUT); [[ -f $OUT ]] || echo "suite,bench,cores,heap,l2i,instr,cycles,mpki,ipc,note" > $OUT
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
run_one() { local suite=$1 b=$2; shift 2; [[ -n $ONLY && $b != $ONLY ]] && return; local log=$SCR/$suite.$b.log
  taskset -c $CORES $JDK/bin/java -Xms$HEAP -Xmx$HEAP -XX:ActiveProcessorCount=$NC $JVMFLAGS "$@" > $log 2>&1 & local jp=$!
  sleep $DELAY; if ! kill -0 $jp 2>/dev/null; then echo "$suite,$b,$CORES,$HEAP,0,0,0,0,0,finished_before_window" >> $OUT; echo "$suite/$b: finished before the window (short or failed)"; tail -2 $log | cut -c1-120; return; fi
  perf stat -x, -o $SCR/perf.csv -e $EV -p $jp -- sleep $WIN > /dev/null 2>&1
  kill $jp 2>/dev/null; sleep 1; kill -9 $jp 2>/dev/null; wait $jp 2>/dev/null
  python3 - $suite $b $CORES $HEAP $SCR/perf.csv $OUT <<'PY'
import csv,sys
suite,b,cores,heap,f,out=sys.argv[1:7]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',v.get('instructions',0)); c=v.get('cycles:u',v.get('cycles',0)); m=v.get('L2I',0)
open(out,'a').write(f"{suite},{b},{cores},{heap},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},ok\n")
print(f"{suite}/{b}: MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
  rm -rf $SCR/scratch_$b; }
if [[ $WHICH == both || $WHICH == dacapo ]]; then
  for b in avrora batik biojava cassandra eclipse fop graphchi h2 h2o jme jython kafka luindex lusearch pmd spring sunflow tomcat tradebeans tradesoap xalan zxing; do
    run_one dacapo $b -jar $DACAPO $b -n 30 --scratch-directory $SCR/scratch_$b
  done
fi
if [[ $WHICH == both || $WHICH == renaissance ]]; then
  for b in $($JDK/bin/java -jar $REN --raw-list 2>/dev/null | tr -d '\r'); do
    run_one renaissance $b -jar $REN $b -r 60 --scratch-base $SCR/scratch_$b
  done
fi
echo JVM_SCREEN_DONE
