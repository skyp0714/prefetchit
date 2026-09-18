#!/usr/bin/env bash
# After the main JVM screen: rerun the DaCapo benchmarks that exited before the window with the JDK-21 compatibility flags
# (cassandra needs -Djava.security.manager=allow; others may need --add-opens), then an 8-core pass for every benchmark with MPKI >= 1.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q JVM_SCREEN_DONE $R/logs/jvm_4core.log 2>/dev/null; do sleep 30; done
FAILED=$(awk -F, '$1=="dacapo" && $10!="ok"{print $2}' $R/jvm_4core.csv | tr '\n' ' '); echo "[$(date +%T)] rerun failed dacapo: $FAILED"
for b in $FAILED; do CORES=8-11 HEAP=8g JVMFLAGS="-Djava.security.manager=allow --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED" ONLY=$b $R/jvm_realistic_screen.sh $R/jvm_4core_rerun.csv dacapo 2>&1 | grep -E "MPKI=|finished"; done
HOT=$(awk -F, 'NR>1 && $8>=1.0 && $10=="ok"{print $1":"$2}' $R/jvm_4core.csv $R/jvm_4core_rerun.csv 2>/dev/null | sort -u | tr '\n' ' '); echo "[$(date +%T)] 8-core pass for MPKI>=1: $HOT"
for sb in $HOT; do s=${sb%%:*}; b=${sb#*:}; fl=""; [[ $b == cassandra ]] && fl="-Djava.security.manager=allow"; CORES=8-15 HEAP=8g JVMFLAGS="$fl" ONLY=$b $R/jvm_realistic_screen.sh $R/jvm_8core.csv $s 2>&1 | grep -E "MPKI=|finished"; done
echo "[$(date +%T)] JVM2_DONE"
