#!/usr/bin/env bash
# Two missing C6-off points on cores 4-7: web-serving (scale 50; the previous attempt measured an empty cgroup) and data-serving (10k ops/s).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
cs47() { local mode=$1 cc; for cc in 4 5 6 7; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cs47 0' EXIT; grep -v "^web-serving-noC6," $R/cloudsuite_4core.csv > $R/cloudsuite_4core.tmp && mv $R/cloudsuite_4core.tmp $R/cloudsuite_4core.csv
cs47 1
echo "[$(date +%T)] web-serving C6 off (scale 50)"; sed 's/for scale in 25 50 100 200 400; do/for scale in 50; do/; s/web-serving,cs-ws-web/web-serving-noC6,cs-ws-web/' $R/cloudsuite_ws2.sh > /tmp/ws2_noc6.sh; CORES=4-7 timeout 900 bash /tmp/ws2_noc6.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-200
echo "[$(date +%T)] data-serving C6 off (10k ops/s)"; sed 's/for rate in 5000 10000 20000 40000 80000; do/for rate in 10000; do/; s/open(out,.a.).write(f"{b},/open(out,"a").write(f"{b}-noC6,/' $R/cloudsuite_fix2.sh > /tmp/ds_noc6.sh; CORES=4-7 timeout 1500 bash /tmp/ds_noc6.sh $R/cloudsuite_4core.csv data-serving 2>&1 | grep -E "^data-serving|warm" | cut -c1-200
cs47 0; docker rm -f $(docker ps -aq --filter name=cs-) > /dev/null 2>&1; echo "[$(date +%T)] CSDIAG2_DONE"
