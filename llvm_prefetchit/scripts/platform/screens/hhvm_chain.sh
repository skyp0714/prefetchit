#!/usr/bin/env bash
set -u
until ! pgrep -x apt-get >/dev/null; do sleep 10; done
echo ps101899 | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y libpcre3 > /tmp/apt_pcre.log 2>&1; echo "libpcre3 rc=$?"
export LD_LIBRARY_PATH="/opt/local/hhvm-3.30/lib:${LD_LIBRARY_PATH:-}"
/usr/local/bin/hhvm --version 2>&1 | head -2
ls /opt/local/hhvm-3.30/lib | head -5
echo HHVM_CHAIN_DONE
