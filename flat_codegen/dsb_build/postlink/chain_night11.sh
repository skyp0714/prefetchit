#!/usr/bin/env bash
# Chain v11: finish the deps image (deps2 layer running -> deps5 layer), then rebuild g/b3/seq + round4 via chain_night10.sh
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $DB
until grep -q "^EXIT" $PL/logs/deps2_build.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] deps2 layer: $(tail -1 $PL/logs/deps2_build.log)"
docker build -f Dockerfile.deps5 -t dsb-deps-jammy . > $PL/logs/deps5_build.log 2>&1; echo "[$(date +%T)] deps5 layer exit $?"
rm -rf $PL/results/round4 out_utl_g libs_utl_g out_utl_b3 libs_utl_b3 out_utl_seq libs_utl_seq
bash $PL/chain_night10.sh
echo "[$(date +%T)] CHAIN11_DONE"
