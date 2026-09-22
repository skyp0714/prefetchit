#!/usr/bin/env bash
# Round 7b: prefetchit1 vs prefetcht1 with the pass applied to the SERVICE modules only (archives from the stock dsb-deps-jammy image):
# prefetchit needs RIP-relative operands, which the pass can only emit in the exe (PIE) modules. Same direct-only plan for both.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q "WS_CHAIN7_DONE" $WS/logs/chain7.log 2>/dev/null; do sleep 15; done
for arm in p7t2 p7i2; do
  MN=prefetcht1; [[ $arm == p7i2 ]] && MN=prefetchit1
  echo "[$(date +%T)] service build $arm ($MN, exe modules only)"
  cd $DB && STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-jammy "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_p7d.json PREFETCHIT_SEQ_MNEMONIC=$MN" 2>&1 | tail -1
  echo "$arm: prefetcht1 $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1) prefetchit1 $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetchit1)"
done
ARMS="base=wsm"; for a in p7t2 p7i2; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 7b: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab7b $REPS $ARMS 2>&1 | tail -10
echo "[$(date +%T)] WS_CHAIN7B_DONE"
