#!/usr/bin/env bash
# after the MariaDB chain: round 15 = post-link timeline arms on the rebuilt base (exact call-site placement, ~1.3k prefetches)
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q MARIADB_CHAIN_DONE coldscreen/chain_mariadb.log 2>/dev/null; do sleep 15; done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; T=$DB/out_utl_tlpl:$DB/libs_utl_tlpl:dsb-deps-g; TN=$DB/out_utl_tlplnop:$DB/libs_utl_tlplnop:dsb-deps-g; L=/dsb/postlink/warmup
echo "[$(date +%T)] round15 start"
./dsb_warm_ab2.sh results/round15 3 g=$B:-:-:64:0:20000:0 tlpl=$T:-:-:64:0:20000:0 tlpl_nop=$TN:-:-:64:0:20000:0 tlplw64=$T:$L/libwarmup.so:$L/list_top256.txt:64:0:20000:0 tlplw64_nop=$TN:$L/libwarmup_nop.so:$L/list_top256.txt:64:0:20000:0 > logs/round15.log 2>&1
echo "[$(date +%T)] CHAIN_TLPL_DONE"
