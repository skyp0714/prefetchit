# Realistic-setting screen (2026-09-18) — summary

Rule: server pinned to 4 cores (PG/MariaDB: 4-7), load raised until the cores are near saturation; user-mode L2I MPKI over 30 s.

## Databases (4 pinned cores, client sweep)

| workload | config | clients | tps | util | MPKI (user) | IPC |
|---|---|---:|---:|---:|---:|---:|
| postgresql | tpcb | 4 | 6323 | 30.9% | **13.26** | 0.961 |
| postgresql | tpcb | 8 | 13392 | 48.5% | **6.64** | 1.067 |
| postgresql | tpcb | 16 | 29144 | 84.2% | 0.13 | 1.472 |
| postgresql | tpcb | 32 | 31685 | 90.6% | 0.15 | 1.459 |
| postgresql | tpcb | 64 | 30363 | 93.7% | 0.28 | 1.210 |
| postgresql | select | 4 | 89040 | 43.0% | **2.01** | 1.395 |
| postgresql | select | 8 | 199492 | 81.1% | 0.20 | 1.459 |
| postgresql | select | 16 | 245855 | 92.4% | 0.01 | 1.550 |
| postgresql | select | 32 | 250743 | 93.8% | 0.00 | 1.434 |
| postgresql | select | 64 | 234129 | 94.3% | 0.02 | 1.253 |
| mariadb_oltp_read_write | durable | 4 | 1951 | 38.0% | **6.18** | 1.539 |
| mariadb_oltp_read_write | durable | 8 | 2780 | 52.9% | **4.93** | 1.545 |
| mariadb_oltp_read_write | durable | 16 | 5134 | 83.5% | **1.47** | 1.822 |
| mariadb_oltp_read_write | durable | 32 | 4443 | 71.9% | **1.30** | 1.856 |
| mariadb_oltp_read_write | durable | 64 | 3293 | 54.5% | **1.23** | 1.839 |
| mariadb_oltp_read_only | durable | 4 | 2738 | 43.2% | **7.16** | 1.613 |
| mariadb_oltp_read_only | durable | 8 | 4165 | 57.0% | **4.24** | 1.760 |
| mariadb_oltp_read_only | durable | 16 | 9043 | 95.8% | 0.15 | 2.353 |
| mariadb_oltp_read_only | durable | 32 | 9373 | 96.5% | 0.19 | 2.356 |
| mariadb_oltp_read_only | durable | 64 | 9052 | 96.5% | 0.28 | 2.266 |
| mariadb_oltp_read_write | fast | 4 | 2392 | 46.1% | **6.87** | 1.513 |
| mariadb_oltp_read_write | fast | 8 | 3386 | 57.9% | **5.02** | 1.563 |
| mariadb_oltp_read_write | fast | 16 | 6701 | 94.3% | 0.80 | 1.995 |
| mariadb_oltp_read_write | fast | 32 | 6926 | 96.1% | 0.87 | 2.012 |
| mariadb_oltp_read_write | fast | 64 | 6831 | 96.5% | 0.96 | 1.927 |
| mariadb_oltp_read_only | fast | 4 | 2736 | 43.1% | **7.64** | 1.596 |
| mariadb_oltp_read_only | fast | 8 | 3530 | 51.4% | **7.06** | 1.558 |
| mariadb_oltp_read_only | fast | 16 | 9461 | 95.9% | 0.13 | 2.423 |
| mariadb_oltp_read_only | fast | 32 | 9425 | 96.6% | 0.18 | 2.374 |
| mariadb_oltp_read_only | fast | 64 | 9123 | 96.6% | 0.28 | 2.285 |

Reading: both databases show 5–13 MPKI while under-utilized (backends sleep between transactions, L2 cools) and ≤0.3 MPKI at the knee;
the only ≥1 point at a realistic utilization is MariaDB oltp_read_write with durable defaults at 16 threads (1.47, 84% util).


## μSuite Router (leaf + mid-tier + memcached on cores 36-39, open-loop qps sweep)

