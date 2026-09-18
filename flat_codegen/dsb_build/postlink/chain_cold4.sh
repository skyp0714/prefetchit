#!/usr/bin/env bash
# After round 19: trace-guided function selection for the cold-path pass (only functions that miss in the fat-static base, 90% coverage),
# own-lines chosen from round 19 (cold3 vs cold3o8); round 20 = gs / best cold3 / cold4 / cold4_nop.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD3_DONE logs/chain_cold3.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] trace gs"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs 0.9 2>&1 | tail -4
cp results/trace_gs/funcs.txt $DB/plans/cold_funcs_gs.txt; wc -l < $DB/plans/cold_funcs_gs.txt
BEST=$(python3 - <<'PY'
import csv,statistics,collections
d=collections.defaultdict(list)
for r in csv.DictReader(open('results/round19/runs.csv')): d[r['arm']].append(float(r['cycles']))
c3=statistics.median(d.get('cold3',[1e30])); c8=statistics.median(d.get('cold3o8',[1e30]))
print('cold3o8' if c8<c3 else 'cold3')
PY
); OWN=16; [[ $BEST == cold3o8 ]] && OWN=8; echo "best round-19 arm: $BEST (own=$OWN)"
COLD="PREFETCHIT_COLD_OWN_LINES=$OWN PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24 PREFETCHIT_COLD_DIRECT_SYMS=/dsb/plans/cold_direct_syms.txt PREFETCHIT_SEQ_FUNCTIONS_FILE=/dsb/plans/cold_funcs_gs.txt"
echo "[$(date +%T)] cold4 build"; (cd $DB && rm -rf out_utl_cold4 libs_utl_cold4 libs_utl_cold4nop; FATSTATIC=1 bash build_utl_variant.sh cold4 dsb-deps-cold3 "$COLD" > $PL/logs/build_utl_cold4.log 2>&1)
grep -h "prefetchit-cold:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | tail -1 | cut -c1-200
f=$DB/out_utl_cold4/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED cold4"; grep -m3 -E "error|Error" $PL/logs/build_utl_cold4.log | cut -c1-200; }
echo "cold4: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0"
if [[ -f $f.nop ]]; then mkdir -p $DB/out_utl_cold4nop; cp $f.nop $DB/out_utl_cold4nop/UserTimelineService
  ARMS="$ARMS cold4=$DB/out_utl_cold4:$L:dsb-deps-g:-:-:64:0:20000:0 cold4_nop=$DB/out_utl_cold4nop:$L:dsb-deps-g:-:-:64:0:20000:0"; fi
echo "[$(date +%T)] round20 arms: $ARMS"; ./dsb_warm_ab2.sh results/round20 3 $ARMS > logs/round20.log 2>&1
echo "[$(date +%T)] CHAIN_COLD4_DONE"
