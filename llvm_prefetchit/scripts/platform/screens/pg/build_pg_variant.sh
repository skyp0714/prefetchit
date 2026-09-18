#!/usr/bin/env bash
# Build PostgreSQL 16 with clang-19 + the PrefetchIT pass plugin into install_<TAG>; ENVS = pass environment (e.g. PREFETCHIT_COLD_PLAN=...).
# Same configure/CFLAGS as build_base.sh so that a plan-free plugin build has the base layout. NOP twin: install_<TAG>/bin/postgres.nop.
set -u; TAG=$1; ENVS=${2:-}
SRC=/home/hnpark2/prefetchit/benchmarks/datacenter_sources/postgres; PG=/home/hnpark2/prefetchit/benchmarks/pg; B=$PG/build_$TAG; I=$PG/install_$TAG
PASS=/home/hnpark2/prefetchit/llvm_prefetchit/build/PrefetchITPass.so; NOPTOOL=/home/hnpark2/prefetchit/llvm_prefetchit/tools/make_nop_control_binary.py
rm -rf "$B" "$I"; mkdir -p "$B"; cd "$B"
env $ENVS CC=clang-19 CFLAGS="-O3 -g -fno-omit-frame-pointer -fpass-plugin=$PASS" "$SRC/configure" --prefix="$I" --without-icu --without-readline --without-zlib > configure.log 2>&1 || { echo "CONFIGURE FAILED"; tail -5 configure.log; exit 1; }
env $ENVS make -j${JOBS:-32} > make.log 2>&1 && make install > install.log 2>&1 || { echo "MAKE FAILED"; grep -m5 -E "error:|Error [0-9]" make.log | cut -c1-200; exit 1; }
grep -h "prefetchit-cold-plan:" make.log | awk '{for(i=1;i<=NF;i++){split($i,a,"="); if(a[1]=="sites")s+=a[2]; if(a[1]=="aliases")al+=a[2]; if(a[1]=="direct")d+=a[2]; if(a[1]=="got")g+=a[2]}} END{print "plan applied: sites="s" aliases="al" direct="d" got="g}'
n=$(objdump -d $I/bin/postgres | grep -c prefetcht1); echo "postgres.$TAG: $n prefetcht1, text=$(size -A $I/bin/postgres | awk '$1==".text"{print $2}')"
if [[ $n -gt 0 ]]; then python3 $NOPTOOL --input $I/bin/postgres --output $I/bin/postgres.nop > /dev/null && chmod 755 $I/bin/postgres.nop && echo "twin ok"; fi
echo "PG_BUILD_DONE $TAG"