| qps | tier | util | MPKI (user) | IPC | p50 / p99 (ms) |
|---:|---|---:|---:|---:|---|
| 1000 | leaf | 2.9% | **55.05** | 0.433 | 0.832 / 1.525 |
| 1000 | midtier | 8.0% | **110.28** | 0.222 | 0.832 / 1.525 |
| 2000 | leaf | 4.5% | **39.84** | 0.535 | 0.58 / 1.304 |
| 2000 | midtier | 13.2% | **77.71** | 0.277 | 0.58 / 1.304 |
| 4000 | leaf | 6.5% | **21.05** | 0.717 | 0.425 / 1.136 |
| 4000 | midtier | 19.8% | **35.80** | 0.401 | 0.425 / 1.136 |
| 8000 | leaf | 10.1% | **3.67** | 1.025 | 0.332 / 0.804 |
| 8000 | midtier | 31.1% | **4.80** | 0.609 | 0.332 / 0.804 |
| 12000 | leaf | 12.3% | **1.81** | 1.110 | 0.516 / 0.933 |
| 12000 | midtier | 44.1% | **1.41** | 0.672 | 0.516 / 0.933 |
| 16000 | leaf | 11.5% | **3.41** | 0.962 | 109.902 / 5569.34 |
| 16000 | midtier | 63.0% | 0.94 | 1.372 | 109.902 / 5569.34 |
| 24000 | leaf | 11.3% | **3.56** | 0.922 | 401.263 / 14943.6 |
| 24000 | midtier | 62.5% | 0.92 | 1.473 | 401.263 / 14943.6 |

Reading: 55–110 MPKI at 3–8% utilization falls to 1.4–1.8 at 12k qps (mid-tier 44% busy) and 0.9–3.6 at 16–24k qps, where the
load generator itself saturates (p99 5–15 ms). The single-threaded load generator cannot drive the 4 cores past ~60%; at the highest
clean point (12k qps) the Router is a marginal candidate (leaf 1.8, mid-tier 1.4).


## DeathStarBench socialNetwork, every container pinned (cpusets sized from CPU share at 4k req/s; nginx capped so all 27 fit in 36 cores), mixed load 4,000 req/s (nginx-bound: 97% of its 7 cores)

| container | cores | util | MPKI (user) | IPC | instr (30 s) |
|---|---|---:|---:|---:|---:|
| nginx-thrift-1 | 0-6 | 96.9% | **1.31** | 1.221 | 881.5 G |
| post-storage-service-1 | 7-10 | 46.7% | 0.24 | 2.635 | 384.0 G |
| post-storage-memcached-1 | 23 | 32.1% | 0.04 | 1.066 | 4.1 G |
| post-storage-mongodb-1 | 30 | 28.1% | **26.40** | 0.576 | 12.9 G |
| user-timeline-mongodb-1 | 35 | 25.7% | **4.07** | 2.191 | 51.0 G |
| home-timeline-service-1 | 21 | 25.1% | 0.16 | 2.381 | 30.9 G |
| home-timeline-redis-1 | 22 | 20.6% | **17.58** | 0.379 | 5.1 G |
| user-timeline-service-1 | 11 | 18.2% | **1.29** | 1.794 | 13.0 G |
| compose-post-service-1 | 12 | 11.7% | **3.27** | 1.248 | 4.0 G |
| text-service-1 | 18 | 9.9% | **1.74** | 2.735 | 16.1 G |
| url-shorten-mongodb-1 | 34 | 9.2% | **12.59** | 0.737 | 10.1 G |
| social-graph-service-1 | 13 | 5.6% | **37.51** | 0.551 | 1.4 G |
| url-shorten-service-1 | 17 | 5.4% | **24.63** | 0.736 | 1.8 G |

Reading: the only saturated container is nginx-thrift (97%, 1.3 MPKI); the C++ services run at 10–47% of their single core and show 0.2–3.3
MPKI (user-timeline 1.3, compose-post 3.3, text 1.7); the 3–6%-utilized containers show the familiar cold-L2 numbers (25–80 MPKI) but
execute <2 G instructions in 30 s. The stack is front-end-bound: to load the services harder nginx needs more cores than the 36-core pool allows.


## DeathStarBench hotelReservation (Go), per-container cpusets from CPU share, mixed load 3,000 req/s (reservation-1 saturates at 5k: 95% of 4 cores)

