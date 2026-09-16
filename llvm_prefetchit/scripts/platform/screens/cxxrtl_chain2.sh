#!/usr/bin/env bash
set -u
until ! pgrep -x apt-get >/dev/null && grep -q APT_DC_DONE /tmp/apt_dc.log; do sleep 15; done
echo ps101899 | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y yosys-dev > /tmp/apt_yosysdev.log 2>&1; echo "yosys-dev rc=$? $(which yosys-config)"
H=$(dpkg -L yosys-dev 2>/dev/null | grep "cxxrtl.h$" | head -1); echo "cxxrtl.h: $H"
[[ -n "$H" ]] || { echo CXXRTL2_DONE; exit 0; }
INC=${H%/backends/cxxrtl/cxxrtl.h}
cd /tmp/screen_inputs/cxxrtl && sed -i "s|^YINC=.*|YINC=$INC|" run_cxxrtl.sh && ./run_cxxrtl.sh > /tmp/cxxrtl_run2.log 2>&1; grep -E "status=|text|error" /tmp/cxxrtl_run2.log | cut -c1-150
echo CXXRTL2_DONE
