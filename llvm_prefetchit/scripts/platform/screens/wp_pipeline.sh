#!/usr/bin/env bash
# WordPress on a self-built php-fpm: STEP=trace|plan|build|measure  (variants: base, pgo_cov90, static_retcond)
#   php-fpm runs as this user (pool user = hnpark2, listen /tmp/php-fpm-<v>.sock 0666), workers pinned to PHP_CORES; nginx site :8082 → that socket.
set -u
STEP="${1:?step}"; ROOT=/home/hnpark2/prefetchit; P=$ROOT/benchmarks/php; LLVM=$ROOT/llvm_prefetchit; OUT=$LLVM/results/pgo_static_20260916/wordpress; mkdir -p $OUT/plans $OUT/measure $OUT/traces
PHP_CORES="${PHP_CORES:-72-79}"; WRK_CORES="${WRK_CORES:-80-83}"; URL=http://localhost:8082/; S=ps101899
log(){ echo "[$(date '+%T')] [wordpress] $*" | tee -a $OUT/run.log; }
wait_quiet(){ while pgrep -x clang++-19 >/dev/null || pgrep -x clang-19 >/dev/null || pgrep -f "runcpu.*action=build" >/dev/null; do sleep 30; done; }
fpm_conf(){ local v=$1; cat > $OUT/fpm_$v.conf <<C
[global]
pid = /tmp/php-fpm-$v.pid
error_log = $OUT/fpm_$v.log
[www]
user = hnpark2
listen = /tmp/php-fpm-$v.sock
listen.mode = 0666
pm = static
pm.max_children = 16
C
}
start_fpm(){ local v=$1; stop_fpm; fpm_conf $v; taskset -c $PHP_CORES $P/install_$v/sbin/php-fpm -y $OUT/fpm_$v.conf -c /etc/php/8.3/fpm/php.ini 2>>$OUT/fpm_$v.log; sleep 1
  echo $S | sudo -S sed -i "s|fastcgi_pass unix:[^;]*;|fastcgi_pass unix:/tmp/php-fpm-$v.sock;|" /etc/nginx/sites-available/wordpress; echo $S | sudo -S ln -sf /etc/nginx/sites-available/wordpress /etc/nginx/sites-enabled/wordpress; echo $S | sudo -S nginx -s reload 2>/dev/null || echo $S | sudo -S systemctl start nginx; sleep 1
  curl -s -o /dev/null -w "$v front %{http_code}\n" $URL; }
stop_fpm(){ for f in /tmp/php-fpm-*.pid; do [[ -f $f ]] && kill $(cat $f) 2>/dev/null; done; sleep 1; pkill -f "php-fpm: master" 2>/dev/null; sleep 1; }
setup_db(){ systemctl is-active mariadb >/dev/null || echo $S | sudo -S systemctl start mariadb; sleep 2; for pid in $(pgrep -x mariadbd); do echo $S | sudo -S taskset -a -cp $PHP_CORES $pid >/dev/null; done; }
load(){ local dur=$1 out=$2; taskset -c $WRK_CORES wrk -t4 -c32 -d${dur}s $URL > $out 2>&1; }
case $STEP in
trace)
  setup_db; start_fpm base; load 10 $OUT/warm.log
  for i in 1 2 3; do TD=$OUT/traces/trace0$i/l2_miss; mkdir -p $TD; [[ -s $TD/lbr_symbolic_dump.txt ]] && continue
    load 50 $OUT/traces/load$i.log & LP=$!; sleep 3; perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 5000 -o $TD/l2miss_profile.data -a -C $PHP_CORES -- sleep 40 > $TD/record.log 2>&1 || true; wait $LP
    bash $ROOT/profiling/analyze_pebs_trace.sh --data $TD/l2miss_profile.data --out-dir $TD --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary $P/install_base/sbin/php-fpm > $TD/analyze.log 2>&1
    log "trace $i samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' $TD/trace_summary.md)"; done
  stop_fpm; python3 $ROOT/static_prefetch/tools/ret/miss_stream_characterization.py --binary $P/install_base/sbin/php-fpm --trace-dir $OUT/traces/trace01/l2_miss --out-dir $OUT/diag 2>&1 | grep -E "^\{'type'" | cut -c1-150 | tee -a $OUT/run.log ;;
