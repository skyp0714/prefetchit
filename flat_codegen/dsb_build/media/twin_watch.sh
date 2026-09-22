#!/usr/bin/env bash
# build_utl_variant.sh writes the NOP twin as out_<pfx>_<v>/<Binary>.nop plus libs_<pfx>_<v>nop, but an A/B arm named "<v>nop" needs
# out_<pfx>_<v>nop/<Binary>. Materialise that directory whenever a new twin appears, so the twins can be measured as ordinary arms.
set -u; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $DB
for i in $(seq 1 ${LOOPS:-720}); do
  for f in out_*/*.nop; do
    [[ -e $f ]] || continue
    d=$(dirname $f); b=$(basename $f .nop); t=${d}nop
    if [[ ! -x $t/$b ]]; then mkdir -p $t && cp -p $f $t/$b && chmod 755 $t/$b && echo "[$(date +%T)] twin arm $t/$b"; fi
  done
  sleep 30
done
