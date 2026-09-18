#!/usr/bin/env bash
# After round 18: static-only dependency archives built with the direct list (no GOT form anywhere in the fat-static exe except libc callees),
# service cold3 (own 16 / callee 1) and cold3o8 (own 8); round 19 = g / gs / cold3 / cold3_nop / cold3o8, default scheduling, containers on 0-35.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD2_DONE logs/chain_cold2.log 2>/dev/null; do sleep 15; done
COLD="PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24 PREFETCHIT_COLD_DIRECT_SYMS=/dsb/plans/cold_direct_syms.txt"
echo "[$(date +%T)] static-only deps image"; (cd $DB && EXTRA_PASS_ENV="$COLD PREFETCHIT_COLD_DIRECT_IN_PIC=1" bash rebuild_deps_static.sh dsb-deps-cold3 - > $PL/logs/deps_cold3.log 2>&1); tail -2 $PL/logs/deps_cold3.log | cut -c1-120
docker run --rm --entrypoint bash dsb-deps-cold3 -c 'ls /usr/local/lib/ | grep -E "^lib(thrift|mongoc|bson|jaegertracing|opentracing|yaml)" | tr "\n" " "; echo' 2>&1 | cut -c1-300
echo "[$(date +%T)] service builds"
(cd $DB && rm -rf out_utl_cold3 libs_utl_cold3 libs_utl_cold3nop out_utl_cold3o8 libs_utl_cold3o8 libs_utl_cold3o8nop
 FATSTATIC=1 bash build_utl_variant.sh cold3 dsb-deps-cold3 "$COLD" > $PL/logs/build_utl_cold3.log 2>&1
 FATSTATIC=1 bash build_utl_variant.sh cold3o8 dsb-deps-cold3 "${COLD/OWN_LINES=16/OWN_LINES=8}" > $PL/logs/build_utl_cold3o8.log 2>&1)
for v in cold3 cold3o8; do f=$DB/out_utl_$v/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $v"; grep -m3 -E "error|Error" $PL/logs/build_utl_$v.log | cut -c1-200; continue; }
  echo "$v: size=$(stat -c %s $f) NEEDED=$(readelf -d $f | grep NEEDED | awk '{print $NF}' | tr -d '[]' | tr '\n' ' ')"
  echo "$v: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"; done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; ARMS="g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g:-:-:64:0:20000:0 gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0"
if [[ -f $DB/out_utl_cold3/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_cold3nop; cp $DB/out_utl_cold3/UserTimelineService.nop $DB/out_utl_cold3nop/UserTimelineService
  ARMS="$ARMS cold3=$DB/out_utl_cold3:$DB/libs_utl_g:dsb-deps-g:-:-:64:0:20000:0 cold3_nop=$DB/out_utl_cold3nop:$DB/libs_utl_g:dsb-deps-g:-:-:64:0:20000:0"; fi
[[ -f $DB/out_utl_cold3o8/UserTimelineService ]] && ARMS="$ARMS cold3o8=$DB/out_utl_cold3o8:$DB/libs_utl_g:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round19 arms: $ARMS"; ./dsb_warm_ab2.sh results/round19 3 $ARMS > logs/round19.log 2>&1
echo "[$(date +%T)] CHAIN_COLD3_DONE"