plan)
  TA=(); for i in 1 2 3; do TA+=(--trace-dir $OUT/traces/trace0$i/l2_miss); done
  python3 $LLVM/tools/prefetchit_trace_to_plan.py "${TA[@]}" --binary $P/install_base/sbin/php-fpm --top-k 999999 --target-coverage-pct 90 --depth 24 --depth-min 4 --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 --allow-unresolved-targets --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0,64 --target-ip-source sample-ip --summary-dir $OUT/plans/pgo_cov90 --output $OUT/plans/pgo_cov90.plan.json > $OUT/plans/pgo.log 2>&1
  log "PGO plan: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']))" $OUT/plans/pgo_cov90.plan.json) injections"
  ;;
build)
  V="${VARIANT:?}"; PLAN="${PLAN:?}"; $P/build_php.sh $V $PLAN 2>&1 | tail -2 | tee -a $OUT/run.log
  B=$P/install_$V/sbin/php-fpm; python3 $LLVM/tools/resolve_plan_layout_shift.py --plan $PLAN --shifts $PLAN.shifts.json --output ${PLAN%.json}.resolved.json > /dev/null 2>&1 || true
  cp -f $B $B.unanchored; python3 $LLVM/tools/reanchor_prefetch_targets.py --baseline $P/install_base/sbin/php-fpm --binary $B.unanchored --plan ${PLAN%.json}.resolved.json --output $B 2>&1 | tail -1 | tee -a $OUT/run.log
  log "$V: $(llvm-objdump-19 -d $B | grep -cE 'prefetcht[012]') prefetches"; mkdir -p $P/install_${V}_nop/sbin; python3 $LLVM/tools/make_nop_control_binary.py --input $B --output $P/install_${V}_nop/sbin/php-fpm > /dev/null 2>&1; ln -sfn $P/install_$V/lib $P/install_${V}_nop/lib 2>/dev/null; ln -sfn $P/install_$V/etc $P/install_${V}_nop/etc 2>/dev/null ;;
measure)
  wait_quiet; exec 9>/tmp/measure.lock; flock 9; setup_db
  CSV=$OUT/measure/runs.csv; [[ -s $CSV ]] || echo "variant,rep,rps,l2i_mpki,ipc,instructions" > $CSV
  for rep in 1 2 3; do for v in base ${VARIANTS:?}; do for arm in $v ${v}_nop; do [[ $arm == base_nop ]] && continue; [[ -x $P/install_$arm/sbin/php-fpm ]] || continue
    start_fpm $arm > /dev/null; load 10 $OUT/measure/warm.log
    perf stat -x, -o $OUT/measure/${arm}_r$rep.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -a -C $PHP_CORES -- taskset -c $WRK_CORES wrk -t4 -c32 -d45s $URL > $OUT/measure/${arm}_r$rep.log 2>&1
    python3 - $CSV $arm $rep $OUT/measure/${arm}_r$rep.csv $OUT/measure/${arm}_r$rep.log <<'PY' | tee -a $OUT/run.log
import csv,re,sys
out,arm,rep,perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0); w=open(log).read(); rps=re.search(r"Requests/sec:\s+([0-9.]+)",w)
csv.writer(open(out,"a",newline="")).writerow([arm,rep,rps.group(1) if rps else "",f"{1000*m/i if i else 0:.3f}",f"{i/c if c else 0:.3f}",int(i)])
print(f"{arm} rep{rep}: rps={rps.group(1) if rps else 'n/a'} MPKI={1000*m/i if i else 0:.2f}")
PY
  done; done; done; stop_fpm
  python3 - $CSV <<'PY'
import csv,statistics as st,sys
from collections import defaultdict
g=defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    if r["rps"]: g[r["variant"]].append(r)
rps={v:st.median(float(r["rps"]) for r in rs) for v,rs in g.items()}; mp={v:st.mean(float(r["l2i_mpki"]) for r in rs) for v,rs in g.items()}
print("| variant | n | median rps | speedup vs base | L2I MPKI |\n|---|---:|---:|---:|---:|")
for v in sorted(g,key=lambda x:-rps[x]): print(f"| {v} | {len(g[v])} | {rps[v]:.0f} | {rps[v]/rps['base']:.4f}x | {mp[v]:.2f} |")
PY
  ;;
esac
