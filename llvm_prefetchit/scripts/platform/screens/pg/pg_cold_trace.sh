#!/usr/bin/env bash
# Trace the PostgreSQL backends under pgbench (16 clients, prepared, scale 100) with socialNetwork noise, default scheduling on 0-42.
# MODE=lbr   → OUT/samples_lbr.txt (+ samples.txt), OUT/maps.txt   [L2I-miss samples with branch stacks; for cold_plan.py]
# MODE=rate  → OUT/rates.txt                                          [cycles+LBR: per-function entry counts; ref = exec_execute_message]
# MODE=instr → OUT/site_exec.txt                                      [instruction samples on prefetcht1 per function; for pruning]
# MODE=miss  → OUT/samples.txt + per-function miss shares            [plain L2I-miss profile of BIN]
# Usage: MODE=... pg_cold_trace.sh BIN OUT        (BIN = .../install_<tag>/bin/postgres)
set -u; BIN=$1; OUT=$2; mkdir -p $OUT; OUT=$(readlink -f $OUT); MODE=${MODE:-lbr}
PG=/home/hnpark2/prefetchit/benchmarks/pg; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
PGB="$PG/install_base/bin/pgbench -h /tmp -p 5440 -c 16 -j 4 -M prepared bench"
$PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 2
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
taskset -c 0-42 $BIN -D $PG/data_scale100 -p 5440 -k /tmp > $OUT/server.log 2>&1 & PM=$!; sleep 4
taskset -c 40-42 $PGB -T 15 > /dev/null 2>&1
taskset -c 40-42 $PGB -T 60 > $OUT/pgbench.log 2>&1 & BP=$!; sleep 8
PIDS=$(pgrep -P $PM | tr '\n' ',' | sed 's/,$//'); b=$(pgrep -P $PM | head -1); echo ps101899 | sudo -S -p '' cat /proc/$b/maps > $OUT/maps.txt; echo "backends: $(echo $PIDS | tr ',' '\n' | wc -l)"
case $MODE in
  lbr)   EV="-e cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp -b -c 1000"; FLD="ip,dso,brstack";;
  rate)  EV="-e cycles:u -b -c 400000"; FLD="ip,dso,brstack";;
  instr) EV="-e instructions:u -c 20000"; FLD="ip,dso";;
  miss)  EV="-e cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp -c 1000"; FLD="ip,dso";;
esac
echo ps101899 | sudo -S -p '' perf record $EV -p $PIDS -o $OUT/perf.data -- sleep 25 > $OUT/perf_record.log 2>&1
wait $BP; tps=$(grep -E "^tps = " $OUT/pgbench.log | tail -1 | sed -E 's/tps = ([0-9.]+).*/\1/'); echo "tps=$tps" | tee $OUT/tps.txt
$PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "^$W -D exp"); do kill $p 2>/dev/null; done
echo ps101899 | sudo -S -p '' chmod a+r $OUT/perf.data; echo ps101899 | sudo -S -p '' perf script -i $OUT/perf.data -F $FLD 2>/dev/null > $OUT/samples_raw.txt; rm -f $OUT/perf.data
python3 - $OUT $BIN $MODE <<'PY'
import sys,re,bisect,collections,subprocess
out,exe,mode=sys.argv[1:4]
segs=[]
for l in open(f"{out}/maps.txt"):
    p=l.split(None,5)
    if len(p)>=6 and 'x' in p[1] and p[5].strip().endswith('/bin/postgres'):
        lo,hi=(int(x,16) for x in p[0].split('-')); segs.append((lo,hi,int(p[2],16)))