| container | cores | util | MPKI (user) | IPC | instr (30 s) |
|---|---|---:|---:|---:|---:|
| reservation-1 | 0-3 | 61.7% | 0.32 | 3.089 | 785.8 G |
| frontend-1 | 6-7 | 39.4% | **1.25** | 1.359 | 63.3 G |
| rate-1 | 4-5 | 39.1% | **1.30** | 2.535 | 174.9 G |
| profile-1 | 10 | 33.4% | **4.26** | 1.624 | 35.0 G |
| search-1 | 8-9 | 32.7% | **3.98** | 1.608 | 67.6 G |
| geo-1 | 12 | 28.9% | **4.64** | 1.541 | 32.7 G |
| memcached-reserve-1 | 15 | 23.8% | 0.91 | 1.313 | 23.8 G |
| recommendation-1 | 11 | 17.4% | **9.08** | 1.278 | 13.9 G |

## DeathStarBench mediaMicroservices (C++), per-container cpusets, compose-review load 2,000 req/s (compose-review-service 95% of 2 cores at 3k)

| container | cores | util | MPKI (user) | IPC | instr (30 s) |
|---|---|---:|---:|---:|---:|
| compose-review-service-1 | 0-1 | 68.2% | **4.81** | 0.993 | 45.5 G |
| movie-review-mongodb-1 | 18 | 48.3% | **3.84** | 1.778 | 83.9 G |
| user-review-mongodb-1 | 17 | 47.2% | **3.99** | 1.865 | 83.0 G |
| nginx-web-server-1 | 25 | 46.0% | **2.53** | 1.222 | 38.0 G |
| movie-id-service-1 | 31 | 43.6% | **4.83** | 0.955 | 14.4 G |
| user-review-service-1 | 29 | 35.3% | **2.42** | 1.060 | 17.8 G |
| compose-review-memcached-1 | 9 | 35.1% | 0.66 | 1.286 | 5.1 G |
| movie-review-service-1 | 33 | 34.0% | **2.17** | 1.062 | 17.6 G |
| rating-service-1 | 32 | 29.8% | **2.30** | 1.127 | 11.2 G |
| review-storage-service-1 | 24 | 21.0% | **23.51** | 0.727 | 9.8 G |
| user-service-1 | 30 | 17.6% | **1.18** | 1.502 | 9.8 G |
| review-storage-mongodb-1 | 16 | 15.0% | **41.70** | 0.543 | 6.3 G |
| unique-id-service-1 | 23 | 13.6% | **3.05** | 1.380 | 7.9 G |
| text-service-1 | 22 | 11.4% | **3.31** | 1.347 | 4.8 G |

Reading (both stacks): only the bottleneck service can be saturated in a request chain; the others sit at 15–50% of their cores. At those
utilizations the Go hotel services show 1.3–4.6 MPKI (search 4.0 @33%, geo 4.6 @29%, profile 4.3 @33%, recommendation 9.1 @17%; the saturated
reservation service 0.3 @62%), and the C++ media services 2.2–4.8 (compose-review 4.8 @68%, movie-id 4.8 @44%, nginx 2.5 @46%; mongodb 3.8–4.0 @47%).
These are candidates, with the caveat that their utilization is production-like (30–70%) rather than saturated.

μSuite SetAlgebra: load generator aborts at start (known heap-corruption race in the loadgen; not screened). HDSearch: mid-tier argument format differs from the screen script and the leaf has the protobuf CHECK crash (not screened).

## Why is the code-miss rate high at low utilization? PostgreSQL diagnostic (server on 36-39, 4 cores; pgbench TPC-B)

| config | clients | tps | util | MPKI (user) | IPC |
|---|---:|---:|---:|---:|---:|
| default (backends float inside the cpuset) | 1 | 3,265 | 12% | 2.3 | 1.89 |
| default | 2 | 5,528 | 20% | 5.2 | 1.53 |
| default | 4 | 6,179 | 28% | **18.5** | 0.86 |
| each backend pinned to its own core | 4 | 11,277 | 41% | 3.9 | 1.57 |
| deep C-states (C6/C6P) disabled on the server cores | 4 | 12,700 | 46% | **0.06** | 1.60 |
| pinned per core + C-states disabled | 4 | 13,360 | 44% | 0.03 | 1.89 |
| pinned per core + C-states disabled | 2 | 7,240 | 22% | 0.02 | 1.94 |

