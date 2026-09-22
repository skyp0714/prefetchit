#!/usr/bin/env bash
set -u
CH=/home/hnpark2/prefetchit/benchmarks/tools/clickhouse/clickhouse; cd /tmp/screen_inputs/chsrv; rm -rf data; mkdir -p data
taskset -c 44-47 $CH server -- --path=./data --tcp_port=9123 --http_port=8323 --logger.console=0 --mysql_port=0 --postgresql_port=0 --interserver_http_port=0 > server.log 2>&1 &
SP=$!; sleep 8
$CH client --port 9123 --queries-file setup.sql > setup.log 2>&1; echo "setup rc=$?"
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
# the benchmark client is light; measure the server cores system-wide
perf stat -x, -o $OUT_DIR/clickhouse_server.perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 44-47 -- \
  taskset -c 60 $CH benchmark --port 9123 -c 4 -i 400 --max_threads=4 < /tmp/screen_inputs/chsrv/queries.sql > $OUT_DIR/clickhouse_server.bench.log 2>&1
python3 - $OUT_DIR/clickhouse_server.perf.csv <<'PY'
import csv,sys; ev={}
for row in csv.reader(open(sys.argv[1])):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
print(f"clickhouse server (MergeTree 120M rows, 4 conc): L2I MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G (cores 44-47)")
PY
kill $SP; wait $SP 2>/dev/null
SPIKE=/nonexistent
[[ -x $SPIKE ]] && CORE=47 bash $S spike_riscv_qsort $PWD "$SPIKE $PWD/benchmarks/chipyard/.conda-env/riscv-tools/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv" 60
echo CHSRV_DONE
