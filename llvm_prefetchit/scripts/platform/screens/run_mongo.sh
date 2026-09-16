#!/usr/bin/env bash
set -u
until grep -q "MONGO PULL DONE" /tmp/mongo_pull.log; do sleep 20; done; sleep 30
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/mongo; mkdir -p $OUT
docker rm -f mongo > /dev/null 2>&1
docker run -d --name mongo --cpuset-cpus 54-57 -p 127.0.0.1:27017:27017 mongo:7 --wiredTigerCacheSizeGB 4 > $OUT/run.log 2>&1; sleep 8
cd /tmp/screen_inputs/mongo && taskset -c 60-63 python3 load.py 15 > $OUT/warm.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 54-57 -- taskset -c 60-63 python3 load.py 60 > $OUT/load.log 2>&1
python3 - $OUT/perf.csv $OUT/load.log <<'PY'
import csv,sys; ev={}
perf,log=sys.argv[1:]
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
print(f"mongodb mixed: {open(log).read().strip()} L2I MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G (cores 54-57)")
PY
docker rm -f mongo > /dev/null 2>&1; echo MONGO_DONE