Reading: the low-utilization cold misses are the idle core's **C6 flush of its L2** (every wake after a C6 residency starts from an
empty L2): disabling the deep C-states on the server cores takes the miss rate from 18.5 to 0.06 and doubles throughput at the same
client count; backend migration inside the cpuset is a secondary factor (pinning alone: 3.9). This is the same mechanism found for
home-timeline yesterday (5.3 → 0.1 with C6 off) and it defines the "high-MPKI side": pinned cores that idle between requests.

## MariaDB on the high-MPKI side (durable defaults, server on 36-39, sysbench 1/2/4 threads)

| workload | threads | tps | util | MPKI (user) | IPC |
|---|---:|---:|---:|---:|---:|
| oltp_read_write | 1 | 571 | 11% | 5.6 | 1.69 |
| oltp_read_write | 2 | 1,021 | 22% | 10.3 | 1.35 |
| oltp_read_write | 4 | 1,882 | 40% | **11.7** | 1.27 |
| oltp_read_only | 1 | 755 | 12% | 7.5 | 1.69 |
| oltp_read_only | 2 | 1,339 | 23% | 8.4 | 1.59 |
| oltp_read_only | 4 | 2,553 | 42% | **8.8** | 1.55 |

Reading: same mechanism as PostgreSQL (one multi-threaded server whose worker threads wake on whichever of the 4 cores is free); at
threads = cores and ~40% utilization MariaDB shows 9–12 MPKI, versus 0.2–1.5 when saturated with 16+ threads.

## JVM suites on 4 pinned cores (8-11), JDK 21, -Xms/-Xmx 8g, user-mode counters over a 20 s steady window

| suite / benchmark | MPKI (user) | IPC |
|---|---:|---:|
| dacapo/tomcat | **4.88** | 1.384 |
| dacapo/spring | **2.75** | 1.854 |
| dacapo/tradesoap | **2.58** | 2.172 |
| dacapo/avrora | **2.49** | 1.306 |
| dacapo/kafka | **2.41** | 1.298 |
| dacapo/jme | **2.16** | 1.738 |
| renaissance/dotty | **1.87** | 1.757 |
| renaissance/finagle-chirper | **1.18** | 2.067 |
| dacapo/tradebeans | **1.17** | 2.720 |
| renaissance/log-regression | **1.16** | 2.264 |
| renaissance/movie-lens | 0.99 | 1.943 |
| dacapo/eclipse | 0.97 | 1.920 |
| dacapo/pmd | 0.92 | 2.486 |
| renaissance/dec-tree | 0.73 | 2.210 |
| renaissance/gauss-mix | 0.59 | 3.756 |

Below 0.5: renaissance/finagle-http 0.36, dacapo/h2 0.31, dacapo/xalan 0.30, renaissance/future-genetic 0.28, renaissance/als 0.21, renaissance/akka-uct 0.13, renaissance/naive-bayes 0.13, renaissance/chi-square 0.12, renaissance/page-rank 0.10, renaissance/rx-scrabble 0.09, renaissance/db-shootout 0.09, renaissance/fj-kmeans 0.08, renaissance/scala-stm-bench7 0.08, dacapo/luindex 0.07, dacapo/lusearch 0.06, dacapo/biojava 0.05, dacapo/zxing 0.05, renaissance/neo4j-analytics 0.05, renaissance/philosophers 0.05, dacapo/jython 0.04, dacapo/zxing 0.04, renaissance/scrabble 0.04, renaissance/reactors 0.04, renaissance/scala-kmeans 0.04, dacapo/batik 0.03, renaissance/par-mnemonics 0.03, renaissance/mnemonics 0.02, dacapo/graphchi 0.01, dacapo/sunflow 0.01, renaissance/scala-doku 0.01.

