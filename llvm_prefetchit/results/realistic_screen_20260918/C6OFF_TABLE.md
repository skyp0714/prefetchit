# Capacity/interleaving-only sweep (deep C-states disabled on the server cores)

| workload | setting (C6 off) | util | MPKI alone (capacity) | MPKI interleaved pool8 / pool16 | IPC | code kind → remedy |
|---|---|---:|---:|---:|---:|---|
| FleetBench fleetbench/proto/proto_benchmark | core 36, C6 off | 100% | 16.92 | — | 0.70 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| TailBench silo | 0-3, C6 off, 1000 qps (other load 250 qps 9.79) | 3% | 9.76 | — | 0.17 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| CloudSuite web-serving | scale50, 4 cores, C6 off | 9% | 4.98 | — | 1.31 | JIT (php-fpm opcache): AOT pass n/a |
| mediamicroservices/movie-id-service-1 | alone 2 core(s) 23% util; pool8 53% cpu; pool16 107% cpu | 23% | 4.86 | 55.29/53.98 | 0.99 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| dacapo/cassandra | 4 cores, C6 off, jdk17 | 58% | 4.27 | — | 1.20 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| mediamicroservices/compose-review-service-1 | alone 1 core(s) 100% util; pool8 121% cpu; pool16 244% cpu | 100% | 3.81 | 38.07/38.25 | 1.11 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| mediamicroservices/nginx-web-server-1 | alone 2 core(s) 21% util; pool8 43% cpu; pool16 80% cpu | 21% | 3.62 | 25.95/22.04 | 1.16 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| dacapo/tomcat | 4 cores, C6 off, java-21 | 9% | 2.98 | — | 1.52 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| dacapo/spring | 4 cores, C6 off, java-21 | 37% | 2.88 | — | 1.87 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| DCPerf v2 django_workload_default | 36-39 server cores, noC6 (default 2.40), util 68% | 68% | 2.42 | — | 1.57 | C AOT (single link unit): cold plan with file-qualified sites |
| DCPerf v2 feedsim_dlrm | 20-27 server cores, noC6 (default 2.11), util 19% | 19% | 2.34 | — | 1.67 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| socialnetwork/post-storage-mongodb-1 | alone 1 core(s) 23% util; pool8 8% cpu; pool16 23% cpu | 23% | 2.26 | 72.79/63.53 | 1.14 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| mediamicroservices/rating-service-1 | alone 2 core(s) 19% util; pool8 46% cpu; pool16 97% cpu | 19% | 2.21 | 49.00/43.18 | 1.07 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| CloudSuite data-serving | rps10000, 4 cores, C6 off | 37% | 2.07 | — | 0.87 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| renaissance/dotty | 4 cores, C6 off, java-21 | 24% | 1.85 | — | 1.75 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| dacapo/fop | 4 cores, C6 off, java-21 | 21% | 1.78 | — | 1.93 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| socialnetwork/user-timeline-mongodb-1 | alone 1 core(s) 8% util; pool8 22% cpu; pool16 23% cpu | 8% | 1.46 | 67.34/52.15 | 2.07 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| mediamicroservices/movie-review-mongodb-1 | alone 1 core(s) 25% util; pool8 42% cpu; pool16 88% cpu | 25% | 1.41 | 38.13/28.54 | 1.77 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| mediamicroservices/user-review-mongodb-1 | alone 1 core(s) 24% util; pool8 41% cpu; pool16 88% cpu | 24% | 1.41 | 38.63/28.74 | 1.99 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| TailBench masstree | 0-3, C6 off, 2000 qps (other load 500 qps 1.22) | 16% | 1.36 | — | 0.19 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| socialnetwork/nginx-thrift-1 | alone 11 core(s) 101% util; pool8 446% cpu; pool16 671% cpu | 101% | 1.21 | 2.33/2.13 | 1.29 | OpenResty/LuaJIT + nginx: nginx AOT part only (rebuild with the pass) |
| dacapo/tradesoap | 4 cores, C6 off, java-21 | 21% | 1.19 | — | 2.38 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| renaissance/finagle-chirper | 4 cores, C6 off, java-21 | 53% | 1.16 | — | 2.10 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| mediamicroservices/user-service-1 | alone 1 core(s) 12% util; pool8 22% cpu; pool16 42% cpu | 12% | 1.13 | 46.95/46.51 | 1.60 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| socialnetwork/user-timeline-service-1 | alone 1 core(s) 27% util; pool8 35% cpu; pool16 49% cpu | 27% | 1.10 | 13.34/8.89 | 1.94 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| mariadb_oltp_rw_durable | 16 clients, 4 cores, C6 off | 86% | 1.09 | — | 1.89 | C AOT (single link unit): cold plan with file-qualified sites |
| mariadb_oltp_rw_durable | 8 clients, 4 cores, C6 off | 50% | 1.05 | — | 1.84 | C AOT (single link unit): cold plan with file-qualified sites |
| socialnetwork/compose-post-service-1 | alone 1 core(s) 15% util; pool8 21% cpu; pool16 31% cpu | 15% | 1.03 | 44.24/42.05 | 1.60 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| dacapo/kafka | 4 cores, C6 off, java-21 | 18% | 0.97 | — | 1.15 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| renaissance/log-regression | 4 cores, C6 off, java-21 | 39% | 0.83 | — | 2.30 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| mariadb_oltp_rw_durable | 4 clients, 4 cores, C6 off | 45% | 0.80 | — | 1.99 | C AOT (single link unit): cold plan with file-qualified sites |
| socialnetwork/url-shorten-mongodb-1 | alone 1 core(s) 4% util; pool8 6% cpu; pool16 8% cpu | 4% | 0.80 | 42.05/37.85 | 1.48 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| mediamicroservices/text-service-1 | alone 1 core(s) 7% util; pool8 13% cpu; pool16 25% cpu | 7% | 0.75 | 47.43/48.39 | 1.60 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| mediamicroservices/unique-id-service-1 | alone 1 core(s) 9% util; pool8 16% cpu; pool16 33% cpu | 9% | 0.74 | 48.26/46.80 | 1.66 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| mediamicroservices/user-review-service-1 | alone 1 core(s) 25% util; pool8 39% cpu; pool16 91% cpu | 25% | 0.65 | 40.44/35.68 | 1.35 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/rpc/rpc_benchmark | core 36, C6 off | 100% | 0.65 | — | 1.91 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/mongodb-reservation-1 | alone 1 core(s) 0% util; pool8 1% cpu; pool16 5% cpu | 0% | 0.61 | 0.95/1.53 | 3.16 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| mediamicroservices/movie-review-service-1 | alone 1 core(s) 29% util; pool8 39% cpu; pool16 86% cpu | 29% | 0.59 | 39.91/35.70 | 1.30 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/frontend-1 | alone 4 core(s) 13% util; pool8 60% cpu; pool16 92% cpu | 13% | 0.53 | 13.07/10.92 | 1.42 | Go toolchain: no pass; would need a Go-side inserter |
| hotelreservation/search-1 | alone 4 core(s) 15% util; pool8 57% cpu; pool16 103% cpu | 15% | 0.42 | 4.63/3.19 | 1.89 | Go toolchain: no pass; would need a Go-side inserter |
| TailBench moses | 0-3, C6 off, 100 qps (other load 25 qps 0.34) | 4% | 0.42 | — | 0.95 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| dacapo/jme | 4 cores, C6 off, java-21 | 1% | 0.41 | — | 1.96 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| DCPerf v2 cdn_bench proxy_server (proxygen) | 8-11 proxy cores, noC6_rps300000; content_server 0.15 | 81% | 0.41 | — | 1.32 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| mediamicroservices/review-storage-mongodb-1 | alone 1 core(s) 4% util; pool8 14% cpu; pool16 27% cpu | 4% | 0.33 | 104.60/88.87 | 2.01 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| TailBench img-dnn | 0-3, C6 off, 500 qps (other load 125 qps 0.34) | 8% | 0.33 | — | 1.45 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/profile-1 | alone 2 core(s) 9% util; pool8 27% cpu; pool16 37% cpu | 9% | 0.28 | 13.01/11.90 | 1.89 | Go toolchain: no pass; would need a Go-side inserter |
| socialnetwork/user-mention-service-1 | alone 1 core(s) 4% util | 4% | 0.28 | —/— | 1.65 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| DCPerf v2 tao_bench_standalone | 28-35 server cores, default, util 42% | 42% | 0.27 | — | 1.50 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| CloudSuite graph-analytics | batch, 4 cores, C6 off | 99% | 0.25 | — | 2.30 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| dacapo/h2o | 4 cores, C6 off, jdk17 | 44% | 0.24 | — | 1.75 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| socialnetwork/post-storage-service-1 | alone 6 core(s) 53% util; pool8 100% cpu; pool16 186% cpu | 53% | 0.22 | 1.84/1.78 | 2.64 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/rate-1 | alone 5 core(s) 26% util; pool8 97% cpu; pool16 234% cpu | 26% | 0.19 | 0.76/0.50 | 2.73 | Go toolchain: no pass; would need a Go-side inserter |
| socialnetwork/home-timeline-redis-1 | alone 1 core(s) 14% util; pool8 12% cpu; pool16 16% cpu | 14% | 0.18 | 19.16/16.54 | 0.87 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| socialnetwork/post-storage-memcached-1 | alone 2 core(s) 30% util; pool8 22% cpu; pool16 42% cpu | 30% | 0.16 | 40.46/36.31 | 0.81 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| socialnetwork/url-shorten-service-1 | alone 1 core(s) 4% util; pool8 6% cpu; pool16 9% cpu | 4% | 0.16 | 38.10/36.35 | 2.15 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| socialnetwork/social-graph-service-1 | alone 1 core(s) 2% util; pool8 3% cpu; pool16 4% cpu | 2% | 0.15 | 21.13/22.83 | 2.26 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/memcached-reserve-1 | alone 2 core(s) 20% util; pool8 31% cpu; pool16 91% cpu | 20% | 0.12 | 0.60/0.43 | 1.34 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| socialnetwork/home-timeline-service-1 | alone 1 core(s) 41% util; pool8 33% cpu; pool16 48% cpu | 41% | 0.12 | 8.92/8.44 | 2.40 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| hotelreservation/recommendation-1 | alone 1 core(s) 5% util; pool8 10% cpu; pool16 16% cpu | 5% | 0.10 | 16.30/15.14 | 2.43 | Go toolchain: no pass; would need a Go-side inserter |
| postgresql_tpcb | 8 clients, 4 cores, C6 off | 48% | 0.09 | — | 1.38 | C AOT (single link unit): cold plan with file-qualified sites |
| postgresql_tpcb | 16 clients, 4 cores, C6 off | 82% | 0.09 | — | 1.46 | C AOT (single link unit): cold plan with file-qualified sites |
| mediamicroservices/review-storage-service-1 | alone 1 core(s) 8% util; pool8 16% cpu; pool16 32% cpu | 8% | 0.09 | 38.26/37.99 | 1.94 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| CloudSuite in-memory-analytics | batch, 4 cores, C6 off | 45% | 0.09 | — | 3.13 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| mediamicroservices/compose-review-memcached-1 | alone 1 core(s) 38% util; pool8 36% cpu; pool16 66% cpu | 38% | 0.08 | 39.60/45.66 | 1.50 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| dacapo/tradebeans | 4 cores, C6 off, java-21 | 20% | 0.07 | — | 2.96 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| hotelreservation/geo-1 | alone 1 core(s) 11% util; pool8 17% cpu; pool16 27% cpu | 11% | 0.06 | 10.06/8.20 | 2.09 | Go toolchain: no pass; would need a Go-side inserter |
| postgresql_tpcb | 4 clients, 4 cores, C6 off | 44% | 0.05 | — | 1.59 | C AOT (single link unit): cold plan with file-qualified sites |
| socialnetwork/text-service-1 | alone 1 core(s) 11% util; pool8 11% cpu; pool16 17% cpu | 11% | 0.05 | 4.47/4.41 | 3.51 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| dacapo/avrora | 4 cores, C6 off, java-21 | 12% | 0.04 | — | 1.46 | JIT (HotSpot): AOT pass n/a; JVM-side prefetch (jit_prefetch) was neutral → BTB/i-cache warm-up or larger L2 only |
| hotelreservation/reservation-1 | alone 4 core(s) 99% util; pool8 278% cpu; pool16 855% cpu | 99% | 0.04 | 0.26/0.15 | 3.72 | Go toolchain: no pass; would need a Go-side inserter |
| CloudSuite data-caching | rps200000, 4 cores, C6 off | 59% | 0.04 | — | 0.88 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| DCPerf v2 graph500_omp_csr (batch) | pids-4ranks, C6 off, pid s in | 100% | 0.01 | — | 1.37 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| TailBench shore | 0-3, C6 off, 10 qps | 25% | 0.01 | — | 0.46 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/compression/compression_benchmark | core 36, C6 off | 100% | 0.01 | — | 1.63 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/stl/cord_benchmark | core 36, C6 off | 100% | 0.01 | — | 1.75 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/tcmalloc/empirical_driver | core 36, C6 off | 100% | 0.01 | — | 1.62 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| socialnetwork/user-timeline-redis-1 | alone n/a; pool8 7% cpu; pool16 9% cpu | 0% | 0.00 | 23.94/13.54 | 0.81 | system daemon (redis/memcached/mongodb): post-link rewriter or rebuild from source |
| DCPerf v2 liblinear_synthetic (batch) | 8-11, C6 off, 20 s in | 36% | 0.00 | — | 3.81 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| DCPerf v2 syscall_single_core (batch) | 8-11, C6 off, 40 s in | 16% | 0.00 | — | 0.12 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| DCPerf v2 schbench_default (batch) | 8-11, C6 off, 10 s in | 100% | 0.00 | — | 3.74 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| DCPerf v2 xsbench (batch) | 8-11, C6 off, 20 s in | 100% | 0.00 | — | 0.63 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| DCPerf v2 gapbs_bc (batch) | 8-11, C6 off, 15 s in | 100% | 0.00 | — | 1.49 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/swissmap/swissmap_benchmark | core 36, C6 off | 100% | 0.00 | — | 1.75 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/hashing/hashing_benchmark | core 36, C6 off | 100% | 0.00 | — | 1.51 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
| FleetBench fleetbench/libc/mem_benchmark | core 36, C6 off | 100% | 0.00 | — | 0.91 | C/C++ AOT: static pass (cold plan v10 for interleaving misses, seq mode for streams) + fat-static link |
