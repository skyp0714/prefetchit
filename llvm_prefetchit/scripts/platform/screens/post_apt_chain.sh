#!/usr/bin/env bash
set -u
until grep -q APT_DC_DONE /tmp/apt_dc.log; do sleep 15; done
echo "[$(date '+%T')] apt batch done"
pip3 install --user --break-system-packages pandas > /tmp/pip_pandas.log 2>&1
./benchpress_cli.py install tao_bench_autoscale > /tmp/tao_install.log 2>&1; echo "[$(date '+%T')] TAO INSTALL rc=$?"
echo ps101899 | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-v2 > /tmp/apt_compose.log 2>&1; echo "[$(date '+%T')] compose install rc=$? $(docker compose version 2>&1 | head -1)"
cd /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork && docker compose pull > /tmp/dsb_pull.log 2>&1; echo "[$(date '+%T')] DSB PULL rc=$?"
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
which qemu-x86_64 && CORE=45 bash $S qemu_user_tcg_matmul /tmp/gem5run "qemu-x86_64 /tmp/gem5run/work 200 60" 150
until grep -q HHVM_DL_DONE /tmp/hhvm_dl.log; do sleep 15; done
cd /home/hnpark2/prefetchit/benchmarks/tools/hhvm && tar -Jxf hhvm-3.30-ubuntu.tar.xz > /dev/null 2>&1 && ls
[[ -d hhvm ]] && (cd hhvm && echo ps101899 | sudo -S timeout 900 ./pour-hhvm.sh > /tmp/hhvm_pour.log 2>&1; echo "[$(date '+%T')] pour-hhvm rc=$?"; /usr/local/bin/hhvm --version 2>&1 | head -1)
echo POST_APT_CHAIN_DONE
