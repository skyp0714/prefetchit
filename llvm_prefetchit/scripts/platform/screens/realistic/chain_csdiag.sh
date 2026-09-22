#!/usr/bin/env bash
# C6-off diagnostic points for the CloudSuite candidates (web-serving scale 50; web-search / data-caching if they qualified), cores 4-7.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q STACKDIAG_DONE $R/logs/chain_stackdiag.log 2>/dev/null; do sleep 60; done
cstate() { local mode=$1 cc; for cc in 4 5 6 7; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cstate 0' EXIT; cstate 1
echo "[$(date +%T)] web-serving C6 off"; sed 's/for scale in 25 50 100 200 400; do/for scale in 50; do/; s/web-serving,cs-ws-web/web-serving-noC6,cs-ws-web/' $R/cloudsuite_ws2.sh > /tmp/ws2_noc6.sh; CORES=4-7 bash /tmp/ws2_noc6.sh $R/cloudsuite_4core.csv 2>&1 | grep -E "^web-serving" | cut -c1-200
if grep -qE "^web-search,.*,[1-9][0-9]*\.[0-9]+,[0-9.]+,workers" $R/cloudsuite_4core.csv; then echo "[$(date +%T)] web-search C6 off"; sed 's/for w in 25 50 100 200 400; do/for w in 50; do/; s/open(out,.a.).write(f"{b},/open(out,"a").write(f"{b}-noC6,/' $R/cloudsuite_fix2.sh > /tmp/wsrch_noc6.sh; CORES=4-7 bash /tmp/wsrch_noc6.sh $R/cloudsuite_4core.csv web-search 2>&1 | grep -E "^web-search" | cut -c1-200; fi
echo "[$(date +%T)] data-caching C6 off"; sed 's/for rps in 100000 200000 400000 700000 1000000; do/for rps in 200000; do/; s/data-caching,cs-dc-server/data-caching-noC6,cs-dc-server/' $R/cloudsuite_dc2.sh > /tmp/dc2_noc6.sh; CORES=4-7 bash /tmp/dc2_noc6.sh $R/cloudsuite_4core.csv 2>&1 | grep -E "^data-caching" | cut -c1-200
cstate 0; echo "[$(date +%T)] CSDIAG_DONE"
