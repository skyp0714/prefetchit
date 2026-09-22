#!/usr/bin/env bash
set -u
until grep -q APT_DC_DONE /tmp/apt_dc.log; do sleep 15; done
until ! pgrep -x apt-get >/dev/null; do sleep 10; done
echo ps101899 | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y ghdl > /tmp/apt_ghdl.log 2>&1; echo "ghdl install rc=$? $(which ghdl)"
cd /home/hnpark2/prefetchit; export OUT_DIR=$PWD/llvm_prefetchit/results/broad_screen_20260916; S=$PWD/llvm_prefetchit/scripts/platform/screen_one.sh
ghdl --version 2>&1 | head -1
CORE=45 bash $S ghdl_neorv32_tb /home/hnpark2/prefetchit/benchmarks/neorv32/sim "bash ghdl.sh --stop-time=20ms" 150
echo GHDL_DONE