Reading: with the JVM's pools sized to 4 cores the icache-heavy DaCapo servers stay above 1 (tomcat 4.9, spring 2.8, tradesoap 2.6, avrora 2.5,
kafka 2.4, jme 2.2, tradebeans 1.2) and three Renaissance benchmarks cross 1 (dotty 1.9, finagle-chirper 1.2, log-regression 1.2); the earlier
unpinned 8-core numbers (future-genetic 9.3, cassandra 13) do not survive pinning (future-genetic 0.28; cassandra/h2o/fop rerunning with JDK-21 flags).
CloudSuite media-streaming: the dataset container must be *run* (it generates the videos) — skipped for now (static nginx file serving).


## JVM candidates on 8 pinned cores (8-15), same JDK/heap — does more idle per core raise the miss rate?

| benchmark | 4 cores MPKI | 8 cores MPKI | 8-core IPC | note |
|---|---:|---:|---:|---|
| dacapo/tomcat | 4.9 | **10.8** | 1.13 | request threads idle more per core → more C6 wakes |
| dacapo/avrora | 2.5 | 84.1 | 0.27 | only 2.9 G instructions in the 20 s window at 8 cores (threads mostly asleep) — wake-up misses, not a code stream |
| dacapo/kafka | 2.4 | 3.1 | 1.25 | |
| dacapo/tradesoap | 2.6 | 3.0 | 2.09 | |
| dacapo/spring | 2.8 | 3.0 | 1.64 | |
| dacapo/cassandra (JDK-21 flags) | 3.3 | 2.4 | 1.16 | |
| dacapo/jme | 2.2 | 2.1 | 1.70 | |
| dacapo/tradebeans | 1.2 | 1.4 | 2.68 | |
| renaissance/dotty | 1.9 | 1.8 | 1.76 | |
| renaissance/log-regression | 1.2 | 1.5 | 2.02 | |
| renaissance/finagle-chirper | 1.2 | 1.3 | 1.93 | |

dacapo/fop finishes in under 40 s (not measured); dacapo/h2o fails to start under JDK 21.

## CloudSuite web-serving (elgg on nginx + php-fpm 8.1, JIT on; web server on cores 4-7 with 8 fpm children / 4 nginx workers; mysql on 12-15, memcached 16-17; faban client scale 25–400)

| faban scale | ops/s (client) | web-server util | MPKI (user) | IPC |
|---:|---:|---:|---:|---:|
| 25 | 15 | 17% | **6.9** | 1.21 |
| 50 | 22 | 15% | **7.3** | 1.20 |
| 100 | 21 | 18% | **6.6** | 1.21 |
| 200 | 18 | 11% | **6.7** | 1.20 |
| 400 | 11 | 16% | **6.8** | 1.20 |

Reading: the faban driver is think-time bound (ops/s barely moves with scale), so the web tier sits at 11–18% of its 4 cores with a stable
6.6–7.3 MPKI — a candidate at exactly the kind of moderate utilization the user prefers; cause to be diagnosed with a C6-off pass.

## Miss-cause diagnostic — servers (same pinned cores; C6 off = deep C-states disabled on those cores; 1 core = whole server on one core)

| workload | default (4 cores) | C6 off (4 cores) | C6 off, 1 core | default, 1 core | cause |
|---|---:|---:|---:|---:|---|
| MariaDB oltp_read_write, 4 threads | 11.7 (40% util) | 0.87 (59%) | 1.07 (84%) | 1.29 (82%) | **cold (C6 wake)** — a busy single core never idles either |
| μSuite Router leaf, 1k qps | 55.0 (3%) | 0.06 | 1.04 | 12.7 | **cold (C6 wake)** |
| μSuite Router mid-tier, 1k qps | 110.3 (8%) | 0.11 | 0.91 | 19.3 | **cold (C6 wake)** |
| PostgreSQL TPC-B, 4 clients | 18.5 (28%) | 0.06 | — | — | **cold (C6 wake)** (+ migration: pinned backends 3.9) |

## CloudSuite web-search (Solr 9 on cores 4-7, 12 GB heap; faban client 25–400 workers — the driver still logs request errors, so loads are partial)