base=min(lo-off for lo,hi,off in segs)
syms=[]
for l in subprocess.run(['nm','--defined-only',exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw': syms.append((int(f[0],16),f[2]))
syms.sort(); addrs=[a for a,_ in syms]; starts={a:n for a,n in syms}
def fn_of(va):
    i=bisect.bisect_right(addrs,va)-1
    return syms[i][1] if i>=0 else None
if mode in ('lbr','miss'):
    import shutil
    if mode=='lbr': shutil.copy(f"{out}/samples_raw.txt", f"{out}/samples_lbr.txt")
    tot=0; exe_n=0; per=collections.Counter(); dso=collections.Counter()
    for l in open(f"{out}/samples_raw.txt"):
        f=l.split()
        if len(f)<2 or not re.match(r'[0-9a-f]+$',f[0]): continue
        tot+=1; d=f[1].strip('()'); dso[d.rsplit('/',1)[-1]]+=1
        if d.endswith('/bin/postgres'):
            exe_n+=1; n=fn_of(int(f[0],16)-base)
            if n: per[n]+=1
    with open(f"{out}/samples.txt","w") as o:
        for l in open(f"{out}/samples_raw.txt"):
            f=l.split()
            if len(f)>=2 and re.match(r'[0-9a-f]+$',f[0]): o.write(f"{f[0]} {f[1]}\n")
    open(f"{out}/func_shares.txt","w").write('\n'.join(f"{c} {100*c/max(1,exe_n):.2f}% {n}" for n,c in per.most_common(300))+'\n')
    print(f"{mode}: samples={tot} exe={exe_n} ({100*exe_n/max(1,tot):.1f}%) distinct_funcs={len(per)}; dso: "+', '.join(f"{k} {100*v/tot:.1f}%" for k,v in dso.most_common(5)))
elif mode=='rate':
    DSO=r'\((?:[^()]|\([^()]*\))*\)'
    ENT=re.compile(r'0x([0-9a-f]+) '+DSO+r'/0x([0-9a-f]+) '+DSO+r'/[MPX-]/[^/]*/[^/]*/([0-9-]+)/(\w+)/')
    N=0; cnt=collections.Counter()
    for ln in open(f"{out}/samples_raw.txt"):
        if not re.match(r'\s*[0-9a-f]+\s+\(',ln): continue
        N+=1
        for fr,to,cyc,ty in ENT.findall(ln):
            n=starts.get(int(to,16)-base)
            if n: cnt[n]+=1
    with open(f"{out}/rates.txt","w") as f:
        f.write(f"#windows {N}\n")
        for n,c in cnt.most_common(): f.write(f"{c} {n}\n")
    print(f"rate: windows={N} functions={len(cnt)} exec_execute_message={cnt.get('exec_execute_message',0)} exec_bind_message={cnt.get('exec_bind_message',0)} top: "+', '.join(f"{n}={c}" for n,c in cnt.most_common(4)))
elif mode=='instr':
    pf=set()
    for l in subprocess.run(['objdump','-d','--no-show-raw-insn',exe],capture_output=True,text=True).stdout.splitlines():
        m=re.match(r'^\s*([0-9a-f]+):\s+prefetcht1',l)
        if m: pf.add(int(m.group(1),16))
    tot=0; onpf=collections.Counter()
    for l in open(f"{out}/samples_raw.txt"):
        f=l.split()
        if len(f)<2 or not re.match(r'[0-9a-f]+$',f[0]): continue
        tot+=1
        if f[1].strip('()').endswith('/bin/postgres'):
            va=int(f[0],16)-base
            if va in pf:
                n=fn_of(va)
                if n: onpf[n]+=1
    with open(f"{out}/site_exec.txt","w") as f:
        f.write(f"#samples {tot} on_prefetch {sum(onpf.values())}\n")
        for n,c in onpf.most_common(): f.write(f"{c} {n}\n")
    print(f"instr: samples={tot} on_prefetch={sum(onpf.values())} ({100*sum(onpf.values())/max(1,tot):.2f}%) top: "+', '.join(f"{n}={c}" for n,c in onpf.most_common(4)))
PY
rm -f $OUT/samples_raw.txt; echo TRACE_DONE
