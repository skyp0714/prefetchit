#!/usr/bin/env bash
# MariaDB prefetch pipeline on the self-built server (clang-19 -O3 -g):
#   STEP=init     own datadir (port 3400) + sysbench tables
#   STEP=screen   L2I MPKI of oltp_read_write on the self-built server (SERVER_CORES, CLIENT_CORES)
#   STEP=trace    3 x PEBS+LBR traces under load → symbolize → miss-stream diagnosis
#   STEP=plan     trace-guided (PGO) plan, sample-IP targets, cov90
#   STEP=build    VARIANT=name PLAN=... rebuild mariadbd through the pass (+ NOP twin) into install_<VARIANT>
#   STEP=measure  VARIANTS="v1 ..." interleaved base/variant/twin sysbench runs (REPS), tps + MPKI
set -euo pipefail
STEP="${1:?step}"; ROOT=/home/hnpark2/prefetchit; M=$ROOT/benchmarks/mariadb; LLVM=$ROOT/llvm_prefetchit; V=10.11.14
OUT="${OUT:-$LLVM/results/mariadb_20260916}"; mkdir -p $OUT
SERVER_CORES="${SERVER_CORES:-64-67}"; CLIENT_CORES="${CLIENT_CORES:-68-71}"; THREADS="${THREADS:-8}"; DUR="${DUR:-60}"; REPS="${REPS:-3}"
PORT=3400; DATA=$M/data; SOCK=/tmp/mariadb_pipe.sock
SB="--mysql-host=localhost --mysql-socket=$SOCK --mysql-user=root --mysql-db=sbtest --tables=16 --table-size=200000"
log(){ echo "[$(date '+%T')] $*" | tee -a $OUT/run.log; }
start_server(){ # $1 = install dir
  local I=$1; pgrep -f "mariadbd.*--port=$PORT" >/dev/null && stop_server
  taskset -c $SERVER_CORES $I/bin/mariadbd --no-defaults --datadir=$DATA --port=$PORT --socket=$SOCK --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=0 --innodb-flush-method=O_DIRECT --skip-log-bin --max-connections=64 --skip-name-resolve > $OUT/server_$(basename $I).log 2>&1 &
  for i in $(seq 1 60); do $I/bin/mariadb-admin --socket=$SOCK -u root ping >/dev/null 2>&1 && return; sleep 1; done; echo "server failed" >&2; exit 1; }
stop_server(){ $M/install_base/bin/mariadb-admin --socket=$SOCK -u root shutdown >/dev/null 2>&1 || pkill -f "mariadbd.*--port=$PORT" || true; sleep 2; }
perf_run(){ # $1 label $2 csv-out ; runs sysbench DUR with perf stat -a -C on server cores
  taskset -c $CLIENT_CORES sysbench oltp_read_write $SB --threads=$THREADS --time=15 run > /dev/null 2>&1
  perf stat -x, -o $2 -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C $SERVER_CORES -- \
    taskset -c $CLIENT_CORES sysbench oltp_read_write $SB --threads=$THREADS --time=$DUR run > ${2%.csv}.sysbench.log 2>&1
  python3 - $2 ${2%.csv}.sysbench.log $1 <<'PY'
import csv,re,sys
perf,log,label=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
tps=re.search(r"transactions:\s+\d+\s+\(([0-9.]+) per sec",open(log).read())
print(f"{label}: tps={tps.group(1) if tps else 'n/a'} L2I MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
}
case $STEP in
init)
  [[ -d $DATA ]] || { $M/install_base/scripts/mariadb-install-db --no-defaults --datadir=$DATA --auth-root-authentication-method=normal > $OUT/installdb.log 2>&1; }
  start_server $M/install_base
  $M/install_base/bin/mariadb --socket=$SOCK -u root -e "CREATE DATABASE IF NOT EXISTS sbtest"
  taskset -c $CLIENT_CORES sysbench oltp_read_write $SB prepare > $OUT/prepare.log 2>&1 || true
  stop_server; log "init done" ;;
screen)
  start_server $M/install_base; perf_run base_screen $OUT/screen_base.perf.csv | tee -a $OUT/run.log; stop_server ;;
trace)
  start_server $M/install_base
  for i in 1 2 3; do TD=$OUT/traces/trace0$i/l2_miss; mkdir -p $TD; [[ -s $TD/lbr_symbolic_dump.txt ]] && continue
    taskset -c $CLIENT_CORES sysbench oltp_read_write $SB --threads=$THREADS --time=70 run > $TD/sysbench.log 2>&1 &
    SBPID=$!; sleep 8; perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 5000 -o $TD/l2miss_profile.data -a -C $SERVER_CORES -- sleep 55 > $TD/record.log 2>&1 || true; wait $SBPID
    bash $ROOT/profiling/analyze_pebs_trace.sh --data $TD/l2miss_profile.data --out-dir $TD --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary $M/install_base/bin/mariadbd > $TD/analyze.log 2>&1 || true
    log "trace $i samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' $TD/trace_summary.md)"
  done; stop_server
  python3 $ROOT/static_prefetch/tools/ret/miss_stream_characterization.py --binary $M/install_base/bin/mariadbd --trace-dir $OUT/traces/trace01/l2_miss --out-dir $OUT/diag 2>&1 | grep -E "^\{'type'|cumulative" | cut -c1-200 | tee -a $OUT/run.log ;;
