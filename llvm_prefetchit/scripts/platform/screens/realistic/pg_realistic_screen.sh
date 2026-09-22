#!/usr/bin/env bash
# PostgreSQL 16 realistic screen: server pinned to CORES (4), pgbench (prepared) clients on 60-67, client-count sweep to saturation,
# per step: tps, backend user-mode L2I MPKI / IPC, utilization of the pinned cores. Modes: tpcb (read-write) and select (read-only).
CORES=${CORES:-4-7}; NC=4; OUT=$1; PG=/home/hnpark2/prefetchit/benchmarks/pg; BIN=$PG/install_base/bin; DATA=$PG/data_scale100
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'; mkdir -p $(dirname $OUT); [[ -f $OUT ]] || echo "workload,config,cores,clients,tps,util_pct,l2i,instr,cycles,mpki,ipc,lat_ms" > $OUT
$BIN/pg_ctl -D $DATA -m fast stop > /dev/null 2>&1; sleep 2
taskset -c $CORES $BIN/postgres -D $DATA -p 5440 -k /tmp > /tmp/pg_real.log 2>&1 & PM=$!; sleep 4
for mode in tpcb select; do for c in 4 8 16 32 64; do
  extra=""; [[ $mode == select ]] && extra="-S"
  taskset -c 60-67 $BIN/pgbench -h /tmp -p 5440 -c $c -j 8 -M prepared $extra -T 10 bench > /dev/null 2>&1
  taskset -c 60-67 $BIN/pgbench -h /tmp -p 5440 -c $c -j 8 -M prepared $extra -T 45 bench > /tmp/pgb_${mode}_$c.log 2>&1 & BP=$!; sleep 8
  PIDS=$(pgrep -P $PM | tr '\n' ',' | sed 's/,$//')
  perf stat -x, -o /tmp/pg_perf.csv -e $EV -p $PIDS -- sleep 30 > /dev/null 2>&1; wait $BP
  python3 - $mode $c $CORES $NC $OUT <<'PY'
import csv,re,sys
mode,c,cores,nc,out=sys.argv[1:6]; v={}
for r in csv.reader(open('/tmp/pg_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
w=open(f'/tmp/pgb_{mode}_{c}.log').read(); tps=re.search(r'tps = ([0-9.]+)',w); tps=float(tps.group(1)) if tps else 0; lat=re.search(r'latency average = ([0-9.]+) ms',w); lat=float(lat.group(1)) if lat else 0
i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(30000*int(nc))
open(out,'a').write(f"postgresql,{mode},{cores},{c},{tps:.0f},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{lat:.2f}\n")
print(f"pg {mode} c={c}: tps={tps:.0f} util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} lat={lat:.2f}ms")
PY
done; done
$BIN/pg_ctl -D $DATA -m fast stop > /dev/null 2>&1; echo PG_SCREEN_DONE