| workers | Solr util | MPKI (user) | IPC | instr (30 s) |
|---:|---:|---:|---:|---:|
| 25 | 4% | **4.4** | 1.59 | 10 G |
| 50 | 2% | **3.4** | 1.81 | 16 G |
| 100 | 3% | **2.0** | 2.11 | 22 G |
| 200 | 7% | **2.8** | 1.94 | 46 G |
| 400 | 11% | **1.6** | 2.22 | 91 G |

Reading: the miss rate falls as the load rises (4.4 → 1.6), the cold-wake signature again; Solr never exceeds 11% of its cores with this
client, so it is a low-utilization candidate only. CloudSuite data-serving: the YCSB warm-up script was not found at the path the
client documents, the run phase executed against an empty table (server at 0.4% util) — not measured.

## Miss-cause diagnostic — JVM candidates (4 pinned cores 8-11; C6 off; C6 off on one core; default on one core)

| benchmark | default 4 cores | C6 off 4 cores | C6 off, 1 core | default, 1 core | cause |
|---|---:|---:|---:|---:|---|
| dacapo/tomcat | 4.9 | 3.0 | 3.9 | 11.8 | **cold + capacity**: 40% is C6 wake (a lone idling core → 11.8), 60% survives (request-handling code > L2) |
| dacapo/spring | 2.8 | 2.9 | 3.8 | 4.4 | **capacity** (+ thread interleaving on one core) |
| dacapo/cassandra | 3.3 | 3.2 | 22.5 | 22.8 | **capacity, multi-thread amplified**: threads sharing one L2 thrash it 7× |
| renaissance/dotty | 1.9 | 1.85 | 3.9 | 3.7 | **capacity + multi-thread** |
| renaissance/finagle-chirper | 1.2 | 1.16 | 0.9 | 1.0 | **capacity** |
| renaissance/log-regression | 1.2 | 0.83 | 1.0 | 1.0 | mixed (cold ~30%, capacity ~70%) |
| dacapo/tradesoap | 2.6 | 1.2 | 0.8 | 0.85 | mixed (cold ~55%, capacity ~45%) |
| dacapo/avrora | 2.5 | 0.04 | 0.02 | 0.02 | **cold (C6 wake)** |
| dacapo/jme | 2.2 | 0.41 | 0.66 | 2.45 | **cold (C6 wake)** |
| dacapo/tradebeans | 1.2 | 0.07 | 0.06 | 0.06 | **cold (C6 wake)** |
| dacapo/kafka | 2.4 (8 cores 3.1) | — | — | — | not diagnosed (the -n 60 run exits before the window) |

## socialNetwork again with a 43-core pool (nginx 12 cores, post-storage 3), fresh stack, mixed load 6,000 req/s (nginx 88%; 8k overloads it)

| container | cores | util | MPKI (user) | IPC | instr (30 s) |
|---|---|---:|---:|---:|---:|
| post-storage-service-1 | 12-14 | 92.0% | 0.25 | 2.671 | 575.2 G |
| nginx-thrift-1 | 0-11 | 87.7% | **1.31** | 1.253 | 1324.4 G |
| post-storage-memcached-1 | 29 | 46.6% | 0.04 | 1.069 | 6.2 G |
| home-timeline-service-1 | 18 | 37.9% | 0.12 | 2.364 | 46.1 G |
| post-storage-mongodb-1 | 38 | 33.1% | **18.31** | 0.703 | 19.0 G |
| user-timeline-service-1 | 22 | 27.2% | **1.15** | 1.926 | 20.5 G |
| home-timeline-redis-1 | 30 | 26.0% | **14.62** | 0.464 | 7.4 G |
| compose-post-service-1 | 19 | 16.9% | **1.95** | 1.423 | 6.1 G |
| user-timeline-mongodb-1 | 37 | 16.5% | **28.11** | 0.759 | 9.8 G |
| text-service-1 | 16 | 12.7% | 0.52 | 3.224 | 24.1 G |
| user-timeline-redis-1 | 26 | 11.9% | **48.18** | 0.476 | 2.0 G |
| url-shorten-mongodb-1 | 34 | 11.6% | **40.45** | 0.516 | 4.5 G |
| social-graph-service-1 | 17 | 7.5% | **31.72** | 0.627 | 2.1 G |
| user-mention-service-1 | 25 | 6.5% | **14.50** | 0.872 | 1.3 G |
| url-shorten-service-1 | 15 | 5.7% | **11.28** | 1.112 | 2.7 G |

