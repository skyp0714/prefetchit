#!/usr/bin/env bash
set -euo pipefail

if [[ "$(. /etc/os-release; echo "${ID}")" != "ubuntu" ]]; then
  echo "[err] this helper supports Ubuntu only" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  autoconf automake ant bc bison build-essential clang-19 cmake curl docker.io \
  flex gfortran git git-lfs jq libaio-dev libboost-all-dev libdwarf-dev \
  libevent-dev libgflags-dev libgoogle-glog-dev libgrpc++-dev libjemalloc-dev \
  libopenblas-dev libpfm4-dev libprotobuf-dev libssl-dev libtool libunwind-dev \
  libzstd-dev lld-19 llvm-19 llvm-19-dev meson nasm ninja-build numactl \
  patch pkg-config protobuf-compiler protobuf-compiler-grpc python3-dev \
  python3-pip python3-venv ripgrep sysstat unzip wget zlib1g-dev

git lfs install
echo "[done] common host dependencies installed"
echo "[note] install a perf binary built for the running kernel separately"