plan)
  mkdir -p $OUT/plans; TA=(); for i in 1 2 3; do [[ -s $OUT/traces/trace0$i/l2_miss/lbr_symbolic_dump.txt ]] && TA+=(--trace-dir $OUT/traces/trace0$i/l2_miss); done
  python3 $LLVM/tools/prefetchit_trace_to_plan.py "${TA[@]}" --binary $M/install_base/bin/mariadbd --top-k 999999 --target-coverage-pct ${COV:-90} --depth 24 --depth-min 4 \
    --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 --allow-unresolved-targets \
    --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0,64 --target-ip-source sample-ip --summary-dir $OUT/plans/pgo_cov${COV:-90} --output $OUT/plans/pgo_cov${COV:-90}.plan.json > $OUT/plans/pgo_cov${COV:-90}.log 2>&1 || tail -3 $OUT/plans/pgo_cov${COV:-90}.log
  log "plan pgo_cov${COV:-90}: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']),'injections')" $OUT/plans/pgo_cov${COV:-90}.plan.json)" ;;
build)
  VAR="${VARIANT:?}"; export PREFETCHIT_PLAN="${PLAN:-}"
  [[ -n "${SEQ_DISTANCE:-}" ]] && export PREFETCHIT_SEQ_DISTANCE=$SEQ_DISTANCE PREFETCHIT_SEQ_STRIDE_INSNS=${SEQ_STRIDE:-20}
  B=$M/build_$VAR; I=$M/install_$VAR; rm -rf $B; mkdir -p $B; cd $B
  F="-O3 -g -DNDEBUG -fno-omit-frame-pointer -fpass-plugin=$LLVM/build/PrefetchITPass.so"
  cmake ../mariadb-$V -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 -DCMAKE_C_FLAGS_RELWITHDEBINFO="$F" -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="$F" \
    -DCMAKE_INSTALL_PREFIX=$I -DWITH_SSL=system -DWITH_ZLIB=system -DPLUGIN_ROCKSDB=NO -DPLUGIN_MROONGA=NO -DPLUGIN_SPIDER=NO -DPLUGIN_CONNECT=NO -DPLUGIN_TOKUDB=NO -DPLUGIN_OQGRAPH=NO -DPLUGIN_SPHINX=NO -DWITH_WSREP=OFF -DWITH_UNIT_TESTS=OFF -DWITH_EMBEDDED_SERVER=OFF > cmake.log 2>&1
  make -j32 > make.log 2>&1; make install > install.log 2>&1
  grep -h "prefetchit-inject: injected=[1-9]" make.log | wc -l | xargs -I{} log "$VAR: {} TUs with injections; $(llvm-objdump-19 -d $I/bin/mariadbd | grep -cE 'prefetcht[012]') prefetches in mariadbd"
  python3 $LLVM/tools/make_nop_control_binary.py --input $I/bin/mariadbd --output $I/bin/mariadbd_nop > /dev/null 2>&1; log "$VAR twin: $(llvm-objdump-19 -d $I/bin/mariadbd_nop | grep -cE 'prefetcht[012]') left"
  mkdir -p $M/install_${VAR}_nop/bin && cp -a $I/bin/mariadbd_nop $M/install_${VAR}_nop/bin/mariadbd && ln -sfn $M/install_base/bin/mariadb-admin $M/install_${VAR}_nop/bin/ 2>/dev/null; cp -rn $I/share $M/install_${VAR}_nop/ 2>/dev/null || true; cp -rn $I/lib $M/install_${VAR}_nop/ 2>/dev/null || true ;;
measure)
  CSV=$OUT/measure/runs.csv; mkdir -p $OUT/measure; [[ -s $CSV ]] || echo "variant,rep,tps,l2i_mpki,ipc,instructions" > $CSV
  for rep in $(seq 1 $REPS); do for v in base ${VARIANTS:?}; do for arm in $v ${v}_nop; do
    [[ $arm == base_nop ]] && continue; grep -q "^$arm,$rep," $CSV && continue
    I=$M/install_$arm; [[ -x $I/bin/mariadbd ]] || { log "missing $I"; continue; }
    start_server $I; line=$(perf_run "$arm rep$rep" $OUT/measure/${arm}_rep$rep.perf.csv); stop_server; log "$line"
    python3 - $CSV "$arm" $rep "$line" <<'PY'
import csv,re,sys
out,arm,rep,line=sys.argv[1:]; g=lambda k: re.search(k+r"=([0-9.]+)",line)
csv.writer(open(out,"a",newline="")).writerow([arm,rep,g("tps").group(1) if g("tps") else "", g("MPKI").group(1), g("IPC").group(1), g("instr").group(1)])
PY
  done; done; done
  python3 - $CSV <<'PY'
import csv,statistics as st,sys
from collections import defaultdict
g=defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    if r["tps"]: g[r["variant"]].append(r)
tps={v:st.median(float(r["tps"]) for r in rs) for v,rs in g.items()}; mp={v:st.mean(float(r["l2i_mpki"]) for r in rs) for v,rs in g.items()}
print("| variant | n | median tps | speedup vs base | L2I MPKI |\n|---|---:|---:|---:|---:|")
for v in sorted(g,key=lambda x:-tps[x]): print(f"| {v} | {len(g[v])} | {tps[v]:.0f} | {tps[v]/tps['base']:.4f}x | {mp[v]:.2f} |")
PY
  ;;
*) echo "unknown step" >&2; exit 2 ;;
esac