Reading: same as the 36-core pass — the thrift services stay at 5–38% of one core (compose-post 2.0, user-timeline 1.2, nginx 1.3 MPKI);
the near-idle services and stores show 11–80 MPKI on <10 G instructions. The C++ tier of socialNetwork is not a strong candidate at any
realistic load; its front end (OpenResty/LuaJIT) is the busy part and sits at 1.3.


## Miss-cause diagnostic — microservice stacks (same per-container cpusets; deep C-states disabled on the pool cores)

### hotelReservation (Go) — 3,000 req/s; the C6-off pass served only 1.8k req/s (reservation-1 saturated), so utilizations are lower there

| container | default MPKI (util) | C6 off MPKI (util) | cause |
|---|---:|---:|---|
| recommendation-1 | 9.08 (17%) | 0.10 (5%) | **cold (C6 wake)** |
| geo-1 | 4.64 (29%) | 0.06 (11%) | **cold (C6 wake)** |
| profile-1 | 4.26 (33%) | 0.28 (9%) | **cold (C6 wake)** |
| search-1 | 3.98 (33%) | 0.42 (15%) | **cold (C6 wake)** |
| rate-1 | 1.30 (39%) | 0.19 (26%) | **cold (C6 wake)** |
| frontend-1 | 1.25 (39%) | 0.53 (13%) | mixed (cold 58% / capacity 42%) |

### mediaMicroservices (C++) — 2,000 req/s

| container | default MPKI (util) | C6 off MPKI (util) | cause |
|---|---:|---:|---|
| review-storage-mongodb-1 | 41.70 (15%) | 0.33 (4%) | **cold (C6 wake)** |
| review-storage-service-1 | 23.51 (21%) | 0.09 (8%) | **cold (C6 wake)** |
| movie-id-service-1 | 4.83 (44%) | 4.86 (23%) | **capacity** |
| compose-review-service-1 | 4.81 (68%) | 3.81 (100%) | **capacity** |
| user-review-mongodb-1 | 3.99 (47%) | 1.41 (24%) | mixed (cold 65% / capacity 35%) |
| movie-review-mongodb-1 | 3.84 (48%) | 1.41 (25%) | mixed (cold 63% / capacity 37%) |
| text-service-1 | 3.31 (11%) | 0.75 (7%) | **cold (C6 wake)** |
| unique-id-service-1 | 3.05 (14%) | 0.74 (9%) | **cold (C6 wake)** |
| nginx-web-server-1 | 2.53 (46%) | 3.62 (21%) | **capacity** |
| user-review-service-1 | 2.42 (35%) | 0.65 (25%) | **cold (C6 wake)** |
| rating-service-1 | 2.30 (30%) | 2.21 (19%) | **capacity** |
| movie-review-service-1 | 2.17 (34%) | 0.59 (29%) | **cold (C6 wake)** |
| user-service-1 | 1.18 (18%) | 1.13 (12%) | **capacity** |

Reading: the Go hotel services are pure cold-wake cases (search 4.0 → 0.4, geo 4.6 → 0.06, profile 4.3 → 0.3, recommendation 9.1 → 0.1),
while the C++ media services keep most of their misses with C6 off (movie-id 4.8 → 4.9, compose-review 4.8 → 3.8, nginx 2.5 → 3.6, rating 2.3 → 2.2):
capacity misses of a request path larger than the L2 — the kind a static prefetch can address.


## CloudSuite data-serving (Cassandra 4, YCSB workload A, 1 M records; server on cores 4-7) and data-caching (memcached, 4 threads; corrected client)

| benchmark | load | server util | MPKI (user) | IPC |
|---|---:|---:|---:|---:|
| data-serving | 5k ops/s | 26% | **3.9** | 0.78 |
| data-serving | 10k ops/s | 36% | **3.0** | 0.73 |
| data-serving | 20k ops/s | 48% | **2.2** | 0.81 |
| data-serving | 40k ops/s | 70% | **1.3** | 1.16 |
| data-serving | 80k ops/s | 83% | 0.84 | 1.02 |
| data-caching | 100k rps | 35% | **1.3** | 0.89 |
| data-caching | 200k rps (C6 off: 0.04) | 59% | 0.05 | 0.84 |
| data-caching | 400k / 700k rps | 79% / 78% | 0.06 / 0.06 | 0.79 / 0.81 |
| web-search | 50 workers, C6 off | 2% | 2.5 (default 3.4) | 1.94 |

