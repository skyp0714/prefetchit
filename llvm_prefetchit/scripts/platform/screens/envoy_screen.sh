#!/usr/bin/env bash
# Envoy reverse proxy in front of the local nginx, wrk load; perf stat on the envoy process
set -u
E=/home/hnpark2/prefetchit/benchmarks/tools/envoy/envoy; OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/envoy_proxy; mkdir -p $OUT
curl -s -o /dev/null -w "nginx %{http_code}\n" http://127.0.0.1:80/ || { echo ps101899 | sudo -S systemctl start nginx; sleep 1; }
taskset -c 54,55 $E -c /tmp/screen_inputs/envoy/envoy.yaml --concurrency 2 > $OUT/envoy.log 2>&1 &
EP=$!; sleep 3; curl -s -o /dev/null -w "envoy %{http_code}\n" http://127.0.0.1:10000/
taskset -c 60-63 wrk -t4 -c64 -d15s http://127.0.0.1:10000/ > $OUT/warmup.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -p $EP -- taskset -c 60-63 wrk -t4 -c64 -d60s http://127.0.0.1:10000/ > $OUT/wrk.log 2>&1
kill $EP; wait $EP 2>/dev/null
python3 - $OUT/perf.csv $OUT/wrk.log <<'PY'
import csv,re,sys
perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
rps=re.search(r"Requests/sec:\s+([0-9.]+)",open(log).read())
print(f"envoy proxy: rps={rps.group(1) if rps else 'n/a'} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G")
PY
echo ENVOY_DONE
