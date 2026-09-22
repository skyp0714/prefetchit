#!/usr/bin/env bash
# PHP 8.3 php-fpm baseline (clang-19 -O3 -g) and pass variants: build_php.sh base|VARIANT [PLAN]
set -euo pipefail
V=${1:-base}; PLAN=${2:-}; ROOT=/home/hnpark2/prefetchit; P=$ROOT/benchmarks/php; LLVM=$ROOT/llvm_prefetchit
cd $P; [[ -f php-8.3.14.tar.gz ]] || curl -sSL -o php-8.3.14.tar.gz https://www.php.net/distributions/php-8.3.14.tar.gz
[[ -d php-8.3.14 ]] || tar xzf php-8.3.14.tar.gz
rm -rf build_$V; cp -r php-8.3.14 build_$V; cd build_$V
F="-O3 -g -fno-omit-frame-pointer"; [[ "$V" != base ]] && F="$F -fpass-plugin=$LLVM/build/PrefetchITPass.so"
[[ -n "$PLAN" ]] && export PREFETCHIT_PLAN=$PLAN
CC=clang-19 CFLAGS="$F" ./configure --prefix=$P/install_$V --enable-fpm --with-fpm-user=www-data --with-fpm-group=www-data --with-mysqli --with-pdo-mysql --enable-mbstring --with-openssl --with-zlib --with-curl --enable-opcache --disable-cgi > configure.log 2>&1
make -j32 > make.log 2>&1; make install > install.log 2>&1
echo "PHP $V BUILD DONE $(ls $P/install_$V/sbin/php-fpm)"; grep -c "prefetchit-inject: injected=[1-9]" make.log || true