Reading: data-serving follows the cold-wake curve (3.9 → 0.8 as the load rises); data-caching is only marginal at low load (1.3 at 35%,
≤0.06 above 200k rps — memcached's request path fits the L2); web-search keeps 75% of its misses with C6 off → mostly capacity (Solr).

# 2026-09-19 — capacity/interleaving-only sweep (deep C-states disabled on the cores in use; everything else realistic)

Two regimes per microservice stack: **alone** = each container on its own cpuset (sized from its CPU share), **interleaved** = all containers
of the stack share one pool of 8 or 16 cores (the "lukewarm" setting of the serverless/microservice literature: other services evict a
service's code between its requests). Databases and JVM suites: pinned 4 cores. Table: `C6OFF_TABLE.md` (`compile_c6off.py`).

Findings:
- Databases: PostgreSQL 0.05–0.09 MPKI at every client count; MariaDB durable read-write 0.8–1.1 → out (MariaDB marginal).
- JVM: capacity misses of 1–3 MPKI survive (cassandra 3.2, tomcat 3.0, spring 2.9, dotty 1.9, tradesoap 1.2, finagle-chirper 1.2).
- Alone (pinned, C6 off): media C++ services 3.6–4.9 (movie-id, compose-review, nginx), rating 2.2, user-service 1.1; socialNetwork
  compose-post 1.0, user-timeline 1.1, nginx-thrift 1.2; hotel (Go) ≤0.5; stores ≤2.3.
- Interleaved (8- or 16-core pool, C6 off, 40–75% pool utilization): the same services jump to **34–55 MPKI (media), 9–44 (socialNetwork
  compose-post 42, user-timeline 9, home-timeline 8, text 4), 3–16 (hotel Go)**, stores 14–105; only the CPU-heavy tiers stay low
  (post-storage 1.8, nginx-thrift 2.1–2.3, hotel reservation 0.15). MPKI is nearly identical for the 8- and 16-core pools → it is the
  interleaving itself (code evicted by neighbours between requests), not the pool size, that sets the miss rate.
- DCPerf v2 (pinned): DjangoBench v2 (4 uwsgi workers, CPython) 2.4 MPKI at 67–69% util → candidate on AOT C; TaoBench 0.3 → out;
  FeedSim v2 pending (needed the Silesia corpus and TLS certs the installer did not provide).

## DCPerf v2 (worktree benchmarks/dcperf_v2 = v2-beta b109b09; ICacheBuster removed) — pinned screens

| job | placement | util | MPKI (user) default / C6 off | IPC | note |
|---|---|---:|---:|---:|---|
| django_workload_default (DjangoBench v2: 4 uwsgi workers, CPython, thrift mock backends, wrk client) | uwsgi on 36-39, Cassandra/thrift/haproxy on 40-42, wrk on 60-67 | 68% | 2.40 / 2.42 | 1.6 | capacity misses in the CPython interpreter + Django code; AOT C → static-pass candidate |
| feedsim_dlrm (FeedSim v2: LeafNodeRank + DLRM inference, mock_services on cores 0-7 by run.sh) | LeafNodeRank on 20-27, drivers on 60-67 | 19% | 2.11 / 2.34 | 1.7 | QPS search converged at 60 qps on 8 cores (p95 ≤ 700 ms); C++ AOT → candidate at low utilization |
| tao_bench_standalone | 28-35 | 42% | 0.27 | 1.5 | the job's own clients reported 0 qps (memtier not started) → unvalidated; memcached-derived, expected ≤0.3 |

v1 → v2 note: the v1 Django/FeedSim results in this repository (manual ICacheBuster prefetch 1.49x / 1.07x) targeted code that no longer
exists in v2; any DCPerf prefetch work must restart from the v2 binaries above.
